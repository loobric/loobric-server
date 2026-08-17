# Batch sync for records (grilled 2026-08-17; SHIPPED in server 0.15.0)

> Status: design grilled and decisions locked 2026-08-17 (see §5);
> implemented the same day in **0.15.0** (additive; one deliberate
> behavior change to the single-record assert doors, §2.4). Measured:
> the motivating 327-tool import went from ~11 min (per-record doors,
> 8 parallel workers) to **~4 s / 3 requests** through the door.
> Client verbs: loobric-cli `sync_tool_records()` /
> `sync_catalog_records()` (transparent chunking); loobric-fusion
> imports batch-first with a 404/AttributeError per-record fallback.

## 1. Why

UBIQUITOUS_LANGUAGE already states the doctrine: *"The API is bulk-first
because sync workloads are batch-shaped."* After the v2 reboot only the
machine side got it — `POST /tool-table-entry-records/sync` takes a whole
tool table in one request. The instance/catalog facades were rebuilt
minimally: every door is single-record.

The cost is structural, not tuning. The first real CAM library import
(loobric-fusion, Amana master library, 327 tools) degenerates into
**~2,600 HTTPS requests**: per tool, 1 create + ~7 asserts + preset
housekeeping. Measured against the sandbox, 2026-08-17: serial with a
fresh TLS connection per request ≈ **12 s/tool** (~65 min projected);
after client-side keep-alive, an index prefetch replacing per-tool GETs,
and **8 parallel workers**, the same import still took **~11 minutes**
(~300 ms per write, aggregate). The parallelism bought almost nothing —
the server serializes every write through SQLite's single writer.
Client-side optimization is exhausted; per-request write transactions
are the floor. A batch door turns N row writes into one transaction,
which is precisely the shape SQLite is fast at. A manufacturer-catalog
import at the IMPORTERS_PLAN scale (thousands of drafts) is tens of
thousands of requests. No transport optimization changes the request
*count* — only a batch door does.

## 2. The design

One purpose-built door per record type, mirroring the entries precedent —
no generic batching middleware.

### 2.1 `POST /tool-instance-records/sync`

```jsonc
{
  "client": "fusion360",
  "client_version": "0.2.0",
  "actor": "fusion360",              // optional; defaults to `client`
  "items": [
    {
      "client_item_id": "f93aeaa8-…",  // upsert identity (required unless id given)
      "id": "<internal.id>",           // optional; targets a record directly,
                                       // takes precedence over client_item_id
      "data": { "tool": { /* native payload */ } },
      "asserts": [                     // optional canonical facts
        {"path": "name", "value": "mysterybit"},
        {"path": "geometry.diameter", "value": 5, "unit": "mm"},
        {"path": "geometry.shape", "value": "ballend"}
      ],
      "presets": [                     // optional cutting-data contributions
        {"origin": "fusion360", "label": "Default preset",
         "material": {"name": "all"},
         "vc": {"value": 78.54, "unit": "m/min"},
         "fz": {"value": 0.05, "unit": "mm"},
         "extras": {"tool_coolant": "flood"}}
      ]
    }
  ]
}
```

Response — per-item tuples **in request order** (lean by default; a
client wanting a post-sync cache passes `?include=records` to have each
item echo the full record):

```jsonc
{
  "items": [
    {"client_item_id": "f93aeaa8-…", "id": "<internal.id>",
     "result": "created" | "updated" | "unchanged" | "error",
     "asserts_applied": 3, "asserts_blocked": 0,
     "presets_contributed": 1, "presets_skipped": 0,
     "error": "…"}                     // only when result == "error"
  ]
}
```

An empty `items` list is a 200 no-op.

### 2.2 Identity & upsert

- Match order: explicit `id`, else `(client, client_item_id)`.
  `client_item_id` has **no uniqueness constraint** (it lives inside the
  JSON section), so an ambiguous match — more than one record carrying
  the same item id for this client — is a per-item error
  (`"ambiguous_item_id"`), no write, batch proceeds. Clients holding a
  state file should send `id` and never hit this.
- No match → **create**, seeding the client section (exactly what the
  create door does today).
- Match with `data` JSON-equal to the stored section → **`unchanged`**:
  no write, no version bump, no audit row. Comparison is JSON-equality
  of `data` alone; `client_version` and section metadata refresh in
  place without counting as a change. The server answers unchanged
  authoritatively — clients delete their local diffing.
- **Merge-only. There is deliberately no `snapshot` mode.** The entries
  door reconciles a *machine's table projection* — absence from the
  table is evidence. An instance record is an owned durable record;
  absence from one library file (one client, one file of possibly many)
  is not evidence of retirement, and deletes are human acts. A client
  that wants to mirror deletions routes proposals to the Inbox, as ever.

### 2.3 Lane discipline (the composite-door rule)

This endpoint **composes** the existing doors; it does not blur them:

- An item's `data` writes only the client's own section and **must never
  influence canonical**. Only the explicit `asserts` list touches
  canonical, and it **must execute the assert door's actual code path**
  (shared helper, not a reimplementation) so every guard rides along:
  `usage.*` refused, `presets.*` refused, `status` vocabulary 400,
  `catalog_type_id` mirrored to its side column. A guard failure is a
  per-item/per-assert outcome with the same detail message the
  single-record door gives.
- `presets` entries execute the contribution door's path: the floor
  (material + one engineering value), replace-own on `(origin, label)`,
  union rematerialization. Below-floor entries count in
  `presets_skipped`; they are not errors. The delete door is not
  composed — pruning stays a per-record (and for humans, Web-UI) act.
- **Scopes compose per lane**: the door requires `sync`; items carrying
  `asserts` or `presets` additionally exercise `assert`. A key holding
  only `sync` gets `asserts_blocked` / `presets_skipped` counts, never a
  rejected batch. (The `cam` and `agent` presets hold both.)
- **Actor** comes from the request body (`actor`, default `client`) and
  is stamped `asserted:<actor>` exactly as the single doors do. It must
  never fall back to the authenticated account's email — see issue #48
  for the failure mode this guards against.

### 2.4 Same-value asserts (ratified rule, both doors)

An assert whose `value`, `unit`, **and actor** all match the stored leaf
is a **no-op**: no source overwrite, no version bump, no audit row —
re-syncing an unchanged library is idempotent end to end. An assert of
the same value by a **different** actor still applies in full:
corroboration is a provenance claim and stays recorded, as today.

The **single-record assert door adopts the same rule in 0.15.0** (today
it unconditionally overwrites source and bumps version). This is the one
deliberate behavior change in the release; changelog it as such.

### 2.5 Failure model & transaction

Two failure classes, cleanly split:

- **Validation failures** (unknown path, ratified-vocabulary 400,
  ambiguous item id, malformed item) are detected before writing →
  per-item `error` result, batch proceeds.
- **DB-level failures** (integrity, disk) → whole-batch 500 and
  rollback. Because the upsert is idempotent, a blind client retry is
  safe.

One DB transaction per batch. **Item cap: 200** (413 with the cap in the
detail; clients chunk) — small enough to keep SQLite's write lock from
starving a concurrently syncing machine, large enough that per-item cost
is sub-millisecond. Body size at this cap (~1–3 MB) is far below proxy
limits.

### 2.6 Audit

Mirrors the entries precedent (`SYNC_TABLE`): one batch-level
**`SYNC_BATCH`** row (client, actor, counts) plus the per-entity rows
exactly as today — `CREATE`/`SYNC` per record, `ASSERT` per *changed*
field, the contribution rows for presets. Per-field provenance history
survives; the batch row gives the operator the at-a-glance event.

### 2.7 `POST /tool-catalog-records/sync`

Same envelope. Differences:

- Identity is the **natural key** (manufacturer + product_code, the
  existing floor); `client_item_id` is accepted and stored as the
  re-adoption fallback. Items below the identity floor → per-item error.
- Natural-key match → **`exists`**: no create, no canonical writes, but
  the client's **own section still syncs** — your lane is always yours
  to write, and a re-import of a newer vendor file keeps the preserved
  raw payload current. (This deliberately upgrades the importers'
  409-skip-everything rule: the skip protected canonical and other
  clients' sections, which `exists` still does.)
- `actor` matters most here: importers stamp the manufacturer
  (`asserted:kennametal`), not the client name.
- Collapses `loobric import`'s create + sync per draft; the DIN 4000 /
  GTC / P21 importers get the speedup with no format-side changes.

### 2.8 Non-goals

- **Bulk delete / snapshot reconcile.** Deletes are human acts.
- **Batching observes.** Machine-side flows have the entries door.
- **Generic batching middleware.** One purpose-built door per record
  type, like entries.

### 2.9 Coverage map (why these two doors complete the batch story)

| Surface | Batch story |
|---|---|
| ToolInstanceRecords | **this design** (§2.1) — CAM library sync |
| ToolCatalogRecords | **this design** (§2.7) — importers |
| Asserts / preset contributions | ride batch items (§2.3) |
| ToolTableEntryRecords | already batch (`/sync`, the precedent) |
| ToolSet / Catalog members | already batch — replace-only membership doors take the whole membership in one request |
| Labels | already batch (`create_labels(count)`) |
| Machine records | inherently low-count; per-record is fine |
| Media blobs | per-blob by design — bytes dominate, batching the envelope saves nothing; revisit only on evidence |
| Deletes | human acts; never batched |

## 3. Expected effect

327-tool Amana import: ~2,600 requests → **2–3 chunked requests**, one
transaction each. Client code shrinks too: loobric-fusion's re-adoption
scan, unchanged-diff, per-field assert loop, and per-record preset
promotion all collapse into payload construction. Clients
feature-detect by probing the door (404 → per-record fallback — the
same dance presetsync does for pre-0.13 servers).

## 4. Vocabulary

"The sync door" (per-record section PUT) and this endpoint share the
word. Ratified naming: this is the **batch sync door**, a composite
door. UBIQUITOUS_LANGUAGE needs the row before anything user-facing
ships (the vocabulary gate applies to CLI verbs and Web UI labels that
surface it).

## 5. Grill record (2026-08-17)

Attacks sustained → amendments: composite-door rule with shared assert
code path (§2.3); ambiguous `client_item_id` handling + per-item `id`
(§2.2); same-value no-op narrowed to same-actor and adopted on both
doors (§2.4); top-level `actor` with the issue-#48 guard (§2.3);
validation-vs-DB failure split and cap lowered 500→200 (§2.5); audit
follows the `SYNC_TABLE` precedent (§2.6).

Decisions taken by sliptonic: same-actor no-op **on both doors**;
**presets ride batch items in v1** (the reserve-for-later option was
declined — a material-bearing library import must not become the next
slow path); response is **tuples with `?include=records`**; catalog
`exists` **syncs the client's own section**.

Attacks that failed (recorded so they aren't re-litigated): change-feed
flooding (consumers are batch-shaped); Cloudflare body limits (fine at
cap 200); merge-only/no-snapshot (absence from a file is not evidence;
the entries door's `force` guard exists because snapshot is dangerous
even where absence *is* evidence).
