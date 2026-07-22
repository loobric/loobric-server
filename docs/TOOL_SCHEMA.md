# Loobric Tool Schema

This document is the **authoritative contract** for how tool data is structured
in Loobric. It is the reference for building new clients (FreeCAD, LinuxCNC,
Fusion, …) and writing tests for them. The Pydantic models in
`loobric_server/contract/` are the machine-readable form of everything below; they
validate the wire on the server **and** drive the client conformance test
suite. If this document and the models disagree, the models win and this
document is the bug.

> Status: design approved 2026-06-15. v2 is pre-release; there is **no
> migration** — the old flat schema is replaced wholesale.

---

## 1. The model in one paragraph

Every tool-domain entity is built from **three sections with identical shape**:

- **`internal`** — server-owned plumbing (`id`, `version`, timestamps).
  Read-only to every client.
- **`canonical`** — the *agreed truth* about the entity. **Every canonical
  field carries its provenance**: who said it and how (`observed`, `asserted`,
  or `unknown`), written inline as `{ "value": …, "source": … }`.
- **`clients`** — a map of per-client sections, each a fixed **envelope**
  (`client`, `client_version`, `client_item_id`, server-stamped timestamps)
  plus an opaque **`data`** payload the client owns completely.

A routine client **sync** writes **only its own client section** and is
physically forbidden from touching `internal` or `canonical` (the server
hard-rejects it). Canonical only changes through two narrow, deliberate doors:
machines **observe** the few fields they can measure; humans/CAM **assert**
everything else through an explicit, audited operation. A field nobody has
stated is honestly **`unknown`** — never defaulted to a plausible guess.

The whole design exists to make one class of bug *impossible*: a single client
silently fabricating shared truth (the "every imported tool became an endmill"
failure). Provenance makes a guess inexpressible.

---

## 2. Why (the principles)

1. **Observation is not assertion.** A machine can only *observe* what it
   physically measures — a tool's tool number and a touched-off diameter. It
   can never know a tool is a "probe" vs an "endmill"; that is a human/CAM
   *assertion*. The schema encodes this distinction in every field's `source`.
2. **Unknown is a first-class, honest state.** The absence of an assertion is
   `unknown`, not a default. Nothing fabricates a value to fill a gap.
3. **Canonical is sticky.** Routine sync never changes it. Observations flow
   because they are facts; assertions are rare, explicit, audited acts.
4. **Uniformity is learnability.** The three-section shape and the client
   envelope are *identical across every entity*. Learn it once; it applies to
   catalog types, instances, entries, sets, and machines alike.
5. **Position belongs to the thing that has positions.** A tool number is never
   a client's private copy (that's how CAM and CNC drift apart). It is
   canonical and owned by the entity that models the position: the tool-table
   entry (`ToolTableEntry`) or the set membership (`ToolSet`).

---

## 3. Sections

### 3.1 `internal` (server-owned)

```jsonc
"internal": {
  "id": "dc6c3faf-…",        // stable public id, server-assigned
  "version": 3,              // optimistic-lock version, server-incremented
  "created_at": "2026-06-15T08:55:02Z",
  "updated_at": "2026-06-15T09:02:10Z"
}
```

Clients **read** `internal` (notably `id` for the back-reference they store on
their own side, and `version` for optimistic locking on their next write). A
client write that contains an `internal` key is rejected `400`.

### 3.2 `canonical` (provenance-tagged truth)

Every canonical leaf is a **provenance-tagged field**:

```jsonc
{ "value": 2.9972, "unit": "mm", "source": "observed:linuxcnc@millstone" }
```

- `value` — the value, or `null` when `source` is `unknown`.
- `unit` — optional, for quantities.
- `source` — one of the provenance forms in §4.

Canonical may nest (e.g. `geometry.diameter`); leaves are always tagged fields.
The set of canonical fields is **entity-specific** and defined by the
per-entity model in `loobric_server/contract/`. A client write that contains a
`canonical` key is rejected `400`; canonical changes go through the
observe/assert doors (§5).

### 3.3 `clients` (per-client sections)

A map keyed by client name. Each section:

```jsonc
"clients": {
  "freecad": {                              // <- the map KEY is the client identity
    "client_version": "0.3.1",              // client-asserted
    "client_item_id": "Probe.fctb",         // client-asserted; re-adoption fallback (§6)
    "created_at":     "2026-06-15T08:55:02Z", // SERVER-stamped
    "updated_at":     "2026-06-15T09:02:10Z", // SERVER-stamped
    "data":           { "fctb": { … } }      // OPAQUE, client-owned, lossless
  }
}
```

The client is identified by its **map key**; on write, the client name is
carried by the request path (`…/clients/{name}`), not the body. There is
deliberately **no `client` field inside the section** — a second copy of the
key could only diverge from it, the same anti-pattern we removed for tool
numbers (Principle 5).

**Envelope fields** (the contract every client section must satisfy):

| field | who sets it | meaning |
|---|---|---|
| *(map key)* | client (via path) | the client identifier — single source of truth |
| `client_version` | client | version string of the client software |
| `client_item_id` | client | the client's own stable handle for this item (re-adoption fallback) |
| `created_at` | **server** | when the server first received this client's section |
| `updated_at` | **server** | when the server last received this client's section |

The only things a client **asserts** about itself are `client_version` and
`client_item_id`. Its identity is the map key; all time is the server's.

**`data`** is opaque: the server never reads or interprets it; it round-trips
verbatim. Anything a client needs that isn't canonical lives here (e.g. the
full `.fctb` document, a raw `.tbl` line). A client may want its source's own
modified time — that goes in `data` (e.g. `data.source_modified_at`), clearly
client-claimed, never confused with the server's envelope timestamps.

Per-section versioning is **deferred**; the record-level `internal.version` is
the optimistic-lock unit for now. (A future revision may add per-section
versions if concurrent multi-client writes prove to cause false conflicts.)

---

## 4. Provenance (`source`)

```
observed:<client>@<machine>     a machine measured it (the only thing a machine may write)
asserted:<client>               a software client declared it
asserted:human@<context>        a person declared it (e.g. asserted:human@inbox)
derived:<by>                     COMPUTED from other canonical data (e.g. an
                                 assembly's gauge length from its components);
                                 recomputable and can go stale when inputs change
unknown                         nobody has stated it; value MUST be null
```

`kind(source)` is the part before `:` — `observed`, `asserted`, `derived`, or
`unknown`. `derived` is distinct because such a value is a *function of other
canonical fields*: when an input changes the value is stale and must be
recomputed — it is neither a human assertion nor a machine observation.

Rules enforced by the contract models:

- `source == "unknown"` ⇒ `value` is `null`.
- A field whose `source` kind is `observed` may only be written through the
  **observe** door, and only by a client whose declared scope permits observing
  that field.
- A field written through **assert** gets an `asserted:*` source.

**Per-field precedence** (documented per field; the structure supports any
policy): the default is *an explicit human assertion outranks a machine
observation outranks unknown*. The interesting case is nominal vs measured: a
catalog type's nominal diameter is `asserted`; an instance's measured diameter
is `observed`; they are different fields on different entities and never fight.

---

## 5. The three canonical doors

There are exactly three ways canonical changes, and **routine sync is not one
of them**:

1. **Sync** (`PUT .../clients/<name>` style write): writes only the client's
   own section. Cannot touch `internal`/`canonical`. This is the *only* thing
   most clients ever do. *(This alone makes the endmill bug impossible: a
   FreeCAD import sync physically cannot write `geometry.shape`.)*
2. **Observe**: a machine client reports a measured value for an *observable*
   canonical field (diameter, length, tool number). The server records it with
   `source = observed:<client>@<machine>`. Relatively free — it's reality.
   Gated by the client's declared scope: a machine may observe a measurement;
   it may never observe (let alone assert) a `shape`.
3. **Assert**: an explicit, audited operation declaring a canonical value
   (`shape`, a nominal dimension, a catalog-type link). Rare and deliberate.
   The FreeCAD "set the tool type on import" correction is an assert.

Enforcement is hard: a sync payload carrying `internal`/`canonical` keys, or an
observe/assert the client's scope doesn't permit, is a `400`. See §9.

---

## 6. Identity & re-adoption (resolving the client-side unknowns)

Two independent links, by design:

- **Server → client (primary).** The server owns `internal.id`. After first
  contact the client stores that id **on its own side** — e.g. FreeCAD writes
  `{"loobric_server": {"record_id": "<internal.id>", "version": …}}` into the `.fctb`
  file. This is the client's private bookkeeping, *not* part of the wire
  sections. It is how the client knows UPDATE vs CREATE next time.
- **Client → its own item (`client_item_id`, fallback).** The envelope carries
  the client's *own* stable handle (FreeCAD's `.fctb` id; a tool-number identity
  for a machine entry). When the client loses the server back-reference (FreeCAD's
  editor drops unknown keys on save — a real, observed failure), the server
  re-adopts the link by matching `client_item_id` against the section it
  already holds for that client. Never by name.

So: the server-id back-reference is the primary key the client persists
locally; `client_item_id` in the envelope is the re-adoption fallback the
server persists. Both exist; neither is guessed.

---

## 7. Entities

All five use the identical three-section shape. Only `canonical` content
differs.

### 7.1 `ToolCatalogRecord` — a catalog *type*
A reusable, shareable definition that can exist with **zero** owned instances
(a manufacturer catalog of 500 tools; you own 3). Groupable into a
`ManufacturerCatalog`. Created by catalog importers, by hand, or by clients
that have type information.

`canonical`: `name`, `manufacturer`, `product_code`, **nominal** `geometry`
(diameter, flutes, …), presets reference. Geometry here is typically
`asserted:catalog-import` or `asserted:human` — it is the published/nominal
spec, never `observed`.

### 7.2 `ToolInstanceRecord` — a *physical* tool
The syncable, installable thing. References an optional catalog type. **Binds
to at most one tool-table entry at a time** (the install-once invariant, §8).

`canonical`: `name`, `catalog_type_id` (optional, provenance-tagged —
`unknown` until someone asserts it), `status` (installed/in-drawer/…),
**measured** `geometry` (`observed` per machine). The measured diameter here is
the per-instance reality; the nominal lives on the type.

### 7.3 `ToolTableEntry` — a row of a machine's tool table
One row of a machine's tool table.

`canonical`: `tool_number` (`observed:<client>@<machine>` — THE tool number, the
CAM↔CNC contract), `bound_instance_id` (the physical tool bound to the entry;
`asserted:human@inbox` when confirmed), `offsets` (`observed`). `internal`
additionally carries `machine_id`.

### 7.4 `ToolSet` — an agnostic named collection of tools
**Not** a FreeCAD library. A `ToolSet` is a control/CAM-agnostic collection. A
FreeCAD `.fctl`, a Fusion tool library, or a shop drawer are each just *one
client's representation* of a ToolSet, living in that set's
`clients.<name>.data`.

`canonical`:
- `name`.
- `machine_id` — optional link: "this set is linked to this machine's tooling."
  Null = a general/drawer set that makes no CAM↔CNC numbering claim.
- `members` — an ordered list of `{ tool_record_id, number }`, where `number`
  is a **canonical, provenance-tagged** position. The position is unique within
  the set. When the set is `machine_id`-bound, member numbers are
  **`observed`** (inherited from the machine's tool-table entries — the machine is fact, the
  set conforms). When unbound, they are `asserted:<client>`.

The per-client library numbers that used to live in `extra.freecad.numbers` are
**promoted out** of the client section into canonical membership — a set's
numbering is shared truth, not any one client's private copy.

### 7.5 `Machine` — a controller
`canonical`: `name`, `controller_type`, `definition` (axes/spindle/units/post).

### 7.6 Composition (ISO 13399)

A real CNC tool is not one object — it is a **stack of items that couple
through standardized interfaces** (ISO 13399): a cutting item (the edge), a
tool item (the body), adaptive items (collets, extensions), and an assembly
item (the holder / spindle interface, e.g. HSK63, BT40, Capto C6). The
*assembly* — the stack — is the thing that actually installs in the machine
and the thing CAM reasons about, because its **gauge/functional length is
emergent from the whole stack** and exists on no single component.

This is modeled with **composition as a canonical capability of a record**, not
a separate entity — keeping the two-record model and uniform sections:

- A record carries an optional **`item_type`** (`cutting_item` | `tool_item` |
  `adaptive_item` | `assembly_item` | `assembly`) — its ISO role, *asserted*,
  never inferred.
- A record that is an assembly carries an ordered **`components`** field whose
  value is a list of `{ component_id, role, connection }` — each a reference to
  another record (catalog→catalog parts; instance→instance parts), the ISO role
  it plays, and a flexible `connection` field for the coupling/interface, gauge
  offset, and stick-out. `components` is itself a provenance-tagged Field (who
  asserted this composition).
- Assembly **geometry is emergent**: `cutting_diameter` comes from the cutting
  item; `gauge_length` is typically `derived:components` (computed from the
  stack) — or `observed:presetter@<id>` when measured on a tool presetter (the
  provenance model already handles that with nothing new).

Both flavors exist: a **`ToolCatalogRecord`** with components is a reusable
assembly *recipe*; a **`ToolInstanceRecord`** with components is a *physical
built stack* — and that instance is what a `ToolTableEntry` binds. A lone tool
is just a degenerate assembly of one (no `components`).

See `tests/fixtures/schema/tool_assembly_record.json` for a worked example.

> **Scope:** the schema *allows* composition (the hooks above are in the
> contract models and validated). Assembly geometry computation, ISO connection
> compatibility checking, and assembly CRUD/inbox flows are **not yet
> implemented** — they layer on without further schema change.

### 7.7 Media (3D models, drawings, images)

A tool has files attached to it: a **3D model** (a STEP solid — the manufacturer's
authoritative shape), **2D drawings**, **product images**, **logos**. These are
*shared truth about the tool*, identical for every consumer (FreeCAD, the web UI,
a future Fusion client) — so they are **canonical**, not a client's private copy.
Putting a model in `clients.freecad.data` would both mislabel it as FreeCAD's and
force every other client to keep a duplicate — the same anti-pattern Principle 5
removes for tool numbers.

Media is one canonical, provenance-tagged **`media`** Field whose `value` is a
list of **MediaRef** descriptors — modeled exactly like `components` (one Field,
a validated list):

```jsonc
"media": {
  "value": [
    { "role": "model_3d", "ref": "sha256:9f86d0…", "content_type": "model/step",
      "filename": "6676918-KH-stp.stp", "size": 94773 },
    { "role": "model_3d_basic", "ref": "sha256:1b40…", "content_type": "model/step", … },
    { "role": "image",    "ref": "sha256:a3f1…", "content_type": "image/png", … }
  ],
  "source": "asserted:catalog-import"        // server-stamped, like any canonical field
}
```

`role` ∈ {`model_3d`, `model_3d_basic`, `drawing_2d`, `image`, `icon`, `logo`,
`document`}. The same nominal-vs-measured split as geometry applies: a **catalog
type** carries the manufacturer's nominal model (`asserted:catalog-import`); a
**physical instance** may later carry an as-built/scanned model
(`observed:presetter@…`) — different provenance, same field.

**Reference, not inline bytes.** The canonical record holds only the small,
shareable, verifiable **reference** (`ref` = the content-addressed blob key); the
bytes live in a separate blob store (`loobric_server.media_store`) and are served
out-of-band:

```
POST   .../{record_id}/media        multipart upload (file + role) → stores blob, asserts the ref
GET    .../{record_id}/media/{ref}  streams the bytes
DELETE .../{record_id}/media/{ref}  drops the reference (blob retained; GC deferred)
```

This keeps multi-MB models out of every record fetch, the changes feed, and
backups — only the key travels in the JSON.

**The server never parses media.** It stores and streams bytes; it does not read
a STEP solid (that would mean dragging a CAD kernel into the server). Rendering is
the consumer's job — the web UI renders STEP client-side via a WASM viewer
(e.g. online-3d-viewer / occt-import-js), FreeCAD uses the file directly. This is
the same discipline as importing: *interpret only what the canonical model can
hold; carry everything else through verbatim.*

> **Scope / deferred:** the reference, blob store, upload/serve/delete endpoints,
> and provenance are implemented and validated. **Blob garbage-collection** (a
> deleted reference leaves its content-addressed bytes in place) and **including
> blob bytes in `backup-export`** (the backup carries the references, not the
> bytes — back up the blob directory alongside the database) are deliberately
> deferred. Per-item media provenance (each MediaRef its own `source`) is also
> deferred — today the whole set shares one `source`, like `components`.

---

## 8. Invariants & reconciliation

- **Install-once.** A `ToolInstanceRecord` is bound to **at most one**
  `ToolTableEntry` at a time, globally (a physical tool is in one place).
  Enforced by a **unique index** on `ToolTableEntry.canonical.bound_instance_id`
  (NULLs exempt → many unbound entries fine) as the hard guarantee, **plus** a
  bind endpoint that returns a friendly `409` ("Probe is installed in *millstone*
  entry T1 — unbind there first, or use *move*") and offers an atomic **move**
  (unbind old + bind new).
- **`ToolRecord` is an instance**, not a type. One `ToolInstanceRecord` per
  physical tool. Catalog types are separate, referenced, and may have zero
  instances.
- **Transitive install-once (deferred).** When an *assembly* instance is
  installed, its component instances are occupied by it; a component instance
  cannot be live in two installed assemblies at once. The schema permits this
  (composition is explicit); the enforcement lands with the assembly work.
- **Number reconciliation.** For a `machine_id`-bound `ToolSet`, the machine's
  tool-table entries are the source of truth (observation > assertion): member
  numbers are inherited (`number = tool_number`). Cases the server cannot infer —
  a set member with no machine entry, or two members claiming one entry — are surfaced to a
  human (like the binding inbox), never silently renumbered.

---

## 9. Enforcement (lane discipline)

The server validates every client write against the contract models:

- A sync write that contains an `internal` or `canonical` key → **`400`** with
  a message naming the offending lane.
- An observe/assert for a field the client's declared **scope** does not permit
  (a machine asserting `shape`; a CAM client observing a measurement) → **`400`**.
- Canonical changes are only accepted through the observe/assert endpoints, are
  audited, and stamp the appropriate `source`.

The point: "routine sync cannot mutate canonical" is not a convention a client
author must remember — it is a wall they hit loudly the first time.

---

## 10. The client contract & how to build/test a new client

**Single source of truth.** `loobric_server/contract/` defines Pydantic models for the
sections, the envelope, the provenance-tagged field, and each entity's
canonical shape. The **server validates the wire** with these models, and the
**same models** + a shared conformance suite + the golden fixtures in
`tests/fixtures/schema/` are what a client repo runs to prove conformance.

**Client scope manifest.** Every client declares what it manages — which
entities it writes, and which canonical fields (if any) it may `observe` or
`assert`. Examples:

- **linuxcnc**: writes `ToolTableEntry` and `ToolInstanceRecord` sections;
  may **observe** `tool_number`, `offsets.*`, instance `geometry.diameter`;
  may **assert** nothing; never creates `ToolCatalogRecord`.
- **freecad**: writes `ToolInstanceRecord` and `ToolSet` sections; may
  **assert** `geometry.shape`, `catalog_type_id`; may create `ToolCatalogRecord`.
- **catalog-import**: writes/creates `ToolCatalogRecord` only; **asserts**
  nominal geometry; never touches instances or entries.

**To build a new client (e.g. Fusion):**
1. Pick your scope (entities + observe/assert fields); declare it.
2. Build your client section: the envelope (`client`, `client_version`,
   `client_item_id`) + your opaque `data`. Never send `internal`/`canonical`.
3. To claim a canonical fact, call observe (machine measurements) or assert
   (deliberate declarations) — only for fields your scope allows.
4. Store the server's `internal.id` on your side for UPDATE-vs-CREATE; send
   your `client_item_id` for re-adoption.
5. Run the conformance suite against a `FakeServer` (the freecad/linuxcnc repos
   already have the harness): it proves your envelope is valid, you stay in
   your lane, your provenance is well-formed, and your declared scope holds.

A generated JSON Schema (from these models) will be published when the first
non-Python client appears.

---

## 11. Worked examples

See `tests/fixtures/schema/*.json` — those files are simultaneously the
canonical examples, the documentation, and the conformance test data. They
cover a catalog record, a physical instance (the Probe), a machine tool-table entry,
and a machine-bound tool set. They are validated by
`tests/contract/test_schema_contract.py` on every test run, so they cannot
drift from the models.
