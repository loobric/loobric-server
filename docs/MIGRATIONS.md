# Schema Migrations — Design

> Status: **Phase 1 implemented** (2026-06-21) — the ledger, runner, baseline, and startup
> wiring live in `loobric_server/migrations/` with tests; the later phases below remain proposed.
> It addresses the top data-durability gap: an upgrade that changes an existing table used to
> break a populated database with a silent `no such column` 500, with no way to tell what
> schema version a database was at.

## The problem (what exists today)

- `init_db()` (`loobric_server/database/session.py`) calls SQLAlchemy `create_all`, which creates
  **missing tables only**. It never adds columns to, or alters, existing tables — the code
  comment says so, and notes it *"bit production on the v2 cutover."*
- There is **no schema-version record** anywhere in the database. Nothing can answer
  "what version is this DB at?"
- Schema changes ship as **bespoke one-off scripts** (`scripts/migrate_m2_catalog_natural_key.py`)
  that a human must know about and run by hand. There is no registry, no ordering, no
  record of what ran.
- **Backup/restore** checks only the backup's *major* version, not whether the backup's
  schema is compatible with the running code. Restoring across a schema change fails with
  no recovery path.
- A `docker pull` of a release with a schema change → crash on first use.

## Design goals & constraints

1. **SQLite-first.** SQLite is the supported database; the spine must work within SQLite's
   limited `ALTER TABLE` (add-column is fine; drops/renames need the create-copy-swap
   pattern). PostgreSQL is exploratory — the design must not *assume* it, but must not
   preclude it.
2. **No heavy dependency.** Alembic was deliberately removed. The spine is a small,
   in-repo runner — a few hundred lines, no new runtime dep.
3. **Automatic and safe on startup.** Self-hosters upgrade by `docker pull` + restart.
   Migrations must run automatically, take a backup first, run transactionally, and on
   any failure **stop the server loudly** rather than serve a half-migrated database.
4. **Forward-only.** No down-migrations (consistent with the project's "freeze + human
   resolve, no three-way merge" ethos). Rollback = restore the pre-migration backup.
5. **Idempotent migrations.** Each migration checks before it acts (the existing M2 script
   already does this with a column-existence guard). Idempotency is belt-and-suspenders
   against imperfect baseline detection on legacy databases — **and it is mandatory on
   SQLite**, where the driver auto-commits before DDL, so a `CREATE`/`ALTER` that later
   fails is *not* rolled back. A failed migration is never recorded, so it is retried on the
   next boot; the idempotent guard makes that retry safe over partially-applied state.

## The spine

### 1. A version ledger: `schema_migrations`

One small table, the source of truth for "what has been applied":

| column | meaning |
|---|---|
| `revision` | zero-padded ordinal, e.g. `0002` — the migration's identity and sort key |
| `name` | human label, e.g. `m2_catalog_natural_key` |
| `applied_at` | UTC timestamp |
| `checksum` | hash of the migration source, to detect a migration edited after it ran |

The **current schema version** is `MAX(revision)` in this table.

### 2. Migration units: `loobric_server/migrations/NNNN_name.py`

Each migration is a Python module — full flexibility for SQLite's create-copy-swap pattern,
unlike raw `.sql`:

```python
revision = "0002"
name = "m2_catalog_natural_key"

def upgrade(conn):
    """Idempotent. Receives a live DB-API connection inside a transaction."""
    if "manufacturer_norm" in _columns(conn, "tool_catalog_records"):
        return  # already applied
    conn.execute("ALTER TABLE tool_catalog_records ADD COLUMN manufacturer_norm TEXT")
    ...
```

(The one-off `scripts/migrate_m2_catalog_natural_key.py` is **not** adopted as a migration:
it was a single-instance fix that has already run, so no database still needs it. Future
schema changes ship as `NNNN_name.py` units from the start.)

### 3. The runner: `run_migrations(engine)`

```
ensure schema_migrations exists
applied  = {rows in schema_migrations}
defined  = discover loobric_server/migrations/*.py, sorted by revision
pending  = [m for m in defined if m.revision not in applied]
if pending:
    take ONE timestamped backup before the batch (reuse loobric_server/backup.py)
    for m in pending:
        with engine.begin() as conn:   # transactional per migration
            m.upgrade(conn)
            record (revision, name, now, checksum) into schema_migrations
    log "migrated 000X → 000Y"
on any exception: log the failed revision + the backup path, re-raise → startup aborts
```

### 4. Baseline — the one genuinely hard part

Three database states must be handled:

- **Fresh DB (no tables).** `create_all` builds every current table from the models. The DB
  is already at head, so the runner **stamps every known migration as applied** without
  running them.
- **Legacy populated DB (tables exist, no `schema_migrations`).** Introduce the spine with a
  `0001_baseline` revision that represents "the schema as shipped at spine introduction."
  Stamp `0001` as applied (its `upgrade` is a no-op assertion that core tables exist), then
  apply anything newer. Future migrations live at `0002+` and, being idempotent, are safe to
  apply whether or not their effect is already present on a given legacy database.
- **Spine-managed DB.** Normal case: apply pending, done.

Detection: *tables exist but `schema_migrations` is absent* ⇒ legacy ⇒ stamp baseline.
*No tables* ⇒ fresh ⇒ `create_all` + stamp all. *`schema_migrations` present* ⇒ managed.

### 5. Startup wiring

`init_db()` becomes:

```
create_all(engine)        # greenfield bootstrap; no-op on existing tables
run_migrations(engine)    # baseline-stamp and/or apply pending
```

`create_all` stays as the greenfield path so the model definitions remain the DDL source for
*new* installs; migrations own all *changes to existing* installs.

## Closing the backup/restore drift gap — ✅ implemented

- Export stamps the **schema revision** into backup metadata (`schema_revision`), so every
  backup is self-describing.
- Restore (`_validate_backup`) compares it to the server's current head:
  - revision **>** head → **refused** (`BackupVersionError`): restoring a newer backup into
    older code would be a downgrade and risk data loss.
  - revision **≤** head, or **absent** (backups predating this field) → restored into the
    current schema; columns added since the backup take their model defaults.

The live schema is always at head before any restore (startup runs the spine first), so there
is **no** automatic replay of intervening migrations onto restored rows — a backfill an old
backup would need is a deliberate future step, never silent. This turns "restore across
versions" from a silent failure into a checked, tested path.

## Not in scope: solo → multi-user data ownership

There is a *separate* way user data can be stranded — switching off solo mode orphans the
solo user's data, because its password is generated and never disclosed. That is a
**data-ownership** concern, not schema migration, and it is **deferred** (it would only matter
to a single-user instance that later goes multi-user — concept drift for now). It is recorded
under "Deferred" in [ROADMAP.md](../ROADMAP.md); do not build it into the spine.

## Phased implementation

1. **Ledger + runner + baseline** — `schema_migrations`, `0001_baseline`, wired into
   `init_db()`. ✅ **Done** (`loobric_server/migrations/`, `tests/integration/test_migrations.py`):
   fresh / legacy / managed boot, idempotent re-run, failure-aborts-without-recording with
   idempotent retry, checksum drift, and the safety-backup hook.
2. **Backup revision + restore drift handling.** ✅ **Done** (`loobric_server/backup.py`,
   `tests/unit/test_backup.py`): export stamps `schema_revision`; restore refuses a
   newer-than-head backup and accepts equal / older / absent.

The spine is complete. Future schema changes are added as new
`loobric_server/migrations/NNNN_name.py` units, each with an idempotent `upgrade(conn)`.
