# Changelog

All notable changes to **loobric-server** are recorded here. This project adheres to
[Semantic Versioning](https://semver.org/). Dates are ISO-8601.

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
