# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Schema migration spine.

A small, forward-only migration runner — no Alembic. It exists because
`create_all` creates missing *tables* but never alters existing ones, so an
upgrade that changes a table silently breaks a populated database. See
`docs/MIGRATIONS.md` for the full design.

Migrations live next to this module as `NNNN_name.py` files, each exposing
`revision`, `name`, and an idempotent `upgrade(conn)`. The applied set is
recorded in the `schema_migrations` ledger table, whose `MAX(revision)` is the
database's current schema version.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import text

LEDGER_TABLE = "schema_migrations"
_MIGRATION_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.py$")


class MigrationError(RuntimeError):
    """A migration could not be applied (or the migration set is invalid);
    the caller must abort startup rather than serve a half-migrated database."""


@dataclass(frozen=True)
class Migration:
    """One migration unit. `upgrade` receives a live, transactional connection."""

    revision: str
    name: str
    upgrade: Callable[[object], None]
    checksum: str
    baseline: bool = False


@dataclass
class MigrationResult:
    head: Optional[str]
    applied: list = field(default_factory=list)
    stamped: list = field(default_factory=list)


def discover_migrations(directory: Optional[Path] = None) -> list[Migration]:
    """Load every `NNNN_name.py` migration file from `directory` (this package
    by default), sorted by revision."""
    directory = directory or Path(__file__).parent
    found: list[Migration] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.py")):
        match = _MIGRATION_FILE.match(path.name)
        if not match:
            continue
        revision, name = match.group(1), match.group(2)
        module = _load_module(path, revision)
        upgrade = getattr(module, "upgrade", None)
        if not callable(upgrade):
            raise MigrationError(f"{path.name}: missing an upgrade(conn) function")
        found.append(
            Migration(
                revision=getattr(module, "revision", revision),
                name=getattr(module, "name", name),
                upgrade=upgrade,
                checksum=_checksum(path),
                baseline=bool(getattr(module, "baseline", False)),
            )
        )
    return found


def current_head(migrations: Optional[list] = None) -> Optional[str]:
    """The latest defined revision (the schema version this code targets), or
    None if no migrations are defined."""
    migs = migrations if migrations is not None else discover_migrations()
    return max((m.revision for m in migs), default=None)


def run_migrations(
    engine,
    *,
    fresh: bool,
    migrations: Optional[list] = None,
    backup_fn: Optional[Callable[[], None]] = None,
    now: Optional[str] = None,
) -> MigrationResult:
    """Bring `engine`'s database up to head.

    `fresh` must be True only when the database had no application tables before
    this startup (so `create_all` just built it at head and migrations only need
    to be *stamped*, not run). On a legacy populated database (no ledger) the
    baseline is stamped and every later migration is applied; because migrations
    are idempotent, applying an effect already present is safe. On a
    ledger-managed database, pending migrations are applied normally.
    """
    migs = sorted(
        migrations if migrations is not None else discover_migrations(),
        key=lambda m: m.revision,
    )
    head = migs[-1].revision if migs else None
    now = now or datetime.now(timezone.utc).isoformat()

    with engine.begin() as conn:
        _ensure_ledger(conn)
        applied = _applied(conn)

    # A migration must never change after it has run, or two databases that
    # "applied 0002" would actually be in different states.
    for migration in migs:
        if migration.revision in applied and applied[migration.revision] != migration.checksum:
            raise MigrationError(
                f"migration {migration.revision} ({migration.name}) was edited after it "
                f"was applied (recorded {applied[migration.revision]}, file "
                f"{migration.checksum}); migrations are immutable once applied"
            )

    pending = [m for m in migs if m.revision not in applied]
    if not pending:
        return MigrationResult(head=head)

    if not applied and fresh:
        # Greenfield: create_all already built the head schema; just record it.
        to_stamp, to_apply = pending, []
    else:
        to_stamp = [m for m in pending if m.baseline]
        to_apply = [m for m in pending if not m.baseline]

    # Safety backup before the first schema-mutating migration of the batch.
    if to_apply and backup_fn is not None:
        backup_fn()

    if to_stamp:
        with engine.begin() as conn:
            for migration in to_stamp:
                _record(conn, migration, now)

    # Each migration runs in its own transaction and is recorded only on
    # success, so a failure aborts startup and the migration is retried next
    # boot. Note: on SQLite the driver auto-commits before DDL, so a CREATE/
    # ALTER is NOT rolled back on failure — which is exactly why migrations
    # must be idempotent (guard every change). The retry then recovers cleanly.
    for migration in to_apply:
        try:
            with engine.begin() as conn:
                migration.upgrade(conn)
                _record(conn, migration, now)
        except Exception as exc:  # noqa: BLE001 - surfaced as MigrationError, aborts startup
            raise MigrationError(
                f"migration {migration.revision} ({migration.name}) failed and was "
                f"rolled back: {exc}"
            ) from exc

    return MigrationResult(
        head=head,
        applied=[m.revision for m in to_apply],
        stamped=[m.revision for m in to_stamp],
    )


def safety_backup(engine) -> Optional[str]:
    """Best-effort pre-migration backup. For SQLite, copy the database file
    alongside itself with a UTC timestamp and return the path. For other
    backends (and `:memory:`) this is a no-op returning None — back those up
    with the backend's own tooling."""
    url = engine.url
    if url.get_backend_name() != "sqlite":
        return None
    db_path = url.database
    if not db_path or db_path == ":memory:":
        return None
    source = Path(db_path)
    if not source.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = source.with_name(f"{source.name}.pre-migration-{stamp}.bak")
    shutil.copy2(source, dest)
    return str(dest)


def _load_module(path: Path, revision: str):
    spec = importlib.util.spec_from_file_location(f"loobric_server_migration_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _ensure_ledger(conn) -> None:
    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} ("
            " revision TEXT PRIMARY KEY,"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL,"
            " checksum TEXT NOT NULL)"
        )
    )


def _applied(conn) -> dict:
    rows = conn.execute(text(f"SELECT revision, checksum FROM {LEDGER_TABLE}")).fetchall()
    return {row[0]: row[1] for row in rows}


def _record(conn, migration: Migration, now: str) -> None:
    conn.execute(
        text(
            f"INSERT INTO {LEDGER_TABLE} (revision, name, applied_at, checksum)"
            " VALUES (:revision, :name, :applied_at, :checksum)"
        ),
        {
            "revision": migration.revision,
            "name": migration.name,
            "applied_at": now,
            "checksum": migration.checksum,
        },
    )
