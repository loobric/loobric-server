# Loobric v2 Research Brief

**Date:** 2026-06-09
**Status:** Reviewed and grilled 2026-06-09. All decisions **accepted** (D13 as amended). Grill resolutions in §6. Execution plan: `REIMPLEMENTATION_PLAN.md`.
**Premise:** The current implementation (loobric-server, loobric-freecad, loobric-linuxcnc) is treated as a **proof of concept**. This brief summarizes what the PoC, competitive research, and the FreeCAD Feeds & Speeds work (PR #30078 / discussion #30422) teach us, and converts those findings into explicit decisions.

**How to read this:** every section ends in a numbered **Decision** with a recommendation. The decision register at the end (§5) is the grill-me agenda. Annotate disagreements inline.

---

## 1. What the PoC taught — technical findings

### 1.1 What actually works

A code audit (June 2026) found loobric-server to be a real, working system, not vaporware:

- **Bulk-first REST API** across all six entities, with partial-success semantics, pagination, tag filtering.
- **Auth done properly**: session + API keys, tag-scoped keys (a key can be locked to entities tagged `mill01`), multi-tenant isolation by default, immutable audit log.
- **Change detection** by version *and* timestamp (`/changes/{entity}/since-version`, `/since-timestamp`).
- **ToolSet version history with rollback** (`/history`, `/restore/{version}`, `/compare`).
- **Backup/restore** (JSON, atomic, per-tenant).
- Real test suite, TDD discipline, functional style.

### 1.2 What's broken or missing — and what each failure teaches

| Finding | Evidence | Lesson for v2 |
|---|---|---|
| **The two clients form disconnected silos.** FreeCAD writes ToolItems; LinuxCNC writes ToolPresets with `instance_id: null`. Nothing links them. The founding use case — CAM↔controller sync — never closes the loop. | `loobric-linuxcnc/parse_tooltable.py`; `loobric-freecad/fctb_parser.py` | Identity resolution (binding a controller's T3 to the CAM tool) is **the product**, and it must be a *server* responsibility. Clients are too thin to do it. |
| **Both clients bypass most of the domain model.** FreeCAD uses only ToolItem (no Assembly/Instance, despite schema requiring `assembly_id` on Instance). LinuxCNC uses only ToolPreset. | same | The 4-entity surface is the wrong *contract* for clients, even if it's the right *schema*. v2 needs a collapsed facade (§1.4). |
| **FreeCAD round-trip is broken**: shape upload calls a nonexistent endpoint; `.fctl` libraries map to nothing; holder/assembly data lost. | `fctb_parser.py`, `LoobricDialog.py` | Round-trip fidelity is a correctness requirement, not a feature. Every import must export back losslessly or users can't trust the hub. |
| **Conflict handling is last-write-wins**; the LinuxCNC script silently overwrites `tool.tbl`. | `sync_tooltable.sh` | For a product whose pitch is "stop crashing spindles on stale offsets," silent clobbering is self-refuting. Divergence must be surfaced, not resolved silently. |
| **Setup friction: 12 steps, ~20 min, 7 of them server admin**, incl. an API key shown once and never again. | `docs/QUICK_START.md` | A solo hobbyist must never see "multi-tenant." Need a zero-config solo mode. |
| **No web UI at all.** Users cannot see their data without curl. | — | Even a read-only browser is a trust requirement. |
| **Claims vs code**: ISO 13399 is a string field; STEP-NC/MTConnect/CSV/XML export, rate limiting, plugin system — all docs-only. | `README.md` vs `loobric_server/api/` | v2 docs claim only what runs. Credibility with this audience is one-strike. |
| **ToolUsage/analytics are write-only** — schema exists, nothing consumes it. | `audit findings` | Don't build storage for data with no consumer. Build the consumer first or cut it. |

### 1.3 Keep / Salvage / Discard

> **Decision D1 — what "PoC" means.** *Recommendation:* PoC means **no backward-compatibility obligations**, not green-field. Concretely:

| Component | Verdict | Rationale |
|---|---|---|
| Bulk-first API design, partial-success semantics | **Keep** (pattern) | Validated; sync workloads are batch-shaped. |
| Auth: API keys, tag scoping, multi-tenancy, audit log | **Keep** (port code) | Production-grade; uninvalidated by anything learned. |
| Change detection (version + timestamp) | **Keep** | Works; needed by every client. |
| Backup/restore, ToolSet history/rollback | **Keep** | The "your data is safe and yours" story. |
| 4-entity deep schema (Item/Assembly/Instance/Preset) | **Salvage** | Right ontology, wrong contract. Keep internally; hide behind a facade (§1.4). |
| Client API contract (entities exposed raw) | **Discard** | Both reference clients refused it. |
| loobric-freecad mapping layer | **Discard/rewrite** | Broken round-trip; pre-dates FreeCAD F&S presets and Machine work. |
| loobric-linuxcnc scripts | **Salvage** | `.tbl` parser is fine; orchestration needs conflict surfacing + binding. |
| ManufacturerCatalog feature | **Park** | Right idea, wrong sequence — see D8. Manufacturers won't come to an empty platform. |
| ToolUsage entity | **Park** | No consumer yet. Reintroduce with the cutting-parameter layer (D11). |
| Marketing site pricing page | **Discard for now** | See D9. |
| loobric-web (v1 web app) | **Discard as deployed app; rebuild in M3** | *(Added 2026-06-10 — this row was missing; the repo wasn't in the workspace.)* Full deep-API consumer: its writes create pre-facade data (dead-model ToolPresets, name-less ToolItems) that poisons v2. Retired and archived; app.loobric.com removed. Its account/key/backup/admin functionality becomes M3 Loobric Web scope (see loobric-server#12). Until then: CLI-only. |

### 1.4 Domain model: correct ontology, wrong altitude

The ToolItem → ToolAssembly → ToolInstance → ToolPreset chain matches how TDM/Zoller model the industrial domain, and it is the right long-term skeleton. But the first users think in **one object**: "my ¼″ downcut, it's T3 on the Shapeoko, these feeds work in ply." Representing that takes four records across four endpoints — and both reference clients declined to do it. Third-party client authors will too, each differently, recreating silos.

> **Decision D2 — collapsed `Tool` facade.** *Recommendation:* one endpoint/concept accepting the user's mental object (geometry + machine assignments + cutting parameters), creating/linking the underlying chain server-side. Progressive disclosure: assemblies/instances surface only when the user does something that needs them (serial number, same cutter in two holders). The deep entities remain for phase-2 shops.

> **Decision D3 — server-side identity binding.** *Recommendation:* when a controller sync uploads "T3, D6.35, '1/4 downcut'", the **server** proposes a binding to the matching catalog tool (diameter + name heuristics, user confirms once, sticky thereafter). Binding is what makes the wear-offset round trip possible. Clients never do identity resolution.

> **Decision D4 — Machine becomes an entity.** *Recommendation:* promote `machine_id` from free string to a lightweight Machine entity. Required by D3 (bindings hang off machines), by per-machine cutting parameters (D11), and it should sync FreeCAD's `.fcm` Machine definitions (§3), which carry spindle min/max — data the F&S resolver needs and the controller knows.

### 1.5 Sync semantics

> **Decision D5 — conflict policy.** *Recommendation:* keep optimistic locking, add **divergence surfacing**: when server and machine disagree on a bound tool's value, sync halts that field and reports ("T3 Z-offset: server 50.012 vs machine 50.007 — keep which?") via CLI prompt/web UI. Never silent overwrite of offsets. Full 3-way merge is out of scope for v2.

---

## 2. Market & business findings

### 2.1 Competitive structure (full report available; summary)

The market splits into three layers that don't connect for small users:

1. **Catalog distribution** — MachiningCloud (freemium, GTC/STEP exports), ToolsUnited (1M+ items, partner-licensed), Sandvik CoroPlus Tool Library (~€200/yr, now bundled in Mastercam).
2. **Shop tool-data management** — Zoller TMS, TDM (Sandvik subsidiary), WinTool, Speroni/BIG DAISHOWA. All quote-priced, presetter/hardware-tied, enterprise sales motion. Practical Machinist consensus: ROI doesn't close below ~10 machines.
3. **Crib/inventory** — ToolBOSS, CRIBWISE, GigaTrak. No CAM/geometry awareness.

**Nobody serves the middle layer below ~10 machines, and no product at any price syncs CAM ↔ open controllers.** Hobbyists/small shops run on spreadsheets, CAM-internal libraries (with documented Fusion cloud-library corruption complaints), and DIY converters (FusionToolTranslator, Tim Paterson's Excel app) — direct evidence the problem is real and unsolved generically.

**Consolidation pressure:** Sandvik owns Mastercam + CoroPlus + TDM + CRIBWISE; Hexagon is assembling the rival stack (ESPRIT + MachiningCloud partnership). They will bundle "good enough" tool data into CAM seats. The one thing they structurally cannot offer: **neutrality and self-hosting**. That is the positioning.

### 2.2 The killer feature

The PoC's headline promise is the right killer feature — it just was never implemented:

> **Decision D6 — v2's organizing demo is the wear-offset round trip.** Touch off a tool at the machine → sync → corrected value appears in FreeCAD with provenance and an audit entry. 30 seconds, legible to every machinist, offered by no product at any price for open controllers. Everything in v2's first milestone serves this demo. *Recommendation: accept; build v2 tracer-bullet-first so this works end-to-end on day one.*

### 2.3 ISO 13399: boundary format, not foundation

Research findings (full report available):

- ISO 13399 travels as STEP P21 files referencing **paywalled** dictionaries (2007 *and* 2021 versions). Full implementation: months, pointless. The working industry subset — what Fusion 360 (`Tool.createFromP21`) and Mastercam actually do — parses ~50–100 property codes (DC, LCF, OAL…) which are **openly documented on Sandvik's and Mitsubishi's sites**. Cleanroom P21-property reader: days-to-weeks.
- **GTC** (package spec freely downloadable) is the practical container; Sandvik offers a free ~8 GB bulk catalog; Iscar/Gühring/Mitsubishi/Seco publish per-tool P21/STEP behind free registration.
- **ISO 13399/GTC carries geometry only — no cutting conditions.** Feeds/speeds ride in vendor extensions.
- **No hobbyist vendor publishes ISO 13399.** The hobbyist ecosystem standardizes on **Vectric tool files (plain SQLite, with feeds/speeds!)** — Amana/ToolsToday, SpeTool, Whiteside, IDC Woodcraft, BitsBits all ship free libraries — and **Fusion 360 `.tools`** (ZIP of JSON, stable, BTL has working import code).

> **Decision D7 — ISO 13399 posture.** *Recommendation:* never let 13399 shape the internal schema (keep structured JSON geometry). Ship a pragmatic GTC/P21 property importer in **phase 2** (small-shop courtship), scoped to the Fusion-equivalent subset. Do not buy ISO documents; hard-code vendor-documented property codes.

> **Decision D8 — importer priority for the first 1000 users.** *Recommendation:* (1) Vectric `.tool`/`.vtdb` — unlocks the router-hobbyist world *with* feeds/speeds; (2) Fusion 360 `.tools`; (3) Carbide Create CSV; (4) FreeCAD `.fctb`/`.fctl` + LinuxCNC `.tbl` round-trip (table stakes); (5) GTC/P21 (phase 2). **User-side importers only** — never bundle vendor libraries (ToU/EU database rights; MachiningCloud data contractually controlled). Ask Amana about bundling permission; they distribute freely for marketing. ManufacturerCatalog feature stays parked until importers exist.

### 2.4 License

- loobric-server is **Elastic 2.0** — source-available, not OSI open source. Marketing currently says "open source." First audience is GPL-native (FreeCAD LGPL, LinuxCNC GPL); the Elastic relicensing backlash is living memory in exactly this community.
- The fear ELv2 addresses (cloud vendor resells Loobric-as-a-service) is equally addressed by **AGPL + commercial license** — the Grafana model; Carbon (open-source MES) chose it in manufacturing.

> **Decision D9 — relicense before v2 ships.** *Recommendation:* AGPL-3.0 core + commercial licensing for the hosted/enterprise offering; clients stay MIT. Relicensing is nearly free now (single copyright holder, no external contributions of substance) and impossible-ish later. At minimum, stop saying "open source core" while ELv2. Secondary: pull the pricing page (alpha product + $299/mo tier reads as fiction; the $15→$299 gap has nobody in it; small shops will anchor against CoroPlus at ~€200/yr, not Zoller). Reintroduce pricing with the hosted product, Professional in the $49–99/mo band.

### 2.5 Identity

> **Decision D10 — infrastructure first, business later.** *Recommendation:* optimize v2 for becoming the canonical tool-data backend for FreeCAD CAM + LinuxCNC (achievable: you maintain FreeCAD CAM; LinuxCNC's new tool-database interface is the exact hook). Revenue path (hosted Loobric Web, small-shop tier, Fusion client) follows adoption. The durable user asset — and the moat no vendor-aligned platform can copy — is **what actually worked**: measured offsets and per-material/per-machine cutting parameters (D11), shareable as community libraries.

---

## 3. FreeCAD Feeds & Speeds reconciliation (PR #30078, discussion #30422)

### 3.1 What FreeCAD is building (Phase 1 PoC, open, +2732 LOC)

- **Resolver architecture**: pure function `resolve(tool, material, op) → FeedSpeedResult` walking a priority chain of **Providers** (`ToolPresetProvider`, `ToolDefaultsProvider`), merging per-field, with **confidence scores** and **warnings**. Frozen dataclasses, zero FreeCAD-document imports, fully unit-testable.
- **Presets**: named F&S records stored **on the Tool Bit**, persisted in `.fctb` as an additive top-level `presets` key (older readers ignore it). Storage is **engineering values only** — surface speed (Vc, m/min), chipload (Fz, mm/tooth), optional vert-feed ratio, optional material — raw feed/rpm are *derived at use-time from current tool geometry* and never persisted. Material referenced by **FreeCAD Material UUID** (name fallback).
- **Provenance**: per-field `FeedSpeedProvenance` on the Tool Controller (`"user"` vs `"preset:tool/aluminum-6061/profile"`). The resolver **never overwrites a `"user"` field**.
- **Machine**: `.fcm` machine definitions carry spindle min/max; suggestions are clamped to them.
- **OP_TYPES** controlled vocabulary: `profile, pocket, slot, drill, adaptive, surface_finish` (many-to-one from the op catalog).
- **Explicitly planned extension points**: addon-registered providers (`register_provider(SandvikCatalogProvider(), priority=80)` sketch appears in the dev guide), **Correctors** (chip-thinning etc., phase 2), "rules" (phase 2). The guide's worked example of a future provider is *literally a vendor-catalog lookup*.
- **Stated non-goal**: F&S is a suggestion engine, not an authority; user always in the loop.
- **ADR-000** establishes a full CAM ubiquitous language (Tool Bit, Tool Controller, Tool Library, Preset, Provider, Resolver, Machine…).

### 3.2 Ownership split

FreeCAD is acquiring native Presets, Machine definitions, and resolution logic — territory Loobric's PoC also claimed. The architectures are *complementary, not competing*, if the split is explicit:

> **Decision D12 — FreeCAD resolves; Loobric stores and syncs.** *Recommendation:* FreeCAD owns live resolution (providers, confidence, correctors, UI). Loobric owns **durable storage, cross-installation sync, and community sharing** of the same records: presets, machine definitions, bindings, offsets. Two concrete integrations: (a) since presets live in `.fctb`, a *correct* `.fctb` round-trip syncs presets **for free** — no new FreeCAD-side work; (b) phase 2, a `LoobricProvider` registered in the resolver chain serves shared/community presets live, with provenance `"loobric:<library>/<preset>"`. The provider extension point was designed for exactly this shape of thing.

### 3.3 Schema alignment

> **Decision D11 — adopt FreeCAD's preset schema as Loobric's cutting-parameter record.** *Recommendation:* Loobric's cutting-parameter layer stores exactly FreeCAD's engineering-value schema: `{surface_speed, chipload, vert_feed_ratio?, material_uuid?, material_name?, op_type?}` scoped to (tool, machine?). Never store raw feed/rpm (FreeCAD's dev guide lists this under "what not to do," for the right reason: incoherent under geometry edits). Adopt OP_TYPES as-is. Adopt material-UUID-with-name-fallback, and define the UUID mapping story for non-FreeCAD clients (Vectric importer maps material names → UUIDs where possible, keeps names otherwise). **Sync must respect provenance**: a `"user"`-provenance value on one installation must not be silently replaced by a synced suggestion.

### 3.4 Naming collisions (must resolve before v2 — these will live in support forums forever)

| Term | FreeCAD ADR-000 meaning | Loobric PoC meaning | Resolution (recommendation) |
|---|---|---|---|
| **Preset** | Named F&S record on a Tool Bit (Vc/Fz per material/op) | Machine-specific tool-table entry (tool #, pocket, offsets) | **FreeCAD wins** — it's upstream and shipping. Loobric renames `ToolPreset` → **`MachineToolEntry`** (or `ToolSlot`); Loobric's cutting-parameter records (D11) are called **Presets**, matching FreeCAD exactly. |
| **Tool Library** | Persisted collection of Tool Bits, shared across jobs | (no entity; PoC `ToolSet` ≈ collection of instances/presets) | Map FreeCAD Tool Library ↔ Loobric **ToolSet**, and consider renaming ToolSet → **Library** in the facade vocabulary. `.fctl` ↔ ToolSet is mandatory either way. |
| **Machine** | `.fcm` definition: axes, limits, spindle, post settings | free-string `machine_id` | Loobric Machine entity (D4) syncs `.fcm` content; same word, compatible meaning. |
| **Tool** (bare) | Forbidden — always qualify | Forbidden (UL file) | Aligned. But Loobric's facade (D2) wants the name `Tool`. Acceptable: facade-`Tool` is an API resource name, not prose; document the equivalence Tool ≈ FreeCAD Tool Bit + assignments. Grill this. |
| **Tool assembly** | *Explicitly avoided* in CAM-workbench prose (means TC confusion) | Core entity (holder + cutter) | Keep `ToolAssembly` in Loobric's deep schema (industrially correct; FreeCAD's avoidance is workbench-local), but it never appears in the facade or hobbyist docs. |
| **Provenance** | Per-field source string on TC | (audit log exists, different grain) | Adopt FreeCAD's term and semantics for synced F&S fields (D11). |

Loobric's `docs/UBIQUITOUS_LANGUAGE.md` has been updated with these as proposed resolutions.

---

## 4. What v2 looks like (sketch, pending grill-me)

Tracer-bullet order — each milestone is a working end-to-end slice:

1. **The loop** (D3, D4, D6): facade + binding + LinuxCNC/FreeCAD round-trip → wear-offset demo works. Solo mode (`pipx install loobric-server && loobric-server serve`, no auth ceremony) + minimal read-only web viewer.
2. **Cold start** (D8): Vectric + Fusion `.tools` importers (with F&S), Carbide CSV; lossless export of everything.
3. **The compounding asset** (D11, D12): Preset records synced via `.fctb`; per-material/machine parameters; community library sharing.
4. **Small-shop phase** (D7, parked items): GTC/P21 importer, ManufacturerCatalog revival, LoobricProvider in FreeCAD's chain, hosted offering + pricing.

---

## 5. Decision register (grill-me agenda)

| # | Decision | Recommendation | Status |
|---|---|---|---|
| D1 | What "PoC" means; keep/salvage/discard | No-compat rewrite of contract; keep infra (table §1.3) | Accepted |
| D2 | Collapsed `Tool` facade over deep schema | Yes; progressive disclosure | Accepted |
| D3 | Server-side identity binding | Yes; binding is the product | Accepted |
| D4 | Machine as entity, syncs `.fcm` | Yes | Accepted |
| D5 | Conflict policy | Surface divergence; never silent overwrite; no 3-way merge in v2 | Accepted |
| D6 | Killer feature = wear-offset round trip | Accept; tracer-bullet first milestone | Accepted |
| D7 | ISO 13399 = phase-2 boundary adapter only | Accept | Accepted |
| D8 | Importer priority: Vectric → Fusion → CC CSV → native → GTC | Accept; user-side only | Accepted |
| D9 | License & pricing posture | AGPL + commercial; clients MIT; pull pricing page | Accepted |
| D10 | Identity: infrastructure first | Accept | Accepted |
| D11 | Adopt FreeCAD preset schema (engineering values, UUID materials, OP_TYPES, provenance) | Accept verbatim | Accepted |
| D12 | FreeCAD resolves / Loobric stores+syncs; `.fctb` carries presets; LoobricProvider phase 2 | Accept | Accepted |
| D13 | Naming: Preset→FreeCAD's meaning; ToolPreset→MachineToolEntry; ToolSet↔Library; facade named `Tool` | Proposed in §3.4 — most contestable; grill hard | Accepted |
| D14 | **Tool-number verification** (2026-06-11, from CONCEPTS.md): the tool number is the only identifier in G-code; verifying CAM's number→tool assumption against the machine's bindings is the system's most important job. Both halves are recorded today, but (a) CAM-side numbers ride in opaque client `extra` — should they be a first-class facade field so core can compare? (b) an automated mismatch alarm (Inbox item when a CAM library's numbering disagrees with a machine's confirmed bindings) is designed but unimplemented. | Decide field promotion + alarm before M2 | **Open** |
| D15 | **Physical-instance identity from controllers** (2026-06-12): modern controllers may store a barcode/serial naming the *specific physical tool* (plus dynamic-pocket maps, life counters). Storage is solved — entries key on `(machine, tool_number)`, `pocket` is a mutable attribute, everything else round-trips losslessly in client-namespaced `extra`. But a barcode is *identity*, which makes such a controller identity-carrying: binding could be deterministic (barcode → registered instance) instead of human-confirmed. The deep schema already has `ToolInstance.serial_number` (unmounted, v1); the v2 facade has no physical-instance concept. Same shape as D14: which fields must core *understand* vs merely *preserve*? | Decide whether/when facade grows instance identity; bundle with D14 | **Open** |

---

## 6. Grill-me resolutions (2026-06-09)

Nine questions, all branches closed:

| # | Question | Resolution |
|---|---|---|
| G1 | Server topology | **Persistent LAN box / NAS is canonical**; Docker-first (x86 + ARM), SQLite default. Nothing server-side ever runs on the control box (old image-built distros; admin nervousness). Hosted is the casual path. **Derived constraint:** the LinuxCNC client must be a single-file, stdlib-only Python script (no `requests`) tolerant of ancient interpreters. |
| G2 | Headless binding/conflict UX | **Pending review is first-class server state.** Sync never prompts, blocks, or guesses: unbound tools sync as unbound; conflicting fields freeze. Milestone-1 web UI is an **inbox with exactly two write actions** (confirm binding, pick conflict winner) + CLI `pending`/`resolve`. |
| G3 | API surface | **Facade-only public API.** Deep entities (ToolItem/Assembly/Instance) are private substrate, no compat promise. Facade gaps get fixed, never bypassed. Facade IDs stable for record life. |
| G4 | Naming (D13 amended) | Facade resource = **`ToolRecord`** (user's improvement — keeps an unambiguous term available without a register rule). Per-machine row = **`ToolTableEntry`**, nested as `ToolRecord.machines[]`. Rejected: `MachineToolInstance` (collides with ToolInstance), `ToolPocket` (field-as-whole + Pocket op collision), bare `Tool`. **Amended 2026-06-11:** the facade word **Library** is purged in favor of **`ToolSet`** — "library" is FreeCAD's term, and the public resource now shares the internal entity's name (`/api/v1/tool-sets`). New language rule: core vocabulary, docs, and UI are client-application agnostic; application names (FreeCAD, LinuxCNC, …) appear only when referring to that application's own artifact or term. |
| G5 | FreeCAD PR #30078 coupling | Preset schema is **Loobric's own, version-stamped** (`preset_schema: 1`), convergently identical to the PR. Invariants (engineering values only, UUID materials, user-wins provenance, OP_TYPES) adopted as Loobric principles independent of the PR's fate. Presets land in milestone 3; `.fctb` parser is the only coupling point. Not gated on merge. |
| G6 | License mechanics | **Relicense loobric-server to AGPL-3.0 before any launch publicity** (verified: 22/22 commits are sliptonic's — relicense is free). **Asymmetric contribution policy:** CLA on loobric-server, DCO-only on MIT clients/importers (Grafana precedent). |
| G7 | Hosted at launch | **Both:** public sandbox (demo creds, seeded, wiped nightly, no signup) **and** invite-gated hosted for serious early adopters (explicit no-SLA terms, export-anytime, pre-set account cap, same Docker image as self-host). Open signup deferred to commercial milestone. |
| G8 | Rewrite mechanics | **Existing repos, on `main`**, delete-and-port aggressively; PoC lives in git history. Public API ships as `/api/v1` (no outsider ever adopted the old contract; API free to change until first stable release). Stack unchanged (Python/FastAPI/SQLite). |
| G9 | Milestone-1 definition of done | The acceptance script passes in **Env A** (fresh Docker on NAS-class box + Addon Manager FreeCAD addon + LinuxCNC sim on stock Debian, < 30 min from `docker run` to closed loop) and **Env B** (real machine, recorded — **the demo video is the launch artifact**; the community post ships rewritten around it). CI runs the e2e against real `.tbl` files + live server; full sim run is a release-checklist item. |

---

## Appendix: sources

- **Implementation audit** (June 2026): file-level findings cited inline in §1; repos `loobric-server`, `loobric-freecad`, `loobric-linuxcnc`.
- **Competitive research**: Zoller ([zoller.info](https://www.zoller.info/us/products/tool-management/tms-tool-management-solutions/software-packages)), TDM ([tdmsystems.com](https://www.tdmsystems.com/en/)), WinTool, CoroPlus pricing ([softwarefinder.com](https://softwarefinder.com/manufacturing-software/coroplus-tool-library)), MachiningCloud ([machiningcloud.com](https://www.machiningcloud.com/)), Sandvik/Mastercam acquisition ([home.sandvik](https://www.home.sandvik/en/news-and-media/news/2021/08/sandvik-to-acquire-leading-cam-software-company-cnc-software-inc.-creators-of-mastercam)), Hexagon cloud tooling (2025 PR), Practical Machinist Zoller-TMS thread, market sizing (Growth Market Reports — directional only).
- **Data availability research**: GTC spec ([gtc-tools.com](https://gtc-tools.com/)), Sandvik tool-data downloads, Iscar E-CAT, Gühring digital services, Mitsubishi ISO 13399 property pages, Fusion P21 import ([help.autodesk.com](https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-TOOL-LIBRARY-IMPORT.htm)), `Tool.createFromP21`, Vectric `.vtdb` SQLite format (Vectric forum), Amana/Whiteside/SpeTool/IDC free libraries, BTL formats ([github.com/knipknap/better-tool-library](https://github.com/knipknap/better-tool-library/blob/main/docs/formats.md)), licensing analysis (ELv2: COSS Community, Goodwin; Carbon AGPL precedent).
- **FreeCAD F&S**: [PR #30078](https://github.com/FreeCAD/FreeCAD/pull/30078) (4 commits, 17 files, +2732/−33, updated 2026-05-26), [discussion #30422](https://github.com/FreeCAD/FreeCAD/discussions/30422) "Feeds and Speeds Developer Guide", ADR-000 (branch `sliptonic/FreeCAD@FSImp`, `src/Mod/CAM/Roadmap/ADR/ADR-000.md`).
