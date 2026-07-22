# Loobric v2 Reboot — Audit, Diagnosis, and Recovery Plan

**Date:** 2026-06-18 · **Status:** HARD STOP declared. No feature work until Phase 0–1 land.
**Author of stop:** project founder (sliptonic). **Trigger:** conceptual drift; the
ubiquitous language is being ignored; new concepts ("Adopt", "Coverage", "Type") are
shipping without confirmation; relationship vocabulary is inconsistent ("bind" vs "link"
vs "mirror"); the FreeCAD UI degrades with every change.

**Inputs:** three independent code audits (vocabulary drift, FreeCAD UX/architecture,
core-vs-docs integrity), all run 2026-06-18, cross-checked against
`loobric-server/docs/UBIQUITOUS_LANGUAGE.md`, `TOOL_SCHEMA.md`, `CONCEPTS.md`, and
`REIMPLEMENTATION_PLAN.md`. Every file:line below was spot-verified against the tree.

**Companion docs:** `REIMPLEMENTATION_PLAN.md` (the v2 plan; principles still hold),
`loobric-server/docs/UBIQUITOUS_LANGUAGE.md` (to be rewritten — see Phase 0).

---

## 1. Executive diagnosis — the counterintuitive finding

**The foundation is not weak. There is too much of it, written at four different moments,
never reconciled.** `CONCEPTS.md`, `UBIQUITOUS_LANGUAGE.md`, `REIMPLEMENTATION_PLAN.md`,
and `TOOL_SCHEMA.md` are each, individually, strong documents. The drift is the *gap
between* these careful layers, plus a layer of vocabulary that was coined during
implementation and never passed through any of them.

There are three fault layers, in increasing severity of governance failure:

### Fault A — two "normative" documents disagree about the core noun

| Document | Date | The core tool resource is… | Status |
|---|---|---|---|
| `UBIQUITOUS_LANGUAGE.md` — self-labeled *"normative for the facade"* | 2026-06-09/11 | **`ToolRecord`** (flat facade; deep term "instance" *never* at the boundary) | Stale; still labeled normative |
| `TOOL_SCHEMA.md` — self-labeled *"authoritative contract"* | 2026-06-15 | **`ToolInstanceRecord`** + `ToolCatalogRecord` (sectioned, provenance-tagged) | Newest; excellent; what was actually approved |
| Running code (`loobric_server/main.py:102-107`) | last ~2 weeks | `/api/v1/tool-instance-records`, `/api/v1/instance-inbox` | Follows the schema; contradicts the glossary |

The document that announces itself *"normative for the facade"* describes a system that no
longer exists. The deep-schema word **"instance"** — which the glossary explicitly forbids
at the public boundary — now appears in public URLs, because `TOOL_SCHEMA.md` promoted it
and nobody updated the glossary to bless or forbid that. **Every "instance leaked into
public" symptom is downstream of this single unreconciled fork.** It is a
documentation-governance failure, cheap to fix once the fork (§6) is decided.

### Fault B — concepts coined in code that never entered the language

`TOOL_SCHEMA.md` is clean: it uses "bind" correctly, says a ToolSet is *not* a FreeCAD
library, and never mentions "Adopt", "Coverage", "Needs Attention", or "Reconcile". Those
words did not come from any design doc. They were invented feature-by-feature, with no
glossary gate, and several are now baked into the **public API contract** and the
**immutable audit log**. This is the drift the founder is reacting to. (Full list: §5,
§7.)

### Fault C — the FreeCAD UI has no view-model, so every fix ripples

Not vibes — a specific structural defect. `LoobricTabs.py` is a **1,387-line god-module**
holding all 7 tab classes + 3 dialogs. Each tab independently re-fetches raw JSON and
re-derives the same joins inline; the "which entry is bound to which tool" join is
reimplemented **three times** with three column layouts (`ToolsTab.populate`,
`MachinesTab.refresh`, `NeedsAttentionTab.refresh`). Consequences:

- There is no single answer to "what should this window show," so each tab invents its own
  — **and coins its own word for it.** Vocabulary fracture and UI fragility share one root.
- Change how "bound" displays → edit three tabs by hand → they drift → a fix to one
  regresses a sibling. **Exactly the symptom reported.**
- Proof already in the tree: the two top-of-file docstrings (`LoobricDialog.py:11-13` and
  `LoobricTabs.py:8-13`) **disagree about which tabs exist**, and
  `needs_attention_preview.py` exists *only* because the authors couldn't tell what their
  own tab renders without simulating it.

**Blast radius is small.** The rot is concentrated in (1) the docs/vocabulary boundary and
(2) the FreeCAD widget layer. The engine, the schema, and the headless clients are sound.

---

## 2. What is solid — keep, do not throw away in the reboot

- **The domain thinking.** `CONCEPTS.md` is excellent (the loop; tool-number-as-contract;
  intent-vs-observation; why binding lives in core). Keep wholesale.
- **`TOOL_SCHEMA.md` + `loobric_server/contract/models.py`.** Sectioned model (internal / canonical
  / clients), provenance-tagged fields, three doors (sync / observe / assert). Rigorous,
  faithfully implemented, with real contract tests (`tests/contract/`,
  `test_schema_contract.py` validates golden fixtures against the models). Best asset in the
  repo.
- **loobric-server engine.** Sectioned routers, binding engine (`binding_v2.py` on
  `SlotProposal`), instance inbox — well-built, well-tested.
- **FreeCAD *headless* half.** `client.py` (clean stdlib client, single `http_json` seam),
  `sync.py` (3-way plan/apply, never-guess-without-a-base, lossless writeback — faithful to
  the plan's "never clobber"), `mapping.py` (lossless `.fctb`/`.fctl` round-trip incl.
  unknown keys), and the **pure** functions in `uihelpers.py` (row builders, `cascade_choice`,
  rollups). The last is the seed of the real view-model.
- **loobric-linuxcnc.** Single-file, stdlib-only, surgical `.tbl` writeback with backups. Sound.

---

## 3. Evidence — the drift, with citations

### 3.1 Relationship vocabulary has fractured into seven words

The founder flagged "bind" vs "link". It is worse: there are **at least seven** competing
words for "a relationship between two entities," and the two main relationships each use a
different (and overloaded) verb.

| Word | Relationship it names | Where (sample) | Status |
|---|---|---|---|
| **bind / bound / unbind** | ToolTableEntry ↔ ToolRecord | glossary; FreeCAD `"Bind existing tool"`; web `unbindSlot()`; linuxcnc `is_bound` | ✅ approved |
| **adopt** | mint+bind a new record from an entry | API `POST /…/adopt` (`tool_table_entry_records.py:373`); web/FreeCAD buttons; CLI; `client.adopt_entry` | ❌ drift |
| **link / link-machine / linked** | ToolSet ↔ Machine | FreeCAD `"Link set to machine…"`; web `linkSetToMachine()`; CLI `link-machine`; col `"Linked machine"` | ❌ drift |
| **mirror / mirrors** | ToolSet ↔ Machine (*same* relation as link) | `HOWTO_MIRROR…` doc; web `"mirrors ${machine}"`; CLI help; `TOOL_SCHEMA.md:263` `"this set mirrors this machine"` | ❌ second word for one relation |
| **install / installed / install link** | the *bound* state, presented | FreeCAD col `"Installed"`; web `installed` pill, `"install link"` | ❌ synonym for "bound" |
| **assert** | write a canonical value w/ provenance | web `/assert`; FreeCAD `"Type asserted."` | ⚠️ schema term, leaking to user UI |
| **reconcile** | align set numbering ↔ machine slots | API `POST /…/reconcile`; CLI; button; audit op `"RECONCILE"` | ❌ drift, written into audit log |

Net: the entry↔record relation is "bind" (good) but is *also* called "adopt" and
"install"; the set↔machine relation is "link" *and* "mirror" interchangeably. A reader
cannot infer the relationship from the word.

### 3.2 The headline term doesn't exist; the deep term is public

- The glossary's flagship public term **`ToolRecord` does not exist in the running system**
  (grep finds it only in comments: `tool_instance_records.py:17`, `schema.py:201`).
- The facade resource is `ToolInstanceRecord` at `/api/v1/tool-instance-records`
  (`main.py:102`); the inbox is `/api/v1/instance-inbox` (`main.py:107`). The deep word
  "instance" is in the public path.
- The facade concept **`Preset`** (glossary) has **no public endpoint** — presets exist
  only on the hidden deep `/api/v1/tool-presets` router. Promised facade term,
  unimplemented in v2.
- `ToolCatalogRecord` is public (`main.py:103`) but is **not in the glossary at all** — it
  came from `TOOL_SCHEMA.md` only.

### 3.3 Concepts that never entered the language (and how load-bearing they are)

| Concept | Footprint | Load-bearing? |
|---|---|---|
| **Coverage** | `GET /tool-set-records/{id}/coverage` (`tool_set_records.py:338`) + pure `compute_coverage()` + CLI `loobric coverage` + FreeCAD `"Needs Attention"` aggregation + ~12 web-UI refs + a private sub-vocabulary (`absent_on_machine`, `machine_only`, `number_mismatch`). A HOWTO says it "lands once the coverage view ships (issue #18)" — issue → code, no glossary pass. | Yes, fully — but low entanglement; pure function, two consumers. |
| **Reconcile** | `POST /tool-set-records/{id}/reconcile` (`:374`) + CLI + FreeCAD button + audit op `"RECONCILE"`. | Yes; no glossary definition. |
| **Adopt** | `POST /…/adopt` (`tool_table_entry_records.py:373`) + audit `{"adopted": true}` + web/FreeCAD buttons + CLI + `client.adopt_entry`. | Yes; a real "mint+bind" concept with no approved verb. |
| **Needs Attention** | FreeCAD *primary* tab `LoobricTabs.py:932` + `needs_attention_preview.py` + `needs_attention_rows()`. **Duplicates the glossary's Inbox** — FreeCAD ships *both* tabs (`LoobricTabs.py:595` Inbox, `:932` Needs Attention). | Yes; competing surface. |
| **Libraries** (FreeCAD tab `:200`) + "Central Tool Library" (homepage `index.astro:123,167`) | resurrects the term explicitly **purged 2026-06-11** in favor of ToolSet. | Cosmetic but high-visibility (product hero). |
| **slot / slots** | public `/sync` payload field (`loobric_linuxcnc.py`) + web/FreeCAD noun for ToolTableEntry. | Yes — conflates "Pocket" (a position) with "ToolTableEntry" (the row), in the public contract. |

### 3.4 FreeCAD information architecture (the actual map)

One **application-modal** `QDialog` (`exec_()`, `LoobricCommands.py:45`), 820×620, **7 tabs**:

```
Loobric toolbar button → LoobricWindow (MODAL, 7 tabs)
  Needs Attention   ← opens here; auto-runs plan_sync + per-set coverage (N+1)
  Libraries         (full plan/apply tree — a SECOND plan_sync of the same truth)
  Inbox             (confirm/reject/adopt)
  Tools             (rename/set type/delete)
  Tool Sets         (rename/reconcile/delete)
  Machines          (bind/adopt/unbind/delete)
  Audit             (read-only)
  bottom: [Inspect JSON] [API Log] … [Close]   ← debug surfaces in primary chrome
```

Overlaps (two ways to do one thing): resolve-an-exception (Needs Attention vs Libraries);
bind/adopt (Inbox vs Machines); the ToolSet object (Libraries tab vs Tool Sets tab); the
sync plan computed twice. Dead end: import success message says *"reload / restart
FreeCAD"* — but the window is modal, so you must close it to comply.

### 3.5 Core integrity — loose ends confirmed in the tree

- **`loobric_server/api/tool_sets_deep.py`** — ~530 lines, **not mounted**; referenced only by a
  comment at `main.py:111`. Dead.
- **`BindingProposal`** ORM model — found only in `schema.py`; the live engine uses
  `SlotProposal` (`binding_v2.py`, `instance_inbox.py`, `machine_records.py`,
  `tool_table_entry_records.py`). Orphaned v1 table.
- **Duplicate retired tables** coexisting with `*_records` successors: `machines`,
  `tool_table_entries`, `tool_sets`, `binding_proposals`.
- **Hidden-but-live deep routers** (`main.py:113-117`, `include_in_schema=False`):
  `tool_items`, `tool_assemblies`, `tool_instances`, `tool_presets`, `tool_usage` — reachable,
  authenticated, undocumented, still heavily tested. No removal milestone.
- **Vestigial migrations** against retiring deep tables (`migrations/add_tags_columns.py`,
  `add_tags_to_resources.py`, `remove_machine_id.py`) — yet `TOOL_SCHEMA.md:11-12` says v2
  has *no migration* (wholesale replace) and `init_db` always `create_all`s.
- **A claimed contract test that does not exist.** `UBIQUITOUS_LANGUAGE.md:50` asserts
  *"Publishing exactly the facade vocabulary and nothing else is a tested contract (deep
  routes are excluded from the schema)."* No such assertion exists; the only OpenAPI tests
  (`test_api_basic.py:41-55`) check status 200 + presence of `openapi`/`info` keys.
  "Private" is currently a documentation choice, not an enforced boundary.
- **Stubs presented as features / unenforced scopes:** `oauth2.py` (5 TODOs, fully stubbed);
  `auth.py:546` `# TODO: Verify user owns the key` (authz gap on key delete);
  `backup_api.py:46,83` admin-scope TODOs.
- **FreeCAD stale docs:** `TECHNICAL.md`/`DEVELOPMENT.md`/`README.md` describe the purged
  ToolItem/ToolPreset vocabulary, a `requests` dependency, `InitGui.py`/`fctb_parser.py`,
  and an Export/Import UI that does not exist.
- **Dead `auto_sync` preference** (saved + reloaded, never read); **duplicated**
  `_normalize_url` (`LoobricDialog.py:49` and `LoobricPreferences.py:58`).

---

## 4. Root causes (why drift keeps happening — fix these or it recurs)

1. **No single normative vocabulary that matches the code.** Two "authoritative" docs
   disagree (Fault A); neither matches the running paths. With no source of truth, every
   contributor picks a plausible word.
2. **No enforcement gate.** Nothing fails CI when a new concept ("Coverage") or an
   unsanctioned word ("Adopt") ships. Concepts go issue → code, skipping the language.
3. **No FreeCAD view-model.** The tabs *are* the model; each re-derives the world and names
   it locally (Fault C). Every UI change ripples and coins a word.
4. **Scope creep past "the loop is the product."** Coverage, Reconcile, the Needs Attention
   aggregation, dual binding surfaces — none serve the wear-offset round trip the plan made
   the sole M1 objective. They expanded surface (and vocabulary) without earning it.

---

## 5. The naming fork — DECIDED 2026-06-18: Option 2 (ratify the schema)

**Decision (R3):** ratify the sectioned schema as the public vocabulary. `ToolInstanceRecord`
/ `ToolCatalogRecord` / `instance-inbox` are the official public terms; the old flat
`ToolRecord` facade term is retired. Optimize for consistency across code/docs; defer
user-facing labels (button text, dialog titles) to a later pass. `UBIQUITOUS_LANGUAGE.md` has
been rewritten to match `TOOL_SCHEMA.md` and the running code. The two options are kept below
for the record.

### Option 1 — Facade hides the schema (most faithful to original intent)
Keep the sectioned schema internally; present a clean public facade. `ToolRecord` is the
public name; `instance`/`catalog`/sections stay internal.

- Public: `/api/v1/tool-records`, `/api/v1/inbox`; vocabulary = ToolRecord, ToolSet,
  Machine, ToolTableEntry, Preset, Binding.
- **Cost:** rename public routes + response envelopes + both clients + CLI + web UI +
  contract tests. Larger code change. **Benefit:** restores "deep terms never at the
  boundary"; the glossary becomes true again with minimal rewrite.
- **Risk:** the facade must now *translate* `ToolInstanceRecord`↔`ToolRecord` and decide how
  `ToolCatalogRecord` is publicly named (or hidden) — real design work, since the catalog
  record is a genuinely public concept the flat-facade glossary predates.

### Option 2 — Schema wins, ratify it (cheapest)
Update the glossary to bless the sectioned vocabulary as public: `ToolInstanceRecord`,
`ToolCatalogRecord`, `instance-inbox` become official.

- Public surface unchanged (code already matches). **Cost:** rewrite the glossary; accept
  that "instance" lives at the public boundary the glossary once forbade. **Benefit:**
  near-zero code churn; one excellent doc (`TOOL_SCHEMA.md`) becomes the single source.
- **Risk:** concedes the facade-cleanliness principle; "ToolInstanceRecord" is a mouthful
  for the product's central noun and will appear in every client and marketing surface.

### Recommendation
**Option 1, with a narrow scope.** The whole point of the facade (G3, plan principle 2) is
that the public boundary speaks a small, stable, clean vocabulary while the deep schema is
free to be as rich as `TOOL_SCHEMA.md` makes it. Option 2 is cheaper today but permanently
surrenders the property the project repeatedly chose to protect, and it bakes "instance"
into every future client. The translation work in Option 1 is bounded (it is exactly the
facade layer that already exists in concept) and it makes the glossary honest again. But
this is a founder call — the cost is real and the schema doc is genuinely good.

---

## 6. The LOCKED decision — rip out crept-in concepts (re-earn entry)

Decided 2026-06-18: concepts that shipped without passing through the ubiquitous language
are **removed now**. Any that prove genuinely needed return only through the language
process with a ratified term and founder sign-off. Targets:

| Remove | Where | Replacement / fate |
|---|---|---|
| **Coverage** | `tool_set_records.py:338` `/coverage` + `compute_coverage` + CLI `coverage` (`loobric.py`) + FreeCAD Needs-Attention aggregation + web coverage section + sub-vocabulary | Delete. The need ("which promised tools aren't on the machine yet") returns later via the language if it earns a place. |
| **Reconcile** | `tool_set_records.py:374` `/reconcile` + CLI + FreeCAD button + audit op `"RECONCILE"` | Delete. |
| **Adopt** | `tool_table_entry_records.py:373` `/adopt` + audit `adopted` flags + buttons + CLI + `client.adopt_entry` | Fold into **bind** (a bind that mints a new record is still binding); one verb. |
| **"Needs Attention" tab** | `LoobricTabs.py:932` + `needs_attention_preview.py` | Delete; the glossary's **Inbox** is the single attention surface. |
| **mirror / link** (two words, one relation) | docs, web, CLI `link-machine`, FreeCAD `"Link set to machine…"` | Pick **one** word for ToolSet↔Machine during Phase 0; purge the other. (Word TBD with the glossary rewrite.) |
| **install / installed** | FreeCAD col, web pill | Replace with the bound/unbound state language. |
| **Libraries** tab + "Central Tool Library" | `LoobricTabs.py:200`, homepage `index.astro:123,167` | **ToolSet** (term was purged 2026-06-11). |

---

## 7. The phased reboot plan (the to-do list)

Each phase unblocks the next; early phases are cheap and high-leverage. **No new feature
work until Phase 1 lands.**

### Phase 0 — One source of truth (docs only, no code) — ✅ DONE 2026-06-18
- [x] **Decide the naming fork (§5).** → R3 = Option 2 (ratify the schema).
- [x] Rewrite `UBIQUITOUS_LANGUAGE.md` so it and `TOOL_SCHEMA.md` agree; retire the v2-flat
      `ToolRecord` term; reframe the deep schema as legacy; dated.
- [x] Record the §6 rip-out decisions (Rejected terms table) and set↔machine word (link) in the glossary.
- [x] The **gate** paragraph added to the glossary (enforced in Phase 1).

### Phase 1 — Stop the bleeding (enforcement) — ✅ DONE 2026-06-18
- [x] **The missing contract test now exists:** `tests/contract/test_facade_vocabulary.py`
      asserts the published OpenAPI excludes the legacy deep routers (the glossary's
      previously-false claim is now true), publishes the facade resources (positive control),
      and carries no retired concept on a public path.
- [x] **Vocabulary denylist:** the same file asserts the bundled web UI + CLI reference no
      retired endpoint (`/adopt`, `/coverage`, `/reconcile`, `/mirror`). (A broader UI-string
      denylist can extend this once the FreeCAD rebuild lands.)

### Phase 2 — Cut dead weight (independent of the naming fork) — IN PROGRESS
- [x] **§6 rip-out in loobric-server (server + CLI + web UI + tests):** removed `/coverage`,
      `/reconcile`, `compute_coverage`, the coverage unit test; **folded `/adopt` into `/bind`**
      (bind mints a new instance when `instance_id` is omitted; audit flag `minted`, not
      `adopted`); removed the CLI `coverage`/`reconcile` commands; web UI coverage tab/section
      and reconcile buttons removed and adopt→bind; purged "mirror" → "link" in CLI strings.
      Core suite green (see below). *Done 2026-06-18.*
- [ ] **loobric-freecad rip-out — DEFERRED to Phase 3.** The FreeCAD client's coverage /
      needs-attention / adopt code lives in the widget layer (`LoobricTabs.py`, `uihelpers.py`,
      `client.py` methods `get_set_coverage`/`reconcile_set`/`adopt_entry`) that Phase 3
      rebuilds wholesale; ripping it out now is throwaway. Its tests use a FakeServer so they
      are not broken by the core change, only contract-stale. Fold into the Phase 3 rebuild.
- [ ] loobric-linuxcnc: unaffected (no calls to the removed endpoints; "reconcile/adopt" appear
      only as English in its own sync-semantics comments — optional later wording pass).
- [x] Deleted `loobric_server/api/tool_sets_deep.py` (unmounted dead router) and the orphaned
      `BindingProposal` model + its stale doc references. *Done 2026-06-18.*
- [x] Deleted the 3 vestigial migrations (`add_tags_columns.py`, `add_tags_to_resources.py`,
      `remove_machine_id.py` — no runner; `migrations/` now empty) and the **orphaned legacy ORM
      models `Machine` + `ToolTableEntry`** (tables `machines`/`tool_table_entries` — nothing
      referenced them; backup never even listed them). App imports clean, suite green.
- [~] `tool_sets` legacy table **NOT removed** — still used by `backup.py`, `versioning.py`,
      `dependencies.py`. Removal is entangled with R9 (backup rewrite) and R6; deferred there.
- [x] **Security TODOs resolved (not just removed):**
      • `auth.py` key-revoke now verifies ownership (returns 404 to non-owners so key ids can't be
      probed) — previously any user could revoke any key.
      • `backup_api.py` `/export` + `/import` are now **admin-gated** (`require_admin`); they
      previously had **no auth at all** (open full-DB dump/restore). Solo user is admin, so solo
      keeps working. Regression tests added (`tests/contract/test_backup_authz.py`).
- [x] `oauth2.py` **deleted** — a fully-stubbed, unreferenced module not in the v2 plan (R7).
- [x] The hidden deep routers now have the exclusion test (Phase 1); removal milestone = R6.

**Phase 2 status: complete** except the `tool_sets`-table removal, which is correctly deferred
into R9/R6 (it cannot be cut without rewriting backup/versioning).

### Phase 2.5 — loobric as the reference Python client (drift prevention)
`loobric.py` becomes THE reference implementation for Python clients and our endpoint-testing
instrument. Decisions (grill 2026-06-18): MIT-licensed, stays single-file & stdlib-only in core,
vendored by clients; full public coverage incl. admin; account-reset via a server endpoint; a
route↔verb drift test + live CLI verification. See memory `loobric-reference-client`.
- [x] **Relicensed** `loobric.py` AGPL → MIT (file-level header, with a note on its role).
- [x] **Split internally** (done 2026-06-18): `make_request` is now a raising transport
      (typed errors `LoobricError`/`NotFound`/`AuthRequired`/`HTTPError`/`ConnectionFailed`,
      never prints/exits); a `Client` class is the importable ops layer (returns data); the CLI
      command shell routes through `Client` via `_client()`; `main()` catches `LoobricError`.
      `from loobric import Client, NotFound` works. CLI tests green (29), full suite 369 pass
      (only the 2 R8 failures), verified end-to-end against the live solo server.
- [x] **Coverage audit done:** loobric exercises 20/60 published routes; gap list recorded.
- [x] **Coverage filled — loobric reaches ALL 60 published routes.** `Client` gained the canonical
      doors (`observe_field`, `sync_client_section`), record creation (instance/catalog/entry),
      `set_members`, `delete_tool_set`, admin (users, catalogs, changes, audit-logs, backup
      export/import via stdlib multipart), `whoami`/`change_password`, and `reset_account`. CLI
      verbs added: `create-machine`/`create-set`/`push`, `reset`, `whoami`, `audit`,
      `backup-export`/`backup-import`, `assert`. Resolution now matches by **name**, not just
      id-prefix. Dogfooding fixed real bugs: empty-`{}`-body dropped (422 on creates), `list-keys`
      didn't show revoked state, and the `--slot`→`--entry` term leak (R10).
- [x] **Account reset:** `POST /api/v1/account/reset` (`loobric_server/api/account.py`, admin, atomic,
      deletes the caller's tool data, keeps user+keys) + loobric `reset` verb + glossary entry.
      Contract tests (`test_account_api.py`) + live demo confirm it.
- [x] **Drift test:** `tests/contract/test_loobric_coverage.py` statically asserts every published
      OpenAPI route is reachable through loobric's `Client` (segment-wildcard matching covers the
      generic doors). It already caught 2 gaps (`delete_tool_set`, a variable-built `list_entries`
      endpoint). This is the Phase-1 gate's sibling for the client — full coverage is now enforced.
- [x] **Workflow:** a `LOOBRIC_SOLO=1` server driven through the loobric CLI is how endpoints get
      verified/demoed (used throughout this phase); pytest stays as the net.

- [x] **Hardened to "working, reliable, documented, tested"** (founder gate before FreeCAD):
      • **Tested at 4 layers** — `make_request` transport unit tests (`test_loobric_transport.py`,
      fake connection: empty-`{}` body, multipart, headers, typed errors); mocked CLI
      contract-of-calls (`test_loobric_cli.py`); **live end-to-end integration**
      (`tests/integration/test_loobric_live.py`, 15 tests driving the CLI/Client through the real
      app in-process via a transport bridge); the route↔verb drift gate. The live sweep is what
      found R12.
      • **`Client` gained an injectable `transport`** (enables in-process testing; also lets clients
      supply their own).
      • **Documented** — `docs/CLI.md` rewritten to the current 29 commands (removed the dead
      `reconcile`/`coverage` sections, added the 9 new verbs, added a "Using loobric as a library"
      section); the `--help` epilog refreshed.

**Phase 2.5 status: complete + hardened.** Full suite **408 pass** (only the 2 R8 failures). Minor
note: `whoami` (`GET /auth/me`) returns "not authenticated" in solo mode — `/auth/me` is
session-based and solo has no session; harmless, pinned by an integration test.

### Phase 3 — Rebuild the FreeCAD UI (the overhaul) — DONE
Decisions ratified by the founder 2026-06-19: **one Sync tab**, **fold Inbox into Machines**,
and **do the loobric swap in this pass**. Executed 2026-06-19:
- [x] Promoted the pure helpers into **one tested view-model** (`viewmodel.py`, replacing
      `uihelpers.py`): `sync_tree` and `machine_tables` answer "what to show" once; the dead
      `/coverage` + needs-attention helpers were deleted. New `tests/test_viewmodel.py`.
- [x] Collapsed the IA to **three tabs — Sync · Machines · Audit**. Sync is the one CAM surface
      (plan tree + a "needs attention" filter = a view over the one plan; Tools/Tool Sets folded in
      as row actions: rename, set type, delete, link-to-machine; double-click a changed row to
      resolve). Machines is the one binding surface (Inbox folded in — Confirm/Reject inline +
      Pending band; Bind existing / **Bind new** = `/bind` with no instance_id, replacing Adopt).
      "Inspect JSON"/"API Log" demoted behind a **Debug ▾** menu.
- [x] Window is **modeless** (`window.show()`, reference kept); the restart dead-end softened to a
      status line; duplicate fetches collapsed (one plan / one `machine_tables` join per refresh).
- [x] **Vocabulary pass**: zero user-facing `slot`/`install`/`Coverage`/`Adopt`/`Reconcile`; the
      Sync filter "needs attention" is founder-approved (it filters the sync plan, ≠ the old tab).
- [x] **loobric vendored** (`freecad/Loobric/loobric.py`); the bespoke `LoobricClient` (urllib +
      `http_json` + `LoobricError`) is **deleted** — `client.py` is now a thin
      `LoobricApi(loobric.Client)` adapter (FreeCAD identity, sync-lane helpers, `ping`, a recording
      transport for the API-log/tests). `sync.py` needed no rewrite (alias + preserved method names).
- [x] Verified: headless suite **87 pass**; contract grep clean (no removed-endpoint calls); live
      loop driven through `LoobricApi` against a `LOOBRIC_SOLO=1` server (machine → entries → sync
      lane → bind existing → bind-new/mint → `machine_tables` join → link → audit → reset).
- [x] **In-FreeCAD smoke** done (founder, 2026-06-19): 3 tabs / filter / inline Confirm-Reject /
      clean vocabulary confirmed against the live cloud server.
- [x] **Web UI brought to the same model** (loobric-server `70653ae`): folded the Inbox into the
      Machines tab — entries surface their proposal inline (Same tool / Different / Bind new), a
      "Pending review" filter, Inbox tab removed. Fixed the duplicate-minting trap (Machines now
      offers "Same tool" instead of only "Bind new").
- [x] **Cosmetic/UX cleanup pass** (loobric-freecad `c3aab2f`): connection status → plain text +
      tooltip; one header Refresh; "Audit" → "Audit log"; inline Log pane removed; Inspect →
      right-click on every tab; theme-invisible checkboxes → toggle buttons; bulk buttons gain
      tooltips + disable when idle; Tool-type column populated.
- [x] **The gate extended (REBOOT R11 closed)** (loobric-server `78e8a88`): the vocabulary contract
      test now scans the bundled web UI + CLI for rejected *words* (not just endpoint paths), so a
      label like "Adopt" or a `--slot` flag fails CI. This is why the web-UI "Adopt" leak and the
      `--slot` flag had slipped through.

### Phase 4 — Realign docs to what runs (plan principle 7)
- [ ] Rewrite/delete FreeCAD `README.md`, `TECHNICAL.md`, `DEVELOPMENT.md` (purged
      vocabulary, dead deps, non-existent UI).
- [ ] Homepage copy: "Tool Library" → ToolSet language.
- [ ] Then, and only then, resume feature work — on the loop, nothing else.

---

## 8. Decision register

| # | Decision | Status |
|---|---|---|
| R1 | Hard stop; no feature work until Phase 1 | **DECIDED** 2026-06-18 |
| R2 | Rip out crept-in concepts; re-earn entry via the language | **DECIDED** 2026-06-18 (§6) |
| R3 | Naming fork: ratify the sectioned schema (Option 2); public = `ToolInstanceRecord`/`ToolCatalogRecord` | **DECIDED** 2026-06-18 |
| R4 | Single word for ToolSet↔Machine = **link / linked** (purge "mirror") | **DECIDED** 2026-06-18 (provisional, pending user-facing-label pass) |
| R5 | `ToolCatalogRecord` is a ratified public term | **RESOLVED** by R3 |
| R6 | Fate of hidden deep routers (remove vs keep+test) | OPEN — Phase 2 |
| R7 | `oauth2.py`: finish or delete | **RESOLVED** 2026-06-18 — deleted (unreferenced stub, not in v2 plan) |
| R8 | `test_registration_security.py` (2 failing) — **diagnosed:** test-isolation defect, not a code regression. The tests assume an empty DB ("first user open, rest require auth") but the `client` fixture runs against the persistent `loobric.db` (no per-test DB reset in conftest). Fix = isolate the fixture's DB per test. Pre-existing; unrelated to the reboot. | OPEN — test hygiene, low risk |
| R9 | `backup.py` backed up only the LEGACY deep tables, not the v2 sectioned `*_records`. **RESOLVED 2026-06-18:** `ENTITY_ORDER` + clear-functions rewritten to the v2 records (`machine_records`, `tool_instance_records`, `tool_catalog_records`, `tool_table_entry_records`, `tool_set_records`, `entry_proposals`, users, api_keys). Proven by a live export→wipe→import roundtrip (`test_loobric_live.test_backup_roundtrip_captures_v2_data`); `test_backup.py` migrated. | **RESOLVED** 2026-06-18 |
| R10 | **"slot" purged project-wide** 2026-06-18 → **entry / ToolTableEntry** (wire fields too: `/sync` `slots`→`entries`, inbox `slot`→`entry`, `slot_id`→`entry_id`, `slots_removed`→`entries_removed`; ORM `SlotProposal`→`EntryProposal`, `SlotIn`→`EntryIn`, etc.). Done across loobric-server (server+loobric+web UI+tests), loobric-linuxcnc, loobric-freecad (live wire reads), and all docs + the glossary (slot added to Rejected terms). **Pocket** kept (magazine position); OP_TYPES `slot` kept (slotting operation — different meaning). Full suite 377 pass (only R8); loop verified live with `--entry`. | **RESOLVED** 2026-06-18 |
| R11 | **Gate blind spot:** the Phase 1 enforcement test checks OpenAPI *paths* + retired-endpoint strings, but NOT CLI flag names / help text / UI labels against the glossary. That is why `--slot` shipped. Extend the gate to cover user-facing client vocabulary. | OPEN — founder declined for now |
| R12 | The `/changes` change-detection endpoints validated `entity_type` against the **legacy** tables only, rejecting the v2 sectioned records. **RESOLVED 2026-06-18:** `changes_api.ENTITY_TYPES` rewritten to the five v2 sectioned records (`change_detection.py` was already generic — no change). loobric's `changes_since_version`/`since_timestamp` query-param names fixed (`since_version`/`since_timestamp`). Proven by `test_loobric_live.test_changes_works_for_v2_records`; `test_changes_api.py` migrated. | **RESOLVED** 2026-06-18 |

---

*This document is the anchor for the reboot, the way `REIMPLEMENTATION_PLAN.md` anchored
v2. When code and this document disagree, fix one of them — do not let them drift.*
