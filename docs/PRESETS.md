# Cutting Data Presets

**Status: ratified.** Grilled with the founder 2026-08-16; supersedes the
interim principles stated on Epic #12. Vocabulary in
`UBIQUITOUS_LANGUAGE.md`; schema context in `TOOL_SCHEMA.md` §7.9.

## 1. What a preset is

A **cutting data preset** ("preset") is a feeds-and-speeds
**recommendation with a source — never a fact about the tool.**

That one sentence carries the whole design. A tool's diameter has a truth,
so measured wins over nominal and differences are marked. Feeds and speeds
have no truth: FreeCAD's conservative hobbyist chipload and a
manufacturer's production-aggressive chart for the same tool and material
are both *correct in their contexts*. Any design that makes the server pick
a winner answers a question that has no answer.

So the server doesn't. Canonical `presets` is a **derived, normalized
union** of source-preserved contributions:

- Every entry keeps its **origin** (who recommends this) forever.
- Nothing reconciles. Identical values from two origins are
  **corroboration**, kept as two entries — the display layer may collapse
  them visually, the data never does.
- The union is materialized with source `derived:preset-union`, exactly
  like `usage.hours` from the usage ledger. No door writes it directly;
  asserting or observing `presets` is a 400.

## 2. Normal form (`preset_schema: 1`)

Engineering values only — the G5 rule (grill 2026-06-09) unchanged:

| field | meaning | notes |
|---|---|---|
| `vc` | surface speed | `{value, unit}`, e.g. m/min, sfm |
| `fz` | chipload per tooth | `{value, unit}`, e.g. mm, in |
| `ratio` | vertical-feed ratio | `{value}` |
| `material` | as the source stated it | `{name, uuid?}` **verbatim** |
| `op_type` | ratified operation taxonomy | optional; see §4 |
| `extras` | verbatim key-value bag | non-comparable **by design** |

**Raw feed and RPM are never persisted** — they are functions of tool
diameter and machine, resolved by the CAM at use time. Easy to derive from
engineering values; lossy to reverse.

The `extras` bag preserves everything else the source states (coolant,
engagement, ramp angle, DOC/WOC…) without pretending it's comparable
across sources. The five core fields are the only comparable surface.

**Floor:** an entry needs material + at least ONE of vc/fz/ratio. Below
the floor a contribution is refused with a fixable message; a client
preset that can't translate stays in its client section (lossless
round-trip is unchanged) and is simply absent from the union — an honest
gap, like the silhouette's DIA+OAL floor.

## 3. Identity, lifecycle, doors

**Identity is `(origin, label)`.** The label is the per-origin name
("Aggressive", "6061 profiling") — so one origin can carry conservative
*and* aggressive variants for the same material and operation, which real
preset lists do.

**`origin` is the recommender; the provenance actor is the transcriber** —
the same split the manufacturer-QA door uses. A human typing Harvey's
chart contributes `origin: "manufacturer"` and the entry is stamped
`asserted:human@web`; an agent transcribing the same chart stamps
`asserted:<agent>@mcp`. Who vouches for the numbers and who typed them are
different facts, and both are kept.

**Replace-own:** a re-contribution matching an existing `(origin, label)`
supersedes it (audited). That is how a client's re-sync updates its
entries and how anyone corrects a typo. **Removal** is a separate
deliberate act on the **delete door** — the agent key preset
(`read sync assert`) doesn't hold it, so agents can revise their own
entries but never remove anyone's.

**Intake — the contribution door:**

```
POST /api/v1/tool-catalog-records/{id}/presets      (assert scope)
POST /api/v1/tool-instance-records/{id}/presets     (assert scope)
{ "origin": "manufacturer", "label": "6061 profiling",
  "material": {"name": "6061-T6"}, "op_type": "profiling",
  "vc": {"value": 250, "unit": "m/min"}, "fz": {"value": 0.05, "unit": "mm"},
  "extras": {"coolant": "flood"}, "machine_id": null,
  "actor": "human@web" }
```

**Clients promote their own presets** through this door as part of their
sync flow — the `.fctl` tool-number-promotion pattern. The sync door stays
pure passthrough and the server never parses a client section's native
preset shape; translation is the client author's job
(`HOWTO_BUILD_A_CLIENT.md`). Server-side importers with F&S in their
formats (e.g. Vectric) call the same door internally.

## 4. Vocabularies

**op_type is ratified, not accreted** (the status-values discipline):
`profiling, slotting, pocketing, adaptive, facing, drilling, boring,
threading, engraving, chamfering`. The contribution door 400s on unknown
values — a deliberate channel with someone present to fix it. A client
mapping its native taxonomy keeps the verbatim source string in `extras`
and omits `op_type` when unmappable.

**Materials are verbatim, normalization deferred.** Entries store
`{name, uuid?}` exactly as the source stated; listing filters group
case-insensitively by name, best-effort by design. A ratified materials
vocabulary (canonical list + per-source aliases) is its own future grill —
same posture as grade/substrate awaiting a canonical home. Deferring it
is honest now and upgradeable later without breaking a single entry.

## 5. Scope and reads

Entries live on **both** record kinds, and an optional `machine_id`
qualifies an entry to one machine ("what worked on millstone"):

- **ToolCatalogRecord** — type-level knowledge: manufacturer
  recommendations, imported library F&S.
- **ToolInstanceRecord** — this physical tool: CAM-synced, shop-proven,
  agent-contributed.

Reads:

- `canonical.presets` inline on every record — the record's **own** union.
- `GET /tool-{catalog,instance}-records/{id}/presets` — the listing, with
  filters `origin`, `material` (case-insensitive verbatim name),
  `op_type`, `machine_id`. The **instance** listing is the full union:
  its own entries plus its linked catalog type's, each marked
  `scope: "instance" | "catalog"`. That union composes at **read time** —
  catalog entries are never copied onto instances, so catalog changes
  never go stale.

Client display policy — local-only vs. all-with-source — needs no server
involvement; the origin tags carry everything a provider (D12) needs.

## 6. Slices

1. **Server (this)**: schema, contribution door, derived union, op_type
   enum, Web UI (preset section on record detail + manual entry form),
   docs, glossary. Plus the MCP `contribute_preset` tool in the next
   loobric-cli release — AI-assisted transcription of manufacturer charts.
2. **FreeCAD promotion**: the addon translates its `.fctb` presets
   (`{name, surface_speed, chipload}` → label/vc/fz) and contributes them
   during sync.

**Explicitly deferred, each its own future grill:** community library
publishing/sharing, the materials vocabulary, F&S *calculation* (the CAM
resolves; Loobric stores), and `observed:` capture of what-actually-worked
from job logs via a deterministic pipeline — the provenance gradient's
natural endgame ("this Fz survived 40 minutes in 304 stainless"
outranking every recommendation).
