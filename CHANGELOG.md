# Changelog

All notable changes to **loobric-server** are recorded here. This project adheres to
[Semantic Versioning](https://semver.org/). Dates are ISO-8601.

## [0.9.1] — 2026-08-05

### Changed
- **Web UI reorganized for consistency.** Every entity is now a list → detail
  pair with the same chrome: Tools splits into a slim list and a detail page
  carrying all actions (rename, labels, retire, delete); a scanned label's
  deep link opens the detail directly. **Labels** is a top-level tab (blank
  inventory + on-tool labels + printing); **Audit** moved off the nav into
  the account page's admin section (with the account roster — the Users tab
  is gone); **Account** is the email top right, no longer a tab; the account
  page gained a proper red-bordered **danger zone** (delete all tool data /
  one-step reset-to-demo).
- **One-press printing.** Picking a stock and pressing Print mints a full
  sheet immediately; only the new "Custom count…" choice prompts. The picked
  stock also applies to per-label reprints (previously hardwired to Avery).

### Added
- **Public-view preview**: `/t/<code>?view=public` shows the owner exactly
  what anyone else's scan shows — byte-identical to the anonymous rendering
  (tested), a no-op for everyone else. The Labels tab and tool detail link
  both views per label.
- **`thermal-4x6` sheet stock**: 4″×6″ adhesive shipping labels (thermal)
  as a 12-up cut-apart grid (2 × 6 of 2″×1″) with faint cut guides.

## [0.9.0] — 2026-08-04

### Added
- **Labels: physical QR/short-code stickers → digital records**
  (docs/LABELS.md). New `labels` entity (migration 0004): 8-char Crockford
  base32 codes, entity-generic and many-per-record, blank until a record is
  **labeled** (new verb; rides the bind door — only the generating account
  can use a code). `POST /api/v1/labels` mints them; `POST
  /tool-instance-records/{id}/label` / `/unlabel` attach and detach.
- **The resolver: `GET /t/{code}`** — the permanent printed-URL surface,
  outside `/api` and the OpenAPI contract. Anonymous scan of a labeled tool
  gets the **public spec page** (catalog identity, geometry, derived usage
  total — the "physical inspection" rule: never the owner, machines, or
  history; security assumptions #16–19). The owner gets an actionable view;
  a blank label scanned by its owner offers pick-or-create **scan-and-label**
  (`POST /t/{code}/label`). Base URL is per-instance (`PUBLIC_BASE_URL`,
  else request-derived) — self-hosting first-class.
- **PDF label sheets**: `POST /api/v1/labels/sheet` renders real sticker
  stock (`avery-5160` 30-up, `thermal-57x32` roll) with vector QR + grouped
  human-readable code; `{"count": N}` mints-and-prints a blank batch,
  `start_at` resumes a partially-used sheet. New deps: segno, reportlab.
- **Usage ledger (TOOL_SCHEMA.md §7.8, now implemented; migration 0005).**
  `usage_hours` is observable on entries (observe door and `/sync`);
  positive deltas against the previous reading are credited to the entry's
  confirmed, interval-stable bound instance; resets re-baseline; ambiguous
  hours are **orphaned** and surfaced read-only in the instance inbox
  (`usage_orphans`), never guessed. The instance's lifetime total
  `usage.hours` is **`derived:usage-ledger`** — asserting or observing it
  is a 400 — and decomposes at `GET /tool-instance-records/{id}/usage`
  (per-machine contributions; `GET /tool-table-entry-records/{id}/usage`
  for an entry's rows). The public spec page shows the derived total —
  publish the sum, never the ledger.

## [0.8.0] — 2026-08-01

### Added
- **Key scope introspection: `GET /api/v1/auth/key`**
  ([#44](https://github.com/loobric/loobric-server/issues/44)). A client can
  now learn AT ACTIVATION TIME what its credential may do, instead of
  learning from a 403 after a write already diverged. Returns the key's
  audit identity (`channel` + `api_key_id`, exactly as audit rows record
  it), its name, its **effective** door scopes (a legacy key reports
  `["read"]` with `legacy: true` — the 0.6.0 degradation made explicit), and
  an explicit `read_only` flag. Requires no scope beyond "the credential is
  valid"; a session or solo caller gets its channel and **no scopes field**
  (unscoped ≠ empty). Unblocks loobric-freecad's asset-store read-only-key
  policy (writes fail fast at the edit + RO badge) and gives `loobric
  status` and the MCP server a real answer instead of 403 archaeology.

## [0.7.1] — 2026-07-30

### Added
- **Revoked API keys can be deleted.** `DELETE /auth/keys/{id}?purge=true`
  permanently removes a key row — refused with 409 while the key is still
  active (revoke first: two deliberate steps, so a working credential can
  never go straight to gone). Session/solo only, like all key management.
  The web UI's key list shows **Delete** on revoked keys (Revoke stays on
  active ones). Audit rows keep the key's id string; history survives the
  row.

### Fixed
- **A controller key can self-register its machine again** (SCOPES_PLAN
  amendment 2026-07-30). The controller preset (`read sync observe`) 403'd on
  FIRST CONTACT: loobric-linuxcnc's first run creates the MachineRecord and
  asserts its name/controller_type, and both endpoints demanded `assert`.
  `POST /machine-records` and `POST /machine-records/{id}/assert` now accept
  **`observe` OR `assert`** (new `door_any`, machine-records only — an
  observe key still cannot assert tool data anywhere else; values stay
  stamped `asserted:<actor>`, scope ≠ provenance).
- **The web UI no longer goes stale in the browser after a deploy.** `/ui/`
  HTML was served with only `Last-Modified`, so browsers applied heuristic
  freshness and kept showing an old page for days — e.g. the pre-0.6.0 key
  dialog (default scopes "read write") against a server that now rejects
  non-door scopes. HTML responses now carry `Cache-Control: no-cache`:
  browsers revalidate every load (a cheap 304) and pick up a redeploy on the
  next plain refresh — no hard-refresh folklore required.

## [0.7.0] — 2026-07-29 (BREAKING: setups replace the set↔machine link)

Design: `MAPPING_PLAN.md` (grilled & locked 2026-07-29). Pairs with
loobric-cli 1.4.0; loobric-freecad and loobric-linuxcnc ship matching updates.

### Added
- **Setups (`machine_set_maps`)** — the transitory machine↔set relationship: a
  bare association row (machine, set, active/ended, attribution; ONE active
  per machine, enforced by a partial unique index; ended rows are permanent
  history). `POST /api/v1/machine-set-maps` activates (`use-set`, atomically
  ending the prior setup), `POST …/{id}/end` ends, `GET …` lists/filters.
  Lifecycle rides the **bind** door — agent keys (`read sync assert`) and bare
  controller keys (`read sync observe`) can never switch setups. Activation
  changes NOTHING on either side. ACTIVATE/END are audited.
- **The setup view** — `GET /api/v1/machine-set-maps/status?machine_id=…`:
  derived at read time, stored nowhere. Headline `ready` (every claim
  satisfied: mounted + claimed number + confirmed identity); per-claim states
  `satisfied` / `requested` / `mismounted` / `blocked` (the wrong-tool-cuts
  case, occupant named) / `pending bind`; unclaimed table rows as **notes**
  (`unlisted` / `unknown tool`) — informational only, never counted against
  readiness. The server is **never an interlock**.
- **Durable claims (§5.1).** A set member's `number` is CAM's durable claim:
  only ever changed by an assert. Reads carry the machine's `observed` number
  and derived `state` ALONGSIDE the claim, never over it. The members door
  merges: an omitted number keeps the stored claim (ends the round-trip that
  laundered claims into observations).
- **The CAM-first proposal bridge.** The 0.95 number-match proposal now also
  fires when the claim arrives AFTER the entry exists (member assert or setup
  activation), not only on the machine push.
- Migration `0003_machine_set_maps`: existing `machine_id` links become setup
  rows — per machine, the most recently updated linked set is `active`, the
  rest are preserved as `ended` history; stored canonical loses `machine_id`;
  the column is dropped.
- Web UI: the Machines tab gains the setup band (READY/NOT READY, unmet
  claims, notes, a use-set picker); Tool Sets show active-setup status and
  per-member states; **Create tool set** claims the mounted numbers and
  activates the setup.

### Removed (BREAKING)
- `tool_set_records.machine_id` (column, canonical field, and the
  `machine_id` assert path — now a 400). Linking is `use-set`.
- `POST /tool-set-records/{id}/refresh` — it persisted observed numbers into
  stored claims, the server-side half of the laundering §5.1 forbids. Reads
  always derive; there is nothing to refresh.
- The `loaded` member state (→ `satisfied`) and the `number_collision`
  ambiguity (→ the member-level `blocked` state).

### Added (unrelated, same release)
- **Canonical machine capability fields** (`MachineCanonical`): `spindle`
  (`max_rpm`, `min_rpm`, `power`, `taper`) and `coolant` (`flood`, `mist`,
  `through_spindle`) — provenance-tagged Fields set through the existing
  assert door (`spindle.max_rpm` etc.). The canonical answer to "what RPM
  can this machine turn?", born from agent sessions inferring spindle specs
  by tool-list archaeology. Vocabulary is ratified, not accreted: an assert
  to an unknown capability path is a 400 (`extra="forbid"`). Additive — no
  migration; existing machine records validate unchanged.
  (TOOL_SCHEMA.md §7.5, UBIQUITOUS_LANGUAGE.md **Machine**.)

## [0.6.1] — 2026-07-27

### Added
- **`docs/SECURITY_ASSUMPTIONS.md`** — every security assumption mapped to
  the test that proves it, with the standing rule that a new assumption
  lands with its row and its test in the same commit; plus the ranked
  not-yet-covered list (rate limiting doesn't exist; CSRF untested) and the
  condensed post-mortem of how unenforced scopes shipped.
- **Security tests that were missing from 0.6.0's own suite**: the bind
  door (agent key 403s on bind/unbind/Inbox confirm/reject), negative sync
  (read-only key cannot write client sections), the admin door (a
  full-preset key cannot reach reset/wipe/backup), and — first ever —
  **cross-account isolation over HTTP**: a second user, via session and via
  a fully-scoped key, gets 404s and empty listings for another account's
  records across all five entities. All passed on first run: the code was
  correct but unproven.

## [0.6.0] — 2026-07-27

### ⚠️ BREAKING: API key scopes are now enforced — legacy keys become READ-ONLY

Scopes existed since v1 but **no v2 endpoint ever checked them** (proven by
probe: a `["read"]` key could write). 0.6.0 makes scopes real, aligned with
the doors (SCOPES_PLAN.md, grilled 2026-07-27):

- **The seven scopes ARE the doors**: `read`, `sync`, `observe`, `assert`,
  `bind`, `delete`, `admin`. Every public endpoint checks the calling key.
  The canonical **AI-agent key is `read sync assert`** — an agent's
  credential physically cannot observe, bind, or delete, even through a raw
  client that bypasses the MCP surface.
- **Legacy keys** (any pre-0.6.0 scope list, e.g. `["read","write"]`)
  **degrade to read-only**. Their writes 403 with: *"This API key predates
  door scopes and is now read-only. Create a new key with the scopes you
  need."* This is deliberate — the old strings were never enforced, and
  grandfathering them would perpetuate unscoped credentials. **Rotate your
  keys after upgrading** (LinuxCNC push keys, MCP keys, importer keys).
- **Creating a key now requires explicit door scopes** (400 otherwise). The
  Web UI gains preset buttons (AI agent / Controller / CAM client / Full)
  and badges legacy keys "legacy · read-only".
- **Keys cannot manage keys**: key creation/revocation and password change
  now require a session (or solo mode) — a key can never create itself a
  stronger key.
- **Composite rule**: the `qa` payload on create-instance writes
  `observed:manufacturer@…`, so it additionally requires the `observe`
  scope — an assert-only key can no longer smuggle measured values through
  a create.
- **Tool-table-entry create/push requires `observe`** — entries are the
  machine's side of the contract; an agent key cannot fabricate machine
  state.
- **Sessions and solo mode are unscoped** — a signed-in human may use every
  door; admin surface still requires the admin role (keys additionally need
  the `admin` scope).

### Added
- **Audit rows record the acting credential**: new `channel`
  (`session` / `api-key` / `solo`) and `api_key_id` columns (migration
  0002). The declared actor is client-supplied; these are server truth — a
  spoofed actor string is now detectable with one query.
- **`GET /auth/me` returns the calling key's effective scopes** (API-key
  auth only), so a client — e.g. `loobric-mcp` — can introspect its own
  credential and warn when over-scoped.
- Glossary: **Scope (API key)** entry; `docs/AUTHENTICATION.md` rewritten
  for the door model (the old `action:entity`/wildcard/tag text described a
  system that never ran on v2).

## [0.5.1] — 2026-07-27

### Added
- **Web UI: client sections are now visible.** The catalog detail view gains
  a **Client data** section showing what each client recorded in its own
  section — importer source attributes, agent caveats ("part number
  unconfirmed"), prices, source URLs — verbatim, outside the canonical spec.
  Until now this data was stored but invisible except in the raw schema
  JSON, which mattered the moment `client_data` became the designated home
  for provenance-critical caveats (loobric-cli 1.1.1+): an agent's warning
  nobody can see protects nobody.

### Fixed
- Web UI copy still named the CLI `loobric_server` in four places (API-keys
  explainer, empty-set hint); it is `loobric`.

## [0.5.0] — 2026-07-27

### Added
- **`DELETE /api/v1/tool-catalog-records/{id}`** — catalog records get the
  delete door every other entity already had. Instances created from the
  record are **kept** — the physical tool outlives its catalog page — with
  their `catalog_type_id` link dissolved (nulled, source `unknown`),
  mirroring how deleting an instance unbinds its entries. Nothing cascades;
  the response reports `instances_unlinked`; every touched record gets its
  own audit row. This is a human door (Web UI / CLI): the MCP channel
  deliberately has no delete tools.
- **Web UI: delete catalog records.** A Delete button on each catalog card
  and on the detail view, with a confirm that states how many tools created
  from the record will be kept and unlinked.

### Fixed
- `pyproject.toml` version had been left at 0.3.6 while `version.py` said
  0.4.0 — re-aligned; both now single-source 0.5.0.
- Web UI: the empty-catalog hint named a nonexistent "loobric_server CLI"
  and claimed the surface was read-only; it now points at `loobric
  create-catalog-record` and `loobric import`.

## [0.4.0] — 2026-07-24

### Changed (behavior)
- **Registration is closed by default.** The first user still registers openly
  (and becomes admin); after that, creating accounts requires an authenticated
  admin (401 unauthenticated, 403 non-admin). Set
  `LOOBRIC_OPEN_REGISTRATION=1` to restore open self-registration — the
  deliberate posture for the public sandbox, whose deploy config sets it. A
  self-hosted server on an exposed port is now safe by default.
  (MCP_PLAN.md §5, hardening ahead of the MCP launch.)

### Added
- **Session cookie `Secure` flag.** `LOOBRIC_COOKIE_SECURE=1`/`=0` forces it
  on/off; unset means auto — Secure exactly when the request arrived over
  https. Plain-http LAN/solo logins keep working; deployments behind a TLS
  terminator set the env var (loobric-deploy does).
- **Glossary: the agent vocabulary.** `docs/UBIQUITOUS_LANGUAGE.md` gains the
  **Agent (provenance actor)** entry (`asserted:<agent>@mcp`; agents assert,
  never observe), loosens **Client** to "any program that talks to a Loobric
  Server through the Public API" (the sync invariant is now stated as a
  property of the sync door), and adds the **Loobric MCP server** product row.

## [0.3.6] — 2026-06-29

### Fixed
- **`GET /api/v1/auth/me` now returns `is_admin`.** The response omitted it, so a
  client could not tell an admin from a regular user — which left the Web UI's
  admin-only Users tab (0.3.5) hidden even for admins, and made `loobric whoami`
  print `Admin: None`. The Web UI now also falls back to `role === "admin"` when
  reading the admin signal, so it lights up correctly against any 0.3.5+ server.

## [0.3.5] — 2026-06-29

### Added
- **Admin account roster: `GET /api/v1/admin/users`.** A read-only, admin-only
  listing for operating a shared/sandbox deployment — answers "how many accounts
  exist, and who are they?" Returns `total` plus a per-account summary (email,
  role, admin/active/verified flags, API-key count, created-at), newest first. No
  secrets are exposed: never a password hash or any key material. Pairs with the
  existing `POST /api/v1/admin/wipe` factory reset.
- **Web UI (`/ui`): an admin-only Users tab.** For admins, a new tab shows the
  account count and roster (email, role, flags, key count, created), backed by
  `GET /api/v1/admin/users`. Hidden for non-admins (and the server gates the data
  regardless).

## [0.3.4] — 2026-06-27

### Added
- **Web UI (`/ui`): sign out and self-service registration.** A **Sign out** button
  in the header ends the session (`POST /auth/logout`). The login screen now toggles
  between **Sign in** and **Create account**, so a new user can register from the
  browser (register → auto sign-in) instead of needing the CLI.

## [0.3.3] — 2026-06-27

### Added
- **Web UI (`/ui`): an Account tab.** Create and revoke API keys (the new key's
  plain value is shown once, for copying) and change your password — all over the
  existing `/auth/keys` and `/auth/change-password` endpoints, authenticated by the
  page's session. The signed-in email now also shows in the header. No new
  endpoints; the page is still one dependency-free static file.

## [0.3.2] — 2026-06-27

### Added
- **`POST /api/v1/admin/wipe`** — admin factory reset. Deletes ALL data, ALL
  accounts, and ALL API keys, **including the calling admin**. Admin-only and
  guarded by an exact confirmation phrase (`"WIPE ALL DATA AND ACCOUNTS"`); 400
  without it. Empties every ORM-mapped table in reverse-FK order and clears the
  in-memory sessions; the schema and migration ledger survive. Afterwards the
  database is empty and the next registration becomes the new admin. Distinct
  from `/account/reset`, which wipes only the caller's tool data.

## [0.3.1] — 2026-06-27

### Fixed
- **`GET /api/v1/auth/me` now accepts API-key (Bearer) auth**, not just a session
  cookie. It previously read only the cookie, so an API-key client got a 401 here
  even though every data endpoint accepted the same key — which broke the
  API-key-first flow (`loobric whoami`) and, in solo mode, made `/auth/me` the one
  endpoint that 401'd. It now uses the same `get_authenticated_user` dependency as
  the rest of the API (session / Bearer / solo).

### Changed
- Bumped `loobric_server.version.__version__` to match `pyproject` (it had been pinned at
  `0.2.0`), so the `/version` endpoint again reports the running build and a
  redeploy is verifiable.

## [0.3.0] — 2026-06-23

The **request-to-load** release: the cross-client sync loop now closes end to
end. Adding a tool to a machine-bound tool set becomes a request a controller
surfaces and the operator fulfils by mounting.

### Added
- **Requested-member tool-set workflow.** Each member of a machine-bound set is
  classified — at read time — as `loaded`, `requested`, or `pending bind`;
  loaded members inherit the machine entry's observed tool number.
- `POST /tool-set-records/{id}/refresh` — merges a machine's state into a set's
  membership, **preserving requested members** (the machine is authoritative for
  numbers/offsets, never for membership).
- Auto-proposed binding: a newly-mounted, still-unbound tool-table entry that
  matches a requested member opens a binding proposal naming that instance.
- **Canonical media** on tool records — 3D models, drawings, and images — with a
  web UI media view and in-browser STEP rendering.
- A schema **migration spine** and self-describing backups.

### Changed
- The client was **extracted into `loobric-cli`** and removed from the server.
- The web UI "refresh from machine" now merges membership instead of replacing it.

## [0.2.0] — 2026-06-21

**M2** — author `ToolCatalogRecord`s and create physical tools from them, end to
end through the CLI and the web UI.

### Added
- **Catalog-record authoring** — `loobric create-catalog-record`: a seeded,
  atomic create. The request carries one declared `--source` actor and the
  nominal `{value, unit}` fields; the **server stamps `asserted:<actor>`** on
  each (lane discipline — the client never writes provenance). Identity floor
  (`name` + `manufacturer` + `product_code`) required; spec fields honest-sparse.
  Plus `list-catalog-records` and `show-catalog-record`.
- **Catalog → instance** — `POST /tool-catalog-records/{id}/create-instance`
  creates an **unbound** `ToolInstanceRecord` from a catalog type (`loobric
  create-record --from-catalog`). Optional **manufacturer QA** at creation
  (`--qa`/`--cert`) stamps measured geometry `observed:manufacturer@<cert>` —
  the provenance gradient (nominal `asserted` → manufacturer-QA `observed` →
  shop touch-off `observed`), reusing the existing grammar, no new kind.
- **Natural-key uniqueness** — a DB unique index on the normalized
  `(account, manufacturer, product_code)`; a duplicate returns **409** naming
  the existing record and inviting reuse.
- **Tool-set membership** — `add-to-set`, `remove-from-set`, and `show-tool-set`
  (the membership door is replace-only; the verbs do a read-modify-write).
- **Server build identity** — unauthenticated `GET /api/v1/version`
  (`{version, commit}`); `loobric whoami` now shows the server address and build,
  so "is this the server/code I expect?" is a one-line check.
- **Optional shell tab-completion** for `loobric` via `argcomplete` (the CLI
  stays stdlib-only and fully runnable without it).
- **Web UI** — browse catalog records with provenance badges; a
  create-tool-from-catalog form; a tool-set detail page listing members, with
  per-member remove.

### Changed
- **Web UI — one consistent open/inspect model**: an item's **name** opens its
  detail view, its **id** links to the raw schema JSON; the redundant per-item
  "schema" / "view" buttons were removed.
- `loobric create-record` is **context-aware** (a machine entry → **bound**; a
  catalog → **unbound**) and names the outcome.

## [0.1.0] — 2026-06-19

First tagged release. This is the **v2** server produced by the June 2026 reboot:
a single, sectioned tool-data schema with a thin public API, and `loobric.py` as
the reference client.

### Added
- **Sectioned tool schema** (`docs/TOOL_SCHEMA.md`): every entity is
  `internal` / `canonical` / `clients`, with provenance-tagged canonical fields
  (`{value, source}`, source ∈ observed/asserted/derived/unknown). Canonical data
  changes only through three doors — **sync** (a client writes its own section),
  **observe** (a machine measurement), **assert** (an explicit declaration).
- **Public vocabulary** (`docs/UBIQUITOUS_LANGUAGE.md`): `ToolInstanceRecord`,
  `ToolCatalogRecord`, `ToolTableEntry` ("entry"), `Machine`, `ToolSet`,
  `Binding`, `Inbox`, `Conflict`. Public paths under `/api/v1/*-records`.
- **Binding**: `POST /tool-table-entry-records/{id}/bind` (pass `instance_id` to
  bind an existing tool; omit it to mint a new one from the entry's observations),
  `/unbind`, and the proposal **Inbox** (`/instance-inbox`) with confirm/reject.
- **`loobric.py`** — the MIT-licensed, single-file, stdlib-only **reference Python
  client**: an importable `Client` covering all published routes plus a 29-command
  CLI (`docs/CLI.md`). Clients vendor it instead of re-rolling an HTTP client.
- **Account reset** — `POST /api/v1/account/reset` (admin) wipes the caller's tool
  data while keeping the account and API keys.
- **Web UI** (`/ui`): Machines · Tools · Tool Sets · Audit log. Binding is folded
  into the Machines tab (each unbound entry surfaces its proposal: Same tool /
  Different / Bind new).
- **Vocabulary gate** in CI: the published OpenAPI excludes the legacy deep
  routers, and the bundled web UI + CLI are scanned for both retired endpoint
  paths and retired *words*.

### Changed
- The API is now a thin facade speaking the sectioned contract models directly
  (no separate "facade vocabulary").
- Backup/export and change-detection rewritten to operate on the v2 sectioned
  records.
- License is AGPL-3.0 (core); clients are MIT.

### Removed
- The rejected concepts **Coverage**, **Reconcile**, **Adopt**, **Needs
  Attention**, **mirror**, and **slot** — along with their endpoints
  (`/coverage`, `/reconcile`, `/adopt`) and the legacy deep routers from the
  published schema. `/adopt` folded into `/bind`; "mirror" → **link**; "slot" →
  **entry**.

### Security
- `/backup/export` and `/backup/import` are now admin-gated (previously
  unauthenticated).
- API-key revocation verifies ownership (returns 404 to non-owners).

### Known issues
- Two `test_registration_security.py` tests fail due to a pre-existing
  test-isolation defect (they assume an empty DB); not a code regression.

[0.1.0]: https://github.com/loobric/loobric-server/releases/tag/v0.1.0
