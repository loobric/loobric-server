# Roundtrip: keeping a tool set in sync across clients

This document walks a single tool set through its whole life — from an empty
database, out to a FreeCAD programmer, and back to the machine — and defines the
behavior each client must implement for the loop to close cleanly.

The scenario deliberately includes the hard case: a programmer adds a tool that
**does not yet physically exist on the machine**. Getting that to settle without
either side clobbering the other is the point of the whole exercise.

---

## Concepts

| Thing | What it is | Source of truth |
|-------|------------|-----------------|
| **Machine** | A controller (e.g. the LinuxCNC box named `millstone`). | — |
| **Tool table entry** | One row in the machine's tool table — a pocket with a `tool_number` and measured offsets. | **Machine** (observed) |
| **Tool instance** | A physical tool that exists in the shop, independent of any pocket. | Human / client (asserted) |
| **Binding** | The link between a tool table entry (a pocket) and the tool instance loaded into it. | Human (asserted), often via a proposal |
| **Tool set** | A named collection of tools (e.g. `millstone`). May be **bound** to a machine. Its `members` reference tool instances. | Human / client (asserted) |

### Authority rules (these make the loop closeable)

1. **Membership is asserted by humans/clients.** A programmer in FreeCAD may add
   a member to a set. The machine never owns *which* tools belong to a set.
2. **Numbers and offsets are observed from the machine.** For a member that is
   loaded, its `tool_number` and offsets are inherited from the machine's entry.
3. **`refresh from machine` reconciles observed fields only.** It updates numbers
   and offsets for loaded members. **It never deletes a member that has no machine
   entry yet** — that member is a pending request, not stale data.

### Member states (for a set bound to a machine)

A set can legitimately have *more members than the machine has tool table
entries*. The extra members are requests in flight, not an error.

| State | Meaning | How it shows up |
|-------|---------|-----------------|
| **loaded** | Member has a bound machine entry. Number/offsets are observed. | "in sync" |
| **requested** | Member asserted into the set; the machine has no entry for it. A load request awaiting the operator. | "1 tool requested" |
| **pending bind** | Operator mounted the tool; the machine now reports an entry, but it isn't bound to the instance yet. | "1 pending bind" |

`set members (18) ≠ machine entries (17)` is a **valid, in-sync state** whenever
the difference is accounted for by `requested` / `pending bind` members.

---

## The roundtrip

### Step 0 — Empty start
The database is empty. No machines, instances, or sets.

### Step 1 — `loobric-linuxcnc` first sync
The controller client runs `sync`.
- The **Machine** `millstone` is created.
- **17 tool table entries** are created from the machine's `.tbl`, all **unbound**
  (we know the pockets and offsets, not yet which physical tool sits in each).

> Report: `17 tools observed, 17 unbound`

### Step 2 — Bind the tools (web UI)
The operator runs **bind new** on each entry, linking each pocket to the tool
instance physically loaded in it. The 17 entries are now bound.

### Step 3 — Create the set (web UI)
The operator runs **Create tool set**, names it `millstone`, and binds it to the
machine. The set is created with **17 members**, one per bound entry. Because the
set is machine-bound, each member's number is **observed** from the machine.

> State: set `millstone` = 17 loaded members. Machine = 17 entries. In sync.

### Step 4 — `loobric-freecad` first download
The programmer launches the sync tool. It fetches from the server and shows set
`millstone` with 17 tools, all not yet present locally. The operator chooses to
download the set and all tools, then presses **apply**.

> Expectation: after apply, everything reports **in sync**.

**Required behavior:** on download-apply, the client records the server's version
as its local baseline. It must **not** treat the just-written local copy as a
newer local edit. (Previously this produced a phantom "local is newer — upload"
prompt that forced a second apply. That is a bug, not the intended flow.)

> State: FreeCAD, server, and machine all agree on 17 loaded tools. In sync.

### Step 5 — Programmer needs a new tool (FreeCAD + `loobric-freecad`)
Setting up a job, the programmer needs a tool the machine doesn't have yet. In the
FreeCAD tool library manager they import or create a toolbit and add it to the
`millstone` library. Back in the sync tool they press **apply**.

This **asserts a new member** into the set (and creates its tool instance). Because
the machine has no entry for it, the member is uploaded in the **requested** state
— the programmer is, in effect, requesting that this tool be loaded on the machine.

> State: set `millstone` = 18 members (17 loaded, **1 requested**). Machine = 17
> entries. This is in sync — the difference is one tracked request.

### Step 6 — Operator sees the request (web UI)
The operator views `millstone` and sees **18 members: 17 loaded, 1 requested**, and
the Machine with 17 entries. The UI presents the requested tool as a pending load,
not as a mismatch to "fix".

> `refresh from machine` here changes nothing: it reconciles the 17 loaded members
> and **leaves the requested member intact**.

### Step 7 — Controller surfaces the request (`loobric-linuxcnc`)
The controller client runs its scheduled `sync`. It pulls the machine-bound set,
compares the 18 members against the 17 local entries, and finds one member with no
entry — a request.

> Report: `17 tools in sync, 1 tool requested: "<tool name>" — mount it and assign a pocket`

It does **not** alter the `.tbl` on its own and does **not** drop the request.

### Step 8 — Operator mounts the tool, controller reconciles (machine + `loobric-linuxcnc`)
The operator physically mounts the requested tool and assigns it a pocket (e.g.
tool number 18), adding the line to the `.tbl`. On the next `sync`, the controller
pushes a **new tool table entry** (observed: number + offsets). The machine now has
18 entries — but the new one is **unbound**.

Because the set member already names the requested instance, the client opens a
**high-confidence binding proposal** linking the new entry to that instance.

> Report: `18 tools in sync, 1 pending bind`

### Step 9 — Confirm the binding (web UI, or automatic)
The operator confirms the binding proposal (or it auto-resolves given its
confidence). Entry 18 is now bound to the requested instance; the member flips from
**requested** to **loaded**, and its number becomes observed (18).

> Report everywhere: `millstone — 18 tools, in sync. Machine — 18 tools.`

### Step 10 — FreeCAD catches up (`loobric-freecad`)
The programmer's next sync pulls the now-loaded member, which gained an observed
tool number. Nothing to push.

> Report: `18 tools, in sync`

**The loop is closed.** The tool travelled FreeCAD → set (as a request) → operator
→ machine (as an observed entry) → binding, and every client converges on 18 loaded
tools with no side clobbering another's change.

---

## Why this closes the loop

The earlier design could not settle because:

- A machine-bound set treated **membership as observed from the machine**, so
  `refresh from machine` deleted any member the machine didn't have — wiping the
  programmer's new tool.
- There was **no representation** for "in the library but not yet on the machine,"
  so clients kept trying to force `set count == machine count`, pumping in opposite
  directions (web shrinking the set to 17, FreeCAD re-uploading to 18) and never
  creating the one thing that would reconcile them: a machine tool table entry.

The fix is the three authority rules plus the `requested` / `pending bind` states:

1. Membership is asserted, never overwritten by the machine.
2. A member with no machine entry is a **request to load**, surfaced to the
   operator — not stale data to delete.
3. The request rides the existing binding mechanism: mount → observed entry →
   proposal → bound → loaded.
