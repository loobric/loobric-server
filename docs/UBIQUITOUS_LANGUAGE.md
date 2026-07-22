# Ubiquitous Language

A shared vocabulary for the Loobric / Loobric project. Use these terms consistently in code,
docs, UI, marketing, and conversation. When code and this document disagree, fix one of them —
don't let them drift.

Status: **v2 vocabulary settled 2026-06-09** (grill-me session; see `RESEARCH_BRIEF.md` §6);
**Library purged in favor of ToolSet 2026-06-11**. **Reconciled to the sectioned tool schema
2026-06-18** (reboot decision R3 = ratify the schema; see `REBOOT.md`): the public vocabulary is
now the sectioned record model defined in `TOOL_SCHEMA.md`. The old v2-flat **`ToolRecord`** facade
term is **retired** in favor of **`ToolInstanceRecord`** / **`ToolCatalogRecord`**. `TOOL_SCHEMA.md`
is the authoritative contract; if it and this document disagree, the contract models in
`loobric_server/contract/` win and this document is the bug. Terms marked ⚠️ have known ambiguity.

**Language rule — client neutrality.** Loobric is client-application agnostic. The names of
specific applications (FreeCAD, LinuxCNC, Fusion, …) never appear in the normative vocabulary,
the facade API, core docs, or core UI text. They appear only (a) when referring to that
application's own artifact or term (a `.fctl` file IS a "FreeCAD tool library"), and (b) in
explicitly client-specific sections such as the reconciliation tables below or a client's own
repository. Generic domain categories — "CAM application", "controller", "tool table" — are the
neutral vocabulary.

**Language rule — the gate (reboot 2026-06-18).** No new domain concept or user-facing word
ships without an entry in this document. A concept that appears in an endpoint path, a response
field, the OpenAPI schema, the CLI, or a client UI but not here is a bug, not a feature — it gets
reverted or it gets a glossary entry with founder sign-off, never silently kept. Phase 1 of the
reboot enforces this in CI (an OpenAPI-vocabulary contract test + a string denylist). This rule
exists because "Adopt", "Coverage", "Reconcile", and "Needs Attention" all reached the public
surface without ever passing through here.

---

## v2 Public Vocabulary (normative)

The public API exposes these concepts. Every tool-domain entity is a **sectioned record**
(`internal` / `canonical` / `clients`) with provenance-tagged canonical fields, defined in
`TOOL_SCHEMA.md`. Public paths use the `*-records` / `instance-inbox` naming the schema ratified.

| Term | Definition |
|------|------------|
| **ToolInstanceRecord** | The primary syncable resource: one *physical* tool — canonical identity/geometry/status, an optional `catalog_type_id`, and per-client sections. Binds to at most one tool-table entry at a time (install-once). Public path `/api/v1/tool-instance-records`. This is what the retired v2-flat vocabulary called "ToolRecord"; that term is **gone** (see Naming Tensions §1). In informal prose "tool" stays acceptable where unambiguous; use **ToolInstanceRecord** when precision matters. |
| **ToolCatalogRecord** | A catalog-level *type*: a reusable, shareable definition (manufacturer, product code, **nominal** geometry) that can exist with zero owned instances. A ToolInstanceRecord optionally references one via `catalog_type_id`. Public path `/api/v1/tool-catalog-records`. |
| **ToolTableEntry** | One machine's tool-table row: `tool_number` (the CAM↔CNC contract, `observed`), `bound_instance_id` (`asserted:human@inbox` once confirmed), `offsets` (`observed`) — all provenance-tagged; `internal` carries `machine_id`. Reflects a controller's tool-table / offset-table row. Public path `/api/v1/tool-table-entry-records`. (Rejected names: `MachineToolInstance`; `ToolPocket` — names a field.) |
| **Machine** | First-class entity: a CNC machine — identity, controller type, definition (axes/spindle/limits/post). Clients sync their native machine definitions to it. Public path `/api/v1/machine-records`. |
| **ToolSet** | A control/CAM-agnostic named collection of tools, with ordered, provenance-tagged member numbers. Optionally **linked** to a Machine (`machine_id`); when linked, member numbers are inherited (`observed`) from the machine's tool-table entries, otherwise `asserted`. A FreeCAD `.fctl`, a Fusion library, or a shop drawer is one client's representation of a ToolSet, living in `clients.<name>.data`. (Supersedes **Library**, purged 2026-06-11.) |
| **Preset** | A named feeds-and-speeds record on a tool record (`preset_schema: 1`): surface speed (Vc), chipload (Fz), optional vertical-feed ratio, optional material reference, operation type. Engineering values only; raw feed/RPM are derived by the consuming application at use time and never persisted. *(Facade endpoint not yet implemented — planned for M3.)* |
| **Binding** | The confirmed link between a ToolTableEntry and a ToolInstanceRecord (`bound_instance_id`). Server-proposed, user-confirmed once, sticky. What makes the sync loop close. Verb forms are part of the vocabulary: to **bind** / **unbind** an entry; an entry is **bound** or **unbound**. Unbound entries still sync — as unbound. **`bind` is the only verb for this relationship** — `adopt` and `install` are retired synonyms (see Rejected terms). |
| **loaded** (member state) | A member of a machine-linked ToolSet whose tool instance is bound to one of the machine's tool-table entries. Its `number` is **observed**, inherited from that entry's `tool_number`. Shows up as "in sync". One of the three derived member states (`loaded` / `requested` / `pending bind`), computed at read time, never stored. |
| **requested** (member state) | A member of a machine-linked ToolSet for which the machine has **no** entry yet — a load request awaiting the operator, not stale data. Its `number` is the **asserted** preference the client supplied, or **unknown**. A machine-driven refresh never deletes a requested member. Shows up as "1 tool requested". (More members than machine entries is a valid, in-sync state when the surplus are `requested` / `pending bind`.) |
| **pending bind** (member state) | A member of a machine-linked ToolSet whose requested tool has been mounted — the machine now reports an entry and an open binding proposal names the instance — but the binding isn't confirmed. The entry's **observed** `number` is surfaced; the state flips to `loaded` once the proposal is confirmed. Shows up as "1 pending bind". |
| **Pending review / Inbox** | First-class server state for items awaiting a human: proposed Bindings and frozen Conflicts. Public path `/api/v1/instance-inbox`. Sync never prompts, blocks, or guesses. |
| **Conflict** | Both sides changed the same bound field between syncs. The field freezes (neither side overwritten) until resolved in the Inbox. |
| **Sync Plan / Apply** | The preview-first sync pattern clients use for interactive sync: **plan** computes what a sync would do — every item classified (in sync, changed here, changed on server, new, deleted, conflict) — touching neither disk nor server; **apply** executes only the user's per-item direction choices. The classification is a suggested default, never a railroad; conflicts and deletions default to "leave unsynced". |
| **Account reset** | A per-account operation that deletes **all** of the caller's tool data — instance/catalog records, tool sets, machines, tool-table entries, binding proposals — while keeping the account and its API keys. Exists to return to a clean slate for testing/demos. Public path `POST /api/v1/account/reset`; **owner-gated** (any signed-in user may reset their *own* data — it is entirely user-scoped). The inverse of **Add demo data**. (Cross-account/factory wipes stay admin-gated: see `/api/v1/admin/wipe`.) |
| **Add demo data** | A per-account operation that **seeds** a fresh account with a small demo — a machine, a two-manufacturer catalog, a couple of physical tools, a tool set, and a pushed tool table — so a first-time visitor has something to explore without the CLI. Built by replaying the normal create/assert/sync doors, so every seeded field carries real provenance. Public path `POST /api/v1/account/seed-demo`; **owner-gated**. Refuses (409) on an account that already holds tool data — load it on a clean slate (**Account reset** first to reload), and it rolls back to that empty slate if any step fails. Mirrors loobric-cli's `examples/quickstart.sh`. UI label: **Add demo data**. (Not "sample data"/"seed" in user-facing prose — "demo data" is the one term.) |

### How canonical data changes — provenance and the three doors

Public, normative (full detail in `TOOL_SCHEMA.md` §4–5). Every `canonical` leaf is a
provenance-tagged field `{ value, source }`. `source` kind is one of **`observed`** (a machine
measured it), **`asserted`** (a human/client declared it), **`derived`** (computed from other
canonical fields), or **`unknown`** (nobody stated it → `value` MUST be null). Canonical changes
only through three doors: **sync** (a client writes only its own `clients.<name>` section — the
only thing most clients do; physically cannot touch `internal`/`canonical`), **observe** (a
machine reports a measured value), **assert** (an explicit, audited declaration). Routine sync is
*not* a canonical-mutating door — that is enforced with a `400`, not a convention.

### Catalog records — authoring (M2)

Normative. How a **ToolCatalogRecord** comes into being and how it is named. See
`TOOL_SCHEMA.md` §7.1 and `Archive/M2_PLAN.md` §4.1.

| Term | Definition |
|------|------------|
| **create_catalog_record** | The verb/endpoint that authors a ToolCatalogRecord in one **atomic, audited** act: `POST /api/v1/tool-catalog-records`. The request carries one declared **actor** plus the nominal fields as bare `{value, unit}` leaves; the **server stamps `asserted:<actor>`** as each field's `source` (the client never writes provenance — lane discipline). All-or-nothing: a malformed request leaves no half-built record and a success writes exactly one `CREATE` audit row. Replaces the old create-blank-then-N-asserts dance. CLI verb: `loobric create-catalog-record` (JSON on stdin/`--file` + convenience flags; required `--source` is the actor). No "mint" wording. |
| **Identity floor** | The minimum a ToolCatalogRecord needs to be **found and de-duplicated**, not the minimum to be *complete*: `name`, `manufacturer`, and `product_code` are **required and non-null** at create. Spec fields (geometry, …) are deliberately optional and **honest-sparse** — a record with no geometry is valid; fields are never fabricated to pass a gate. (The `(manufacturer, product_code)` natural key that builds on this floor is M2 §4.2, a separate change.) |
| **create-instance (catalog → instance)** | The two ways a ToolInstanceRecord is born differ by their resulting bind state. From a **machine entry** (`create-record MACHINE TOOL_NUMBER`, the entry `bind` door): the instance is **bound** to that tool-table position. From a **catalog record** (`create-record --from-catalog CATALOG`, `POST /tool-catalog-records/{id}/create-instance`): the instance is **unbound** — a catalog is a type, not a machine position — and asserts `catalog_type_id` with source `asserted:<requester>` (the link is the requester's own first-party act; the actor defaults to the requesting context). The catalog path copies the catalog name (or a `--name` override), leaves `status` **unknown**, optionally records manufacturer QA (next row; absent QA, measured geometry stays **unknown** and nominal geometry is reachable through the link), and yields a new, distinct instance on every call. No "mint" wording in the catalog path. |
| **observed:manufacturer@&lt;cert&gt; (manufacturer QA)** | The **middle rung of the provenance gradient** (`Archive/M2_PLAN.md` §3): more than the catalog's nominal `asserted:<manufacturer>` spec on the *type*, but measured by the **manufacturer's QA on the certified tool**, not the shop. Recorded on a **ToolInstanceRecord**'s measured geometry at catalog→instance creation: `create-record --from-catalog CATALOG --qa qa.json --cert <cert>` (`qa.json` is geometry-shaped — `{diameter:{value,unit}, …}`). `--cert` is **required iff `--qa`** is given; the catalog→instance endpoint is the deliberate **audited door** permitted to stamp a third-party `observed:manufacturer@*` — the routine **observe** door is unchanged and still requires a client to stamp its own identity. The client sends values + units + cert only; the **server composes the `source`** (lane discipline) as `observed:manufacturer@<serial>`, where the *who* is the generic measurer role **`manufacturer`** (the specific vendor name already lives in the type's `asserted:<manufacturer>`) and the *where/serial* is the tail of `--cert` after the last `@` (so `kennametal@SN12345` and a bare `SN12345` both yield `observed:manufacturer@SN12345`). The shop touch-off (`observed:<client>@<machine>`) is the third rung. No new provenance *kind* — this is the existing `observed:<who>@<where>` grammar (the `observed:presetter@…` precedent already blesses a non-CNC measurer). |
| **Catalog (vs ToolCatalogRecord)** ⚠️ | "Catalog" means a **set / collection** of records — a manufacturer's published line, or the future public/cross-account catalog layer. It is **not** the singular record: one published spec is a **ToolCatalogRecord** (CLI: a *catalog record*), never "a catalog". Say "catalog record" for the row and reserve "catalog" for the collection. (Manufacturer Catalog, below, is the collection sense.) |
| **Shop-as-manufacturer** | The honest convention for a tool with no vendor (a shop-ground cutter): set `manufacturer = "shop"`. The shop genuinely *is* the manufacturer of a tool it ground, so this satisfies the identity floor without fiction — no nullable-manufacturer special case, no fabricated vendor. |

### Rejected / removed terms (do not reintroduce — reboot R2)

These shipped during implementation without entering the language and were removed 2026-06-18.
They return only through this document with founder sign-off:

| Removed term | Was used for | Use instead |
|---|---|---|
| **Adopt / adopted** | minting + binding a new record from an entry | **bind** (a bind may mint the record it binds) |
| **install / installed** | the *bound* state, presented | **bound** / **unbound** |
| **Coverage** | a set-vs-machine diff view (+ `absent_on_machine`/`machine_only`/`number_mismatch`) | (removed; no replacement — re-earn via this doc if needed) |
| **Reconcile** | aligning set numbering to machine tool-table entries | (removed; the schema's number-reconciliation is surfaced through the **Inbox**) |
| **Needs Attention** | a FreeCAD tab duplicating the Inbox | **Inbox** |
| **mirror / mirrors** | the ToolSet↔Machine relation | **link / linked** (the one chosen word; provisional pending the user-facing-label pass) |
| **slot / slots** | undocumented drift for a tool-table row, and the `/sync` wire field `slots` | **ToolTableEntry** / "entry" (and **Pocket** for the magazine position); the wire field is now `entries`. Purged 2026-06-18 (REBOOT R10). |

---

## Server Surfaces

One Loobric Server server exposes three distinct surfaces. Don't say "the facade" when you mean
one of these — name the surface.

| Term | Definition |
|------|------------|
| **Public API** (`/api/v1`) | The product's actual contract: the REST endpoints speaking the public vocabulary above. The ONLY read/write path — every other surface, first-party or not, is a client of it. "Facade" is the internal architecture name for the layer that implements it; user- and developer-facing prose says **API** or **public API**. |
| **Web UI** (`/ui`) | The management UI served by core: one static file, no build step, AGPL like the rest of core. Speaks only the Public API from the browser — it is a first-party *client* with no privileged access; auth is enforced by the API it calls, not by the page. Grew out of the milestone-1 "web inbox" (G2); now tabs for Machines, Tools, Tool Sets, and Audit log (the inbox is folded into the Machines tab — proposals are confirmed/rejected inline). Distinct from **Loobric Web**, the commercial hosted application (M3 rebuild). |
| **API reference** (`/api/v1/docs`, `/api/v1/redoc`) | Interactive, auto-generated documentation of the Public API for developers (Swagger UI / ReDoc). Never hand-maintained — it is a *projection* of the API, generated from `/api/v1/openapi.json`. Publishing exactly the facade vocabulary and nothing else is a tested contract (deep routes are excluded from the schema). |
| **OpenAPI schema** (`/api/v1/openapi.json`) | The machine-readable contract artifact behind the API reference; what contract tests assert against. |

---

## Architecture Terms (internal only)

Words for talking about the system's structure — in design docs, code comments, and commit
messages. They never appear in user-facing prose, client UI, or the published API: a user sees
"the API" and "Loobric", not the layering behind them.

| Term | Definition |
|------|------------|
| **Facade** | The layer implementing the Public API. Under the 2026-06-18 reconciliation (R3) it is **thin**: the public API speaks the sectioned contract models in `loobric_server/contract/` *directly* — there is no longer a separate "facade vocabulary" translating down to a different deep one. "Facade" remains the name for the API layer (the Web UI and API reference are surfaces *on top of* it, not parts of it), and "facade gaps get fixed, never bypassed" (G3) still holds. |
| **Legacy deep schema** | The retiring v1 substrate (`ToolItem` / `ToolAssembly` / `ToolInstance` / `ToolPreset` / `ToolUsage` and their routers, mounted `include_in_schema=False`). Superseded by the sectioned records; scheduled for removal (reboot R6); no compat promise; do not build on it. The richness it modeled now lives as **composition** inside the sectioned records (`TOOL_SCHEMA.md` §7.6). |

---

## Project & Product Names

| Term | Definition |
|------|------------|
| **Loobric** | The company/organization and brand (loobric.com, GitHub org). Not the product name. |
| **Loobric** | The product: an open-core tool data synchronization system. |
| **Loobric Server** | The central REST API + database server (`loobric-server`). The thing clients talk to. Licensed AGPL-3.0 (relicensed from Elastic 2.0 on 2026-06-09, decision G6). |
| **Client** | Any program that synchronizes tool data with a Loobric Server server: `loobric-freecad`, `loobric-linuxcnc`, the `loobric.py` CLI, or third-party integrations. Clients are MIT-licensed reference implementations. |
| **Loobric Web** | The hosted web application. The v1 app (`loobric-web`, app.loobric.com) is retired; a v2 rebuild on the Public API is scoped in M3. Part of the commercial offering, not the open core. ⚠️ Boundary with the core **Web UI** (`/ui`, see Server Surfaces) is undecided: M3 scope (account/key management, audit browsing, backup/restore, admin) is currently slated for the core Web UI — decide which features are open `/ui` vs commercial Loobric Web before M3 starts. |

## Domain Concepts — Tools

> **Legacy section (historical).** The table below describes the **retiring** v1 deep entities
> (`ToolItem` / `ToolAssembly` / `ToolInstance` / `ToolPreset` / `ToolUsage`). The current model
> is the sectioned records in `TOOL_SCHEMA.md` (`ToolInstanceRecord`, `ToolCatalogRecord`,
> `ToolTableEntry`, `ToolSet`, `Machine`). Keep this only as a glossary for reading old code until
> the legacy substrate is removed (reboot R6).

The word "tool" alone is ⚠️ **overloaded** in machining. The legacy schema resolved it into
distinct entities along the catalog → physical → machine axis. Always use the specific term.

| Term | Definition |
|------|------------|
| **ToolItem** | A *catalog-level* description of a tool type: manufacturer, part number, tool type (drill, end mill, …), and geometry. Describes *what kind of thing* a tool is, not a physical object. Both cutters and holders are ToolItems. |
| **ToolAssembly** | A combination of a holder ToolItem and a cutter ToolItem, with assembly-specific data (e.g. stickout). What a CAM programmer typically thinks of as "a tool." |
| **ToolInstance** | A *physical* tool with a unique serial number, lifecycle status (AVAILABLE, IN_USE, MAINTENANCE, RETIRED), and actual measured values. Two identical end mills are one ToolItem but two ToolInstances. |
| **ToolPreset** | (Deep, historical) A machine-specific setup of a ToolInstance: the parameters a particular controller needs (tool number, pocket, offsets). This is what a controller tool-table row maps to. Publicly renamed **ToolTableEntry** in v2. |
| **ToolUsage** | A record of a ToolInstance being used: machine, program, operator, runtime metrics, wear measurements. The basis for wear tracking and analytics. |
| **ToolSet** | The collection entity (`tool_sets`). In v2 it directly backs the public **ToolSet** resource — internal and public nomenclature are identical. |
| **Geometry** | The dimensional definition of a ToolItem (diameter, length, flutes, shape). Stored as structured JSON; the part CAM systems care most about. |
| **Measurements** | *Actual* measured values on a ToolInstance (as opposed to nominal catalog geometry). E.g. presetter results. |
| **Wear / Offset** | Adjustments discovered at the machine (tool wear, length/diameter offsets). The canonical example of data that today gets stranded in the controller and never flows back to CAM. |

## Domain Concepts — Catalogs & Sharing

| Term | Definition |
|------|------------|
| **Manufacturer** | A user role for tool vendors who publish catalogs. Admin-created, optionally **verified** (partnership flag). |
| **Manufacturer Catalog** | A published, searchable collection of ToolItems owned by a manufacturer account. Users *copy* tools out of catalogs; they never edit catalog tools directly. |
| **Copy (from catalog)** | Creating a user-owned ToolItem from a catalog ToolItem. The copy is independent and editable. |
| **parent_tool_id** | The link from a copied ToolItem back to its catalog source. Enables provenance and copy-count analytics. |
| **Published** | A catalog flagged visible to the public. Unpublished catalogs are private to the manufacturer. |

## Domain Concepts — Sync

| Term | Definition |
|------|------------|
| **Sync / Synchronization** | The core verb: making tool data consistent between Loobric Server and a client system (a CAM application's tool data, a controller's tool table, etc.). |
| **Bidirectional sync** | Changes flow both ways: CAM → server → controller *and* controller → server → CAM (e.g. wear offsets entered at the machine propagate back). |
| **Tool table** | A controller's native tool data store (e.g. a `.tbl` file with T/P/D/Z parameters). A client-side format, not a Loobric concept; Loobric models its rows as ToolTableEntries. |
| **Tool number** | The ONLY tool identifier that travels in G-code (`T3 M6`): the single point of contact between CAM's assumption and the controller's reality. Both sides' number→tool mappings are recorded (CAM numbering with the ToolSet; the machine side via Binding on `(machine, tool_number)`), making their agreement a verifiable fact. Verifying this mapping is the system's most important job — see `CONCEPTS.md`. |
| **Pocket** | The magazine position a tool physically occupies — a tool-changer implementation detail, NOT identity. Some controllers map number→pocket 1:1; others assign pockets dynamically and remember where each tool went. Entries are keyed on `(machine, tool_number)`; `pocket` is an optional, mutable observed attribute, and Bindings survive pocket shuffles. |
| **Tool library** | ⚠️ Client-side term only — some CAM applications call their tool collections "libraries". Inside Loobric the word is **ToolSet**; "library" appears only when naming that application's own artifact. |
| **Change detection** | Using `version` / `updated_at` to find what changed since last sync, so clients sync deltas instead of everything. |
| **Version (optimistic locking)** | Integer incremented on every write to an entity. A write with a stale version is a **conflict**. |
| **Conflict** | A write attempted against a stale version, typically because two systems changed the same entity between syncs. |
| **Bulk operation** | API endpoints that create/update many entities in one request. The API is "bulk-first" because sync workloads are batch-shaped. |
| **Import / Export** | Moving tool data in/out of Loobric in portable formats (JSON, CSV, XML) — the no-lock-in escape hatch, distinct from live sync. |

## Roles, Tenancy & Security

| Term | Definition |
|------|------------|
| **User** | An account. Owns its tool data; all queries are isolated per account (**multi-tenant by default**). |
| **Role** | `user`, `admin`, or `manufacturer`. Governs what an account may do. |
| **API key** | User-created credential for programmatic/machine access (what a controller-side sync script uses). Distinct from email/password login. |
| **Tag-based API access** | Scoping an API key's reach by entity tags (e.g. a key for machine `mill01` only sees tools tagged for it). |
| **Audit log** | Immutable structured record of who changed what, when. Compliance/forensics, separate from operational logs. |
| **Solo mode** | Opt-in single-user deployment mode (`LOOBRIC_SOLO=1`, decision G1/D1): authentication is bypassed and every request acts as the built-in **solo user**. Exists so one person on a trusted LAN can go from `docker run` to a working sync loop with zero registration/login/API-key ceremony. Never the default; hosted and sandbox instances always run multi-user. The clients don't know or care which mode the server is in — an empty API key simply works against a solo server. |
| **Solo user** | The built-in account (`solo@localhost.loobric_server`) auto-created on first request in solo mode; it owns all data created while solo. Its password is random and never disclosed, so this data is reachable *only through solo mode* — switching a server to multi-user strands it until an admin intervenes. ⚠️ The solo → multi-user migration story is undefined; define it before promoting solo mode in quickstart docs. |
| **Multi-user mode** | The default when `LOOBRIC_SOLO` is unset: registration, login, API keys, per-account isolation. Not usually named in prose — it's just how the server works; "multi-user" appears only when contrasting with solo mode. |

## Machines & Shop Concepts

| Term | Definition |
|------|------------|
| **Machine** | A CNC machine/controller. First-class entity since v2 (see Public Vocabulary); the old free-string `machine_id` is gone. |
| **Controller** | The CNC control software/hardware (LinuxCNC, Fanuc, Haas, …) that consumes ToolPresets. |
| **CAM system** | Software that generates toolpaths (FreeCAD CAM workbench, Fusion 360, Mastercam, …) and consumes ToolItems/Assemblies/geometry. |
| **Tool room / Tool crib** | Where physical tools are stored, assembled, and measured in a shop. A target integration domain (presetters, inventory). |
| **Presetter** | Shop-floor device that measures actual tool dimensions; a future source of ToolInstance measurements. |

## Standards

| Term | Definition |
|------|------------|
| **ISO 13399** | International standard for cutting tool data representation and exchange. Loobric aims to be *aligned* with (not strictly conformant to) it. |
| **STEP-NC (ISO 14649)** | Standard for machining process data including tooling. |
| **MTConnect** | Read-only protocol for machine-tool data; relevant for usage/wear telemetry. |
| **GTC (Generic Tool Catalog)** | Industry format for distributing manufacturer tool catalogs; relevant to the Manufacturer Catalog feature. |

## Business Model

| Term | Definition |
|------|------------|
| **Open core** | Business model: Loobric Server is free and self-hostable; revenue comes from hosting, the web UI, and team/enterprise features. |
| **Self-hosted** | Running Loobric Server on your own infrastructure (free tier, full data control). |
| **Cloud-hosted** | Loobric-managed hosting (Hobbyist $15/mo, Professional $299/mo, Enterprise custom). |
| **AGPL-3.0** | loobric-server's license (relicensed from Elastic 2.0 on 2026-06-09, decision G6): OSI-approved open source; network-use copyleft prevents proprietary SaaS forks while keeping self-hosting fully free. Commercial licensing covers the hosted/enterprise offering. Clients remain MIT. |

---

## Reconciliation with FreeCAD CAM (ADR-000)

FreeCAD's CAM workbench maintains its own ubiquitous language in `src/Mod/CAM/Roadmap/ADR/ADR-000.md`,
extended by the Feeds & Speeds work (PR #30078). Loobric's first client lives there, so collisions are
resolved **in FreeCAD's favor** wherever FreeCAD's term is shipping. Proposed resolutions (see
`RESEARCH_BRIEF.md` §3.4, decision D13 — pending grill-me):

| Term | FreeCAD meaning | Loobric PoC meaning | Proposed resolution |
|------|-----------------|--------------------|---------------------|
| **Preset** | Named F&S record on a Tool Bit: surface speed (Vc), chipload (Fz), optional vert-feed ratio, optional material UUID, op type. Engineering values only; raw feed/rpm derived at use-time. | `ToolPreset` = machine-specific tool-table entry (tool number, pocket, offsets) | **RESOLVED: adopt FreeCAD's meaning.** Loobric's cutting-parameter records are "Presets" with the identical schema. Loobric's old entity renamed → **ToolTableEntry**. |
| **Tool Library** | Persisted collection of Tool Bits, independent of Jobs | ToolSet | **RESOLVED:** FreeCAD Tool Library / `.fctl` ↔ Loobric **ToolSet**. ("Library" was briefly the facade word; purged 2026-06-11 — it is FreeCAD's term, and the facade now uses the internal name.) |
| **Machine** | `.fcm` definition: axes, limits, spindle min/max, post settings | free-string `machine_id` | Loobric **Machine entity** syncs `.fcm` content. Same word, compatible meaning. |
| **Tool Bit** | The cutter: geometry, edges, parameters, F&S Presets; persisted as `.fctb` | ≈ ToolItem (type=cutting_tool) | Equivalence documented; `.fctb` round-trip **must preserve the additive `presets` key**. |
| **Provenance** | Per-field source string (`"user"`, `"preset:…"`); resolver never overwrites `"user"` | (audit log, coarser grain) | Adopt term + semantics for synced F&S fields. **Sync must never replace a `"user"`-provenance value silently.** |
| **OP_TYPES** | Controlled cutting-kind vocabulary: `profile, pocket, slot, drill, adaptive, surface_finish` | (none) | Adopt verbatim for Preset records. |
| **Tool assembly** | *Avoided* in CAM-workbench prose (confusable with Tool Controller) | Core entity (holder + cutter) | Keep `ToolAssembly` in Loobric's deep schema; never in facade/hobbyist docs. |

## Naming Tensions — status after 2026-06-09 grill

1. ~~Facade resource name~~ **RE-RESOLVED 2026-06-18 (R3):** the public resource is **`ToolInstanceRecord`** (a physical tool), with **`ToolCatalogRecord`** for catalog types — the sectioned schema (`TOOL_SCHEMA.md`) is ratified as the public vocabulary and the old flat **`ToolRecord`** term is retired. Bare "tool" remains harmlessly informal.
2. ~~Library vs ToolSet vs Catalog~~ **RE-RESOLVED 2026-06-11:** **ToolSet** = the one word, public and internal — "Library" purged from the facade as a client-side (FreeCAD) term; **Catalog** = manufacturer-published collections only.
3. **ToolInstance may point at a ToolItem *or* a ToolAssembly** — now internal-only (facade-only public API), but the schema rule is still needed for phase 2. Open.
4. ~~`machine_id` string~~ **RESOLVED:** Machine entity (D4); syncs `.fcm`. Pending implementation.
5. ~~Open source vs source-available~~ **RESOLVED:** AGPL-3.0 core + commercial, MIT clients (G6). After relicense, "open source" is accurate.
