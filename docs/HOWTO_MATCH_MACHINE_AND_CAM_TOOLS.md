# How-to: Match a machine and a CAM tool set you built separately

## Goal

You have a machine tool table **and** a CAM tool set, built independently.
Same shop, same physical tools, but the server doesn't yet know which tool-table
entry corresponds to which CAM tool. This guide links them.

This is an **identity** question: "is this tool-table entry the same physical tool
as this record?" It is **not** a data merge. If the two sides hold different
geometry for what turns out to be the same tool, binding changes neither side's
numbers or measurements. Settling identity and settling a data difference are
separate concerns; this guide settles identity (and, at the end, set
numbering) only. See [the note below](#a-note-on-data-differences).

Direction: **both sides already populated**.

"Control client" means the integration that syncs a CNC control's tool table;
"CAM client" means the integration that manages a CAM tool set. (Reference
implementations: loobric-linuxcnc and loobric-freecad. The steps assume any
control and CAM client behave the same way.)

## Before you start

- Server running, logged in with `loobric` (see [CLI.md](https://github.com/loobric/loobric-cli/blob/master/docs/CLI.md)).
- The control client has synced the machine's tool table up — entries exist.
- The CAM client has synced its tools up — tool records and a tool set exist.
  Confirm with `loobric list-tools` and `loobric list-tool-sets`.

## Steps

### 1. Review the inbox

When a machine reports a tool the server doesn't recognize, the server may
propose a matching record. Proposals collect in the inbox.

```bash
loobric pending
```

```
  ID: 4f2a1c9b
  Machine entry: T2
  Proposed match: 1/4 in downcut, 2-flute
  Confidence: 88% - same diameter and flute count
```

Each item is a scored guess about identity. Resolving one overwrites nothing on
either side.

### 2. Confirm or reject each proposal

```bash
loobric resolve 4f2a confirm   # same tool: link the entry to the record
loobric resolve 7c10 reject    # different tools: drop the suggestion
```

- `confirm` = **same physical tool**. The entry binds to the record; future
  changes route between them. Both keep their own data.
- `reject` = **different tools**. The suggestion is dropped permanently; the
  entry stays unbound and keeps syncing.

If unsure, `reject`: a rejected pair can still be linked by hand later (step 3),
while a wrong `confirm` is currently hard to undo.

### 3. Bind the entries that had no proposal

The inbox only holds cases the server could guess at. Some entries will have no
proposal — a match the server couldn't see. Find them and link by hand.

```bash
loobric tool-table <machine>   # which entries are still unbound
loobric list-tools             # the record id to link to
loobric bind <machine> 5 <record>
```

Binding never overwrites either side; it routes future changes between the entry
and the record.

### 4. Link the set so it inherits the machine's numbering

Identity is now settled per tool. The last step lines up the CAM set's member
numbers with the machine's tool numbers, so the set and the control agree on
T-numbers.

**Link the set to the machine.** When a set is machine-linked, its member
numbers are inherited from the machine's tool-table entries — the machine is
observed fact, the set conforms. There is no separate step: linking *is* the
alignment.

```bash
loobric list-tool-sets               # find the set id
loobric link-machine <set> <machine> # link it to the machine
```

A set member with no matching tool-table entry keeps its own asserted number —
nothing on the machine to inherit from. Resolve those by binding the
corresponding entry (step 3) so the machine reports it.

### 5. Confirm the result

```bash
loobric tool-table <machine>   # entries you linked read bound -> <record>
loobric pending                # empty, or only items you deliberately left
loobric list-tool-sets         # the set is present and machine-linked
```

### A note on data differences

Binding and linking answer **identity** and **numbering**. They do not merge
**measurements**. If the machine measured a 6.35 mm diameter and the CAM record
says 6.30 mm for the same tool, binding leaves both values exactly as they were.

A data difference is a separate concern, decided through the observe/assert
doors ([TOOL_SCHEMA.md](TOOL_SCHEMA.md) §5), not through binding. Don't expect a
bind to "fix" a geometry mismatch — it answers "same tool?", nothing more.

## Confirm success

- `loobric tool-table <machine>` — every entry you intended to link reads
  `bound -> <record>`.
- `loobric pending` — empty, or only items you deliberately left.
- `loobric list-tool-sets` — the set is present and machine-linked.

## Related

- [CLI.md](https://github.com/loobric/loobric-cli/blob/master/docs/CLI.md) — `pending`, `resolve`, `bind`, `tool-table`, `list-tools`,
  `link-machine`.
- [HOWTO_BUILD_CAM_SET_FROM_MACHINE.md](HOWTO_BUILD_CAM_SET_FROM_MACHINE.md)
  — when the machine has the tools and CAM is empty (control → CAM).
- [TOOL_SCHEMA.md](TOOL_SCHEMA.md) §8 — install-once and number-inheritance
  invariants.
