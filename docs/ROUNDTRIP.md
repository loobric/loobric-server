# Roundtrip: keeping a tool set in sync across clients

This document walks a single tool set through its whole life — from an empty
database, out to a FreeCAD programmer, and back to the machine — and defines the
behavior each client must implement for the loop to close cleanly.

The scenario deliberately includes the hard case: a programmer claims a tool
number for a tool that **does not yet physically exist on the machine**.
Getting that to settle without either side clobbering the other is the point of
the whole exercise. (Design: `MAPPING_PLAN.md`, grilled & locked 2026-07-29.)

---

## Concepts

| Thing | What it is | Source of truth |
|-------|------------|-----------------|
| **Machine** | A controller (e.g. the LinuxCNC box named `millstone`). | — |
| **Tool table entry** | One row in the machine's tool table — a `tool_number` and measured offsets. | **Machine** (observed) |
| **Tool instance** | A physical tool that exists in the shop, independent of any pocket. | Human / client (asserted) |
| **Binding** | The link between a tool table entry and the tool instance loaded into it. | Human (asserted), often via a proposal |
| **Tool set** | A named collection of tools — purely CAM-owned. Each member's `number` is CAM's durable **claim**: the T-number posted G-code will call. | Human / client (asserted) |
| **Setup** | The period during which a tool set is active on a machine (`loobric use-set`). Transitory; ended rows are the machine's history. | Operator (bind door) |

### Authority rules (these make the loop closeable)

1. **Membership and claims are asserted by humans/clients.** A programmer in
   FreeCAD may add a member to a set and claim a number for it. The machine
   never owns *which* tools belong to a set, and **observation never
   overwrites a claim** — the machine's number rides alongside (`observed`),
   it never replaces the member's `number`.
2. **Numbers and offsets on entries are observed from the machine.** The tool
   table is machine truth; the server never creates, renumbers, or deletes a
   machine-side row on its own.
3. **The server is never an interlock.** Every disagreement between claims and
   table is *displayed* (the setup view), never enforced. Individual clients
   may add local enforcement for their users; the server never gates a sync, a
   post, or a machine.
4. **Pending is information, not a task.** Nobody is obligated to drive the
   diff to zero. A one-tool job list against a thirty-tool table is a valid,
   healthy state — 29 notes, not 29 alarms.

### Claim states (for the machine's active setup, derived at read time)

| State | Meaning | Severity |
|-------|---------|----------|
| **satisfied** | Mounted, at the claimed number, identity confirmed. Reads "ok". | — |
| **requested** | Nothing on the machine holds it — a load request awaiting the operator. | attention |
| **mismounted** | Mounted + confirmed, but at a different number (CAM says T14, table has T9). | attention |
| **blocked** | A *different* confirmed tool holds the claimed number — posted G-code would run the wrong tool. | attention |
| **pending bind** | Something is mounted for the claim; identity unconfirmed. | attention |
| **unlisted / unknown tool** | Table rows the set doesn't claim (the probe; leftovers; unbound mysteries). | **notes** — never alarms |

The headline is **ready**: every claim satisfied. Notes never count against
it. `set members ≠ machine entries` is a **valid state** whenever the
difference is accounted for by the states above.

---

## The roundtrip

### Step 0 — Empty start
The database is empty. No machines, instances, sets, or setups.

### Step 1 — `loobric-linuxcnc` first sync
The controller client runs `sync`.
- The **Machine** `millstone` is created.
- **17 tool table entries** are created from the machine's `.tbl`, all **unbound**
  (we know the pockets and offsets, not yet which physical tool sits in each).

> Report: `17 tools observed, 17 unbound`

### Step 2 — Bind the tools (web UI)
The operator runs **bind new** on each entry, linking each pocket to the tool
instance physically loaded in it. The 17 entries are now bound.

### Step 3 — Create the set and make it the setup (web UI)
The operator runs **Create tool set**, names it `millstone`: the set is created
with **17 members**, each claiming the number its tool is mounted at, and
becomes the machine's **active setup** (`use-set`). Every claim is satisfied.

> State: setup `millstone` = 17 satisfied claims. Machine = 17 entries. **Ready.**

### Step 4 — `loobric-freecad` first download
The programmer launches the sync tool, downloads the set and all tools, and
presses **apply**. The `.fctl` numbers are the members' claims.

**Required behavior:** on download-apply, the client records the server's version
as its local baseline. It must **not** treat the just-written local copy as a
newer local edit.

> State: FreeCAD, server, and machine all agree on 17 tools. Ready.

### Step 5 — Programmer claims a new tool (FreeCAD + `loobric-freecad`)
Setting up a job, the programmer needs a tool the machine doesn't have yet. In
the FreeCAD tool library manager they create the toolbit, add it to the
`millstone` library **at nr 18** — the claim — and press **apply**.

This **asserts a new member with claim 18** into the set (and creates its tool
instance). The programmer can now build the Job against T18 and post G-code:
the claim is durable, and nothing has touched the machine.

> State: setup = 18 claims (17 satisfied, **1 requested**). Machine = 17
> entries. **NOT READY (1 need attention)** — a tracked request, not an error.

### Step 6 — Everyone sees the same thing
The web UI's machine card, `loobric status millstone`, and the FreeCAD sync
view all show the requested claim. Nothing nags, nothing blocks: the flags
inform.

### Step 7 — Controller surfaces the request (`loobric-linuxcnc`)
The controller client's scheduled `sync` reads the setup view:

> Report: `17 tools in sync, 1 tool requested: "<name>" (<id>) - mount it and
> assign pocket 18`

It does **not** alter the `.tbl` and does **not** drop the request.

### Step 8 — Operator mounts the tool, controller pushes
The operator mounts the tool at pocket 18 and adds the `.tbl` line. The next
`sync` pushes a **new unbound entry** (observed: number + offsets). Because the
active set claims 18 for the requested instance, the server opens a
**high-confidence (0.95) binding proposal** naming it. (The bridge fires in
BOTH orderings: entry-then-claim and claim-then-entry — a claim asserted after
the tool was already mounted proposes immediately, not at the next push.)

> Report: `17 tools in sync, 1 pending bind`

### Step 9 — Confirm the binding (any bind-door credential)
The operator (or the programmer — MAPPING_PLAN §10 Q2) confirms the proposal.
Entry 18 is bound; the claim flips to **satisfied**: claim 18 (asserted, still
untouched), observed 18, identity confirmed.

> Report everywhere: `Ready (millstone) - 18 tools in sync.`

### Step 10 — FreeCAD catches up
The programmer's next sync pulls the now-satisfied member. Its `.fctl` nr is
**still the claim (18)** — the pull never rewrites a claim with an
observation. Nothing to push; the posted G-code was right all along.

**The loop is closed.** The tool travelled FreeCAD → set (as a claim) →
operator → machine (as an observed entry) → binding, and every client
converges with no side clobbering another's change.

---

## The detour: mismount (steps 8b–10b)

Suppose pocket 18's retention knob is damaged, so the operator mounts the tool
at **T9** instead and binds it there.

> State: **mismounted** — claim 18 (asserted), observed 9. Every surface shows
> both numbers. The posted G-code still calls T18, which is exactly why this
> line needs attention.

Two honest resolutions, both through normal channels:

- **(a) Operator remounts at 18.** The next sync moves the binding; claim ==
  observed; **satisfied**. Zero writes anywhere else.
- **(b) Programmer concedes.** In FreeCAD they renumber the library entry to
  9 — an *explicit edit*, never the sync's — repost the Job, and apply. The
  push re-asserts claim 9; claim == observed; **satisfied**.

The sync itself never launders 18 into 9: a pulled `.fctl` keeps the claim.

## The crib shop: switching setups

A shop that sets the machine up per job keeps several sets. Switching is one
operator act:

```
loobric use-set millstone flange-job
```

The previous setup **ends** (its row survives — `loobric setup-history
millstone` answers "what ran when, started by whom"). Nothing else changes:
every binding, entry, member, and claim is exactly as it was. The view flips
instantly: the new set's claims classify against the same machine truth, last
job's still-mounted tools become **notes** (unlisted), and the machine reads
ready the moment the new claims are satisfied. The permanently-mounted probe
pends as a note forever — honestly, and harmlessly.

## Why this closes the loop

The earlier designs could not settle because:

- membership was treated as observed from the machine, so refresh deleted the
  programmer's new tool (fixed by authority rule 1);
- there was no representation for "in the library but not yet on the machine"
  (fixed by the `requested` claim state);
- and the sync **overwrote asserted numbers with observations** — the claim
  CAM programmed against was laundered away on every round trip, so the one
  contract that matters (the G-code's T-number) was connected to nothing
  durable (fixed by MAPPING_PLAN §5.1: claims are durable; observation rides
  alongside; `/refresh` — which persisted observations into claims — is gone).
