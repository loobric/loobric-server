# How-to: Build a CAM tool set from your machine's tools

## Goal

Your machine already has a tool table. You want those same tools in your CAM
tool set so you can program against them, without re-entering anything by hand.
This guide takes you from "the tools exist on the machine" to "the tools are a
CAM tool set linked to the machine."

Direction: **control → CAM**.

Throughout, "control client" means the integration that syncs a CNC control's
tool table up to the server, and "CAM client" means the integration that
manages a CAM tool set. (Reference implementations: loobric-linuxcnc and
loobric-freecad. The steps assume any control and CAM client behave the same
way.)

## Before you start

- A running Loobric Core server and a logged-in `loobric`. See
  [QUICK_START.md](QUICK_START.md) and [CLI.md](https://github.com/loobric/loobric-cli/blob/master/docs/CLI.md).
- A control client configured against this server and pointed at your machine.
- A CAM client configured against the same server.
- The control client has run at least once, so the machine's tool table has
  synced up.

## Steps

### 1. Let the control client sync the tool table up

Nothing to type. When the control client runs, each row in the machine's tool
table becomes a **tool-table entry** on the server. These entries arrive
**unbound**: the server has the entry and its measured values, but no shared
tool record stands behind it yet.

### 2. Find the machine

```bash
loobric list-machines
```

Note the machine id (or a unique prefix — short prefixes work like a git short
SHA).

### 3. See what the machine reported

```bash
loobric tool-table <machine>
```

Every entry shows as unbound:

```
T1: 6mm flat endmill  ⌀6.00  [unbound]
T2: 1/4" downcut      ⌀6.35  [unbound]
T3: 3mm ball          ⌀3.00  [unbound]
```

### 4. Create a tool record from each entry

`create-record` mints a brand-new tool record from an entry's observed values
and binds the entry to it, in one step. Do this for each tool you want in CAM.

```bash
loobric create-record <machine> 1 --name "6mm flat endmill"
loobric create-record <machine> 2 --name "1/4 downcut"
loobric create-record <machine> 3 --name "3mm ball"
```

`--name` defaults to the entry's description, so you can omit it.

A note on T-numbers: the tool number stays on the **machine entry**, not on the
record. A tool record is the machine-independent description of a tool; its
position is a property of the tool-table entry, never of the record itself. (See
[TOOL_SCHEMA.md](TOOL_SCHEMA.md) §7.)

### 5. Confirm the records exist and the entries are bound

```bash
loobric list-tools
loobric tool-table <machine>
```

`list-tools` shows one record per tool. The table now reads `bound -> <record>`
for each entry you turned into a record.

### 6. Import the records into your CAM tool set

This is the CAM client's job, not `loobric`. Point your CAM client at the
server and import (or refresh). It reads the tool records and represents them as
a tool set — that representation lives in the set's own client section, so the
CAM library is just *one client's view* of a shared tool set (see
[TOOL_SCHEMA.md](TOOL_SCHEMA.md) §7.4). Each imported tool keeps a link back to
its server record.

### 7. Link the set to the machine

A tool set built from a specific machine should record where it came from. A
tool set carries an optional `machine_id` link to the Machine it belongs to.
**When a set is linked to a machine, its member numbers are inherited from the
machine's tool-table entries** — so the set and the control agree on T-numbers
without any extra step.

Your CAM client may set this link when it creates the set. If not, `loobric`
links it for you:

```bash
# find the set id
loobric list-tool-sets

# link the set to the machine
loobric link-machine <set> <machine>
```

### 8. Confirm the result

```bash
loobric tool-table <machine>   # every entry reads bound -> <record>
loobric list-tool-sets         # the set is present and machine-linked
```

Because the set is linked to the machine, its member numbers follow the
machine's tool-table entries. In your CAM client, the imported tools should
match the machine's tools, T-number for T-number.

## Confirm success

- `loobric tool-table <machine>` — every entry you turned into a record reads
  `bound -> <record>`.
- `loobric list-tools` — one record per machine tool.
- `loobric list-tool-sets` — the CAM tool set shows up, machine-linked, with the
  expected member count.
- In your CAM client, the imported tool set matches the machine's tools.

## Related

- [CLI.md](https://github.com/loobric/loobric-cli/blob/master/docs/CLI.md) — every command used here, plus the touch-off-to-bound
  walkthrough.
- [HOWTO_MATCH_MACHINE_AND_CAM_TOOLS.md](HOWTO_MATCH_MACHINE_AND_CAM_TOOLS.md)
  — when the machine and the CAM tool set were built separately and need linking.
- **Coming soon:** the reverse direction — push a CAM tool set down to a machine
  (CAM → control).
