# Spec labels — printed spec plates around the late-bound label system

A **spec label** is a printed *rendering of a record*: the tool's specs in
ink, for people who identify tools by reading the label, not scanning it.
It exists because real users split roughly evenly — half want the pure
late-bound sticker (scan for current truth), half want the label itself to
say what the tool is. Spec labels serve the second camp **without touching
the first**: they are a presentation layer, and every LABELS.md invariant
stands unchanged.

Design grilled & ratified 2026-08-15. Rendering validated first by a
throwaway spike (`Loobric/research/label-spike/`) printed on real stock.

## What a spec label is — and is not

- A spec label is **not a Label**. A Label is identity: a code pointing at
  a record. A spec label is a *report* of a record. The distinction is
  architectural, not visual — in the shop both are "labels", which is why
  the name keeps the word.
- A Label's QR/code is one **optional element** of a spec label. The
  QR-less spec plaque (engraved-style, attached to the tool) is a spec
  label with no code — a natural case, not a contradiction.
- Everything printed is a **snapshot at print time**. Regrind the tool,
  rebind it, renumber the table — the ink does not update; you reprint.
  The QR, when present, is the part that never goes stale.
- Printing is **read-only** (read door). It never mints labels, never
  writes anything. Printing an unlabeled record with a QR template is a
  400 naming the record ids: label first (one existing call) or pick a
  QR-less template. No auto-mint, ever — accidental prints must not
  allocate permanent codes.

## What gets printed

All values come from the **merged view** of the instance and its optional
catalog type:

- **Merge rule:** instance (measured) value wins over catalog (nominal)
  for every geometry key; absent either, the other prints; absent both,
  the element is omitted or shows `—`.
- **Marker:** a value where measured differs from nominal prints with a
  trailing `*` (`Ø5.92*` on a nominal 6mm reground tool). The scan shows
  full provenance; the ink shows the flag.
- **T#** comes from the **bound ToolTableEntry only** — THE tool number,
  the CAM↔CNC contract, unambiguous per the install-once invariant.
  Unbound tools print nothing. ToolSet member claims **never** print: a
  tool in three sets has no one true number.
- **Silhouette:** the tool image is a vector side profile **derived from
  geometry** (`shape`, DIA, OAL, LOC, shank DIA) — honestly scaled, crisp
  on 1-bit thermal stock, zero dependencies. Needs at least DIA + OAL;
  unknown shapes draw a plain profile. Recognized shape families: round
  tip (`ballend`), rounded corners (`bullnose`), pointed (`chamfer`,
  `vbit`, `drill`, `spotdrill`, `countersink`, `engraver`, `tap`),
  reverse taper (`dovetail`), stylus + ball (`probe`), blade-on-arbor
  (`slittingsaw`); probes and saws skip the flute-line hatching, and
  their missing shank/LOC values get shape-appropriate defaults instead
  of the endmill guesses. An **angle-spec'd pointed tool** (engraver,
  chamfer: `included_angle` + `tip_diameter`, no stored diameter — its
  cutting diameter is a function of depth) draws a true-angle taper to
  the tip flat, deriving the top-of-grind diameter from
  `tip + 2·LOC·tan(angle/2)` (explicit LOC required, capped at the
  shank); the spec line leads `60° · tip 0.005` instead of `Ø`, and the
  roomy table's DIA row becomes ANG. The derivation is presentation
  only — no canonical `diameter` is ever invented. Stored media is
  never parsed or embedded (deferred; see below).
- **Units:** decimal as stored, `(in)`/`(mm)` suffix where space allows
  (the smallest plaque drops it — at 5.5 pt the full spec line only fits
  compacted). No conversion, no fractions.

Printed abbreviations (**DIA/Ø, FL, LOC, OAL, T#, `*`**) are ratified
vocabulary — see `UBIQUITOUS_LANGUAGE.md`, which also pins the schema
semantics: `geometry.length` **is** overall length, and
`geometry.cutting_edge_height` **is** length of cut.

## Templates and stocks (v1: canned, fixed content)

Two templates, each a fixed element set — no positional customization, no
omit lists (missing *data* renders as omission; missing *preference* is
the export path's job):

| template | elements | stocks |
|---|---|---|
| `qr-specs` | QR + code, name, spec line (Ø·FL·LOC·OAL), T#; roomier stocks add manufacturer, DIA/FL/LOC/OAL table, silhouette | any sticker stock |
| `spec-plaque` | big T#, name, compact spec line, silhouette — **no QR, no code** | plaque stocks (and any stock) |

Stocks are the LABELS.md registry plus a small canned plaque set:

| stock | size | layout |
|---|---|---|
| `avery-5160` | 30-up US Letter | compact cell |
| `thermal-4x6` | 12-up cut-apart | compact cell |
| `thermal-4x6-wide` | 4-up cut-apart, single column of 57×32 mm | roomy cell (spec table + silhouette, same as the 57×32 roll) |
| `thermal-57x32` | 57×32 mm roll | roomy cell |
| `plaque-38x19` | 38×19 mm, one per page | plaque |
| `plaque-50x25` | 50×25 mm, one per page | plaque |
| `plaque-25x25` | 25×25 mm, one per page | plaque |

> Plaque sizes are **provisional** — chosen from the spike, pending blank
> dimensions from the users who requested plaques. They are registry data;
> changing them is not a schema event.

The plain QR-only sticker is not a spec-label template: that artifact is a
*Label* print and stays on `POST /api/v1/labels/sheet`.

## The API

    POST /api/v1/spec-labels/sheet          (read door)
    {
      "record_ids": ["…", …],               // ToolInstanceRecords, owned
      "template":  "qr-specs" | "spec-plaque",
      "stock":     "avery-5160" | … ,
      "start_at":  0,                        // grid position, like labels/sheet
      "format":    "pdf" | "json" | "csv",   // default pdf
      "labels":    {"<record_id>": "<label_id>", …}   // optional override
    }

- `format=pdf` → the sheet, print at **100% scale**, same rules as labels.
- `format=json` / `csv` → the **export escape hatch**: the fully resolved
  print data (code, URL, merged spec fields, T#, marker flags) for users
  who feed Brother/NiceLabel/ZPL or any bring-your-own-layout tool. This
  is the v1 answer to "customize the layout and contents".
- QR templates: every record must be labeled; unlabeled ids → 400 listing
  them. A record with several labels prints its **newest active label**,
  overridable per record via `labels`.
- Entity scope v1: tool-instance records only; the request schema stays
  entity-generic so catalog prints can arrive later as an addition.
- Cross-account access is 404, never 403 (SECURITY_ASSUMPTIONS.md #8).

## Web UI

The Tools tab grows a **Print spec labels…** flow: select tools, pick
template + stock (+ start-at), print. The 400-on-unlabeled surfaces as an
inline "these tools have no label yet — label them first?" prompt that
mints via the normal label call **on explicit confirmation** (a user act,
not a printing side effect), then retries.

## Deferred, deliberately

Declarative custom templates; user-defined stock dimensions; per-print
omit lists; catalog-record prints (drawer-slot plaques); embedding stored
raster media (needs Pillow; dithers on thermal); fractional-inch display;
stale-print indicators; auto-mint on print. Each layers on without schema
or API breakage; none ships until real users outgrow v1.
