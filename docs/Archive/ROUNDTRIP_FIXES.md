# Roundtrip fixes — implementation spec

Two independent fixes are needed to make [ROUNDTRIP.md](./ROUNDTRIP.md) close
cleanly:

- **Fix 1** — FreeCAD's phantom "local is newer" after a download (ROUNDTRIP
  steps 4–5). A baseline bug, contained to `loobric-freecad`.
- **Fix 2** — the requested-member loop (ROUNDTRIP steps 5–10). A modeling gap
  spanning `loobric-server` and `loobric-linuxcnc`.

They are separable; ship them independently.

---

## Fix 1 — FreeCAD download baseline (phantom double-apply)

### Symptom
After downloading set `millstone` and pressing **apply**, the dialog reports the
local tools are *newer* and must be uploaded. A second **apply** clears it. (ROUNDTRIP
steps 4 → 5.)

### Root cause
The diff is a 3-way semantic compare of `local` / `base` / `regenerated`
(`loobric-freecad/freecad/Loobric/sync.py:164-183`, `_classify`). With no base it
can only return `unchanged` or `conflict`; a real base is required to ever
classify correctly.

The two entity kinds get their base from **different places**:

- **Sets** keep a local snapshot: `set_snapshots[set_id]` in `.loobric_state.json`
  (`sync.py:255-280`), rewritten on every pull (`sync.py:777`). Sets are fine.
- **Instances/bits** have **no local snapshot**. Their base is read back from the
  server's own section, `clients.freecad.data.fctb`, via `_base_fctb()` in
  `plan_sync` (`sync.py:383`).

But a plain download never populates that server section. `pull_bit()` writes the
local `.fctb` (`sync.py:722`) and only calls `put_instance_section()` **when a
shape correction was made** (`sync.py:736`, inside `if chosen and chosen != …`).
For the normal case (instances created by the bind step in the web UI, never
touched by FreeCAD), `clients.freecad` stays empty.

Net: after the first apply, `_base_fctb(record)` is empty → the next diff has no
base → the just-written local file is misclassified instead of reading
`unchanged`. The second apply writes the section, a base finally exists, and it
settles.

### Fix (recommended: Option A — write the section on every pull)
In `pull_bit()`, **always** persist FreeCAD's section after a successful pull, not
only on a shape heal. Lift the `put_instance_section()` call out of the
`if chosen …` guard:

```python
# after _write_json(path, regenerated)  (sync.py:722)
healed = mapping.record_to_instance_sections(regenerated, client_item_id=basename)
client.put_instance_section(rid, healed.data, healed.client_item_id)
```

Downloading a tool *means* "FreeCAD now holds this `.fctb`" — recording that in
FreeCAD's own client section is exactly what the section is for, and it makes
download symmetric with upload. On the next sync `_base_fctb()` returns the
synced doc, so `_classify` yields `unchanged`. One apply, done.

This is lane-safe: a client section can never touch `internal`/`canonical`
(`tool_instance_records.py:172-203` rejects out-of-lane bodies). It bumps
`row.version` (`tool_instance_records.py:202`), which is **harmless to
loobric-linuxcnc** — its tool-table merge compares offsets and deliberately
ignores version/metadata bumps (`_entry_offsets`, `loobric_linuxcnc.py:273-289`).

### Alternative (Option B — local instance snapshot)
Mirror the set path: add `record_snapshots` (instance id → last-synced `.fctb`) to
`.loobric_state.json`, write it in `pull_bit`, and prefer it over `_base_fctb` in
`plan_sync`. Choose this only if you want zero server writes on a pure read. It
adds a second baseline mechanism; Option A reuses the one the server already has.

### Acceptance
- Regression test: create an instance with an empty `clients.freecad`, run
  `plan_sync` → `pull` → `plan_sync` again, assert the second plan classifies the
  bit as `unchanged` (no `push`).
- Manual: ROUNDTRIP step 4 reaches "in sync" after a **single** apply.

---

## Fix 2 — Requested members (closing the loop)

This implements the workflow in ROUNDTRIP steps 5–10: adding a tool to a
machine-bound set is a **request to load**, which the controller surfaces, the
operator fulfils by mounting, and the existing binding machinery confirms.

### Member states (derived at read time, not stored)
For a set with `machine_id` set, classify each member by its instance's binding on
that machine:

| State | Condition | Member `number` |
|-------|-----------|-----------------|
| **loaded** | the member's instance is `bound_instance_id` of some tool-table entry on `machine_id` | **observed** = that entry's `tool_number` |
| **requested** | no entry on `machine_id` is bound to the member's instance | **asserted preference** (if FreeCAD supplied one) or **unknown** |
| **pending bind** | a tool-table entry on `machine_id` plausibly matches the requested instance but is not yet bound to it (an open proposal exists) | machine `tool_number` (observed), binding unconfirmed |

`set members (18) > machine entries (17)` is **valid and in-sync** when the extra
members are `requested`/`pending bind`.

### Current gaps (with anchors)
1. Number reconciliation is **specced but unimplemented**: `TOOL_SCHEMA.md:335-339`
   says machine-bound member numbers are inherited from entries, but
   `tool_set_records.py:52-62` (`_response`) returns canonical verbatim — no
   runtime derivation, no state classification.
2. **`refresh from machine` replaces membership.** `set_members`
   (`tool_set_records.py:209-232`) overwrites the whole `members` list, so a
   refresh built from the machine's 17 entries drops the requested member.
3. **The controller never sees the set.** `loobric-linuxcnc` GETs only
   tool-table-entry records (`loobric_linuxcnc.py:647`); it has no notion of a
   requested tool.

### Server changes (loobric-server)

**S1. `reconcile_set_membership(db, set_row) -> ReconcileResult`.**
For each member of a machine-bound set, resolve `tool_record_id` (instance) →
tool-table entry on `machine_id` whose `bound_instance_id` matches.
- bound → mark `loaded`, set member `number` = entry `tool_number` with
  `source = observed:<machine>` (this is the inheritance `TOOL_SCHEMA.md:335-339`
  promises).
- not bound → mark `requested`, **preserve the member and its asserted/unknown
  number**.
- ambiguous (two members resolve to one entry, or an observed number collides with
  an asserted one) → surface to the set inbox (see S4); never silently renumber.
Use this to enrich the GET response with a per-member `state` field, and as the
engine behind refresh-from-machine.

**S2. Refresh-from-machine becomes a reconcile, not a replace.**
Either change the web UI's refresh to call a new `POST /{id}/reconcile` (runs S1
and writes back observed numbers) or redefine its `set_members` call to merge.
Invariant: **a member with no machine entry is never deleted by a machine-driven
reconcile.** The machine is authoritative for *numbers/offsets*, never for
*membership*.

**S3. Auto-propose the binding when the requested tool is mounted.**
When `POST /tool-table-entry-records/sync` (`tool_table_entry_records.py:162-235`)
**creates a new unbound entry** on a machine that has a bound set with a
`requested` member, create an `EntryProposal` (`schema.py:376-388`) naming that
member's instance, with an elevated `confidence` and `reason = "requested via set
<name>"`. Match signal, strongest first:
   1. the new entry's `tool_number` equals the member's asserted preferred number;
   2. otherwise geometry match (the existing diameter heuristic,
      `binding_v2.py:36-43`).
Extend `propose_for_entry` (`binding_v2.py:46-79`) — or add a request-aware path
called from `sync_entries` — so the request short-circuits the 0.5 threshold.
On bind, the existing `close_open_proposal_on_bind` (`binding_v2.py:82-95`)
confirms it and the member flips `requested`/`pending bind` → `loaded`.
Optional policy: auto-confirm (skip the inbox) when **both** number and geometry
agree; otherwise leave the proposal open for human confirmation.

**S4. (Optional) Set inbox** for ambiguities from S1, analogous to the binding
inbox. Not required for the happy path; required before relaxing S3's auto-confirm.

### Controller changes (loobric-linuxcnc)

**C1. Fetch the machine-bound set.** Add `GET /tool-set-records?machine_id=<id>`
alongside the existing entries fetch (`loobric_linuxcnc.py:647`).

**C2. Compute requested tools.** Build the set of bound instance ids from the
server entries already fetched (`entry.canonical.bound_instance_id.value`).
A set member is **requested** when its `tool_record_id` is not among them. (This
reuses data the client already holds; no new server-side query needed.)

**C3. Report, don't act.** Add a summary line and fold the count into the in-sync
check (`loobric_linuxcnc.py:793-794`):
```
17 tools in sync, 1 tool requested: "1/4 ball endmill" — mount it and assign pocket 18
```
Pocket 18 is shown only if the member carries an asserted preferred number. The
controller **never edits the `.tbl`** for a requested tool.

**C4. Fulfilment is the existing path.** The operator mounts the tool and adds the
`.tbl` line. On the next sync the new local tool has no server entry → the existing
decision table pushes it via **merge** (`loobric_linuxcnc.py:661-689,707-708`),
creating a new unbound entry, which triggers S3. The merge mode is essential here:
it upserts without reconciling anything away. Between mount and bind, C2 reports the
member as **pending bind** (instance now has an entry, not yet bound):
```
18 tools in sync, 1 pending bind
```

### Tool-number assignment (resolves the earlier open question)
A `requested` member's number is an **asserted preference**, or **unknown** if
FreeCAD supplies none. It is only a proposal: when the tool is mounted, the
machine's **observed** `tool_number` is authoritative and supersedes the
preference (observation > assertion). If the operator honors the preferred number,
the `tool_number` match (S3.1) is the strongest auto-bind signal; if not, geometry
match (S3.2) carries it and the member simply adopts the pocket the operator chose.

### State machine
```
            FreeCAD adds member            operator mounts + .tbl line
            to machine-bound set           → merge push creates entry
   (none) ───────────────────────▶ requested ───────────────────────▶ pending bind
                                       ▲                                     │
                                       │ refresh-from-machine                │ bind confirmed
                                       │ MUST preserve (S2)                  │ (proposal → S3)
                                       └─────────────────────────────────  loaded ◀──┘
                                                                     number becomes observed
```

### Authority rules (must hold after this fix)
1. Membership is asserted by humans/clients; the machine never owns it.
2. Numbers/offsets are observed from the machine for loaded members (S1).
3. Any machine-driven reconcile (refresh-from-machine, S1/S2) updates observed
   fields and **never deletes a member lacking an entry**.

### Glossary additions (gate before shipping any label)
`requested`, `pending bind`, and `loaded` are new user-facing status terms (web
UI, controller output, FreeCAD dialog). Add them to the glossary **before** the
strings ship — the CI vocabulary gate does not catch output nouns. See
[[check-vocabulary-before-user-facing-terms]].

### Acceptance / tests
- **Integration (the loop):** automate ROUNDTRIP steps 5–10. After step 5 the set
  reports 18 members / 1 requested while the machine has 17 entries, and this reads
  **in sync** everywhere. After mount + sync: 1 pending bind. After confirm: 18
  loaded, all clients converge.
- **Refusal:** `refresh from machine` against the 18-member / 17-entry state leaves
  18 members (the requested one survives); only observed numbers change.
- **Auto-propose:** a `/sync` that creates a new entry matching a requested
  member's preferred number yields a confirmed (or high-confidence open) proposal
  naming that instance.
- **Provenance:** a loaded member's number carries `observed:<machine>`; a
  requested member's preferred number carries `asserted:<actor>`.
