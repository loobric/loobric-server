# Labels — physical stickers, public spec pages, and the resolver

A **label** is a physical QR/short-code sticker pointing at one record: the
link between the endmill in the drawer and its digital twin. Scanning (or
typing) a label's code leads to the record — what the tool is, its
dimensions, and (once the usage ledger has data) how much it has been used.

Vocabulary (see `UBIQUITOUS_LANGUAGE.md`): *label* is noun and verb — you
**label** a record, **unlabel** it; a label on nothing is **blank**. The
word is deliberately not "bind" (bind stays entry↔instance only), though
labeling rides the same **bind door**: both adjudicate what a physical
artifact is.

## The short URL

Every label resolves at:

    <base>/t/<code>

- `<base>` is **per-instance**: the `PUBLIC_BASE_URL` setting if set,
  otherwise derived from the request. A self-hosted box prints labels
  pointing at itself. Behind a proxy or TLS terminator, set
  `PUBLIC_BASE_URL` explicitly (loobric-deploy does) — labels are permanent
  ink, so set it before printing in earnest.
- `/t/` lives outside `/api` and outside the OpenAPI contract: it is the
  permanent indirection layer between the sticker and whatever the right
  destination is today, and it must outlive API versions.
- Codes are 8-character Crockford base32 — no `I`, `L`, `O`, `U`, so there
  is no 0/O or 1/I/l ambiguity. Lookup is forgiving: case, hyphens, spaces,
  and the ambiguous letters are normalized (`t-7kx3 f9a` finds `T7KX3F9A`).
  The printed code beside the QR is the no-phone fallback.

## What a scan shows

| | anonymous / other accounts | the owning account |
|---|---|---|
| **blank label** | generic landing page (404) | the blank-label page (label it) |
| **labeled** | the **public spec page** | the owner view |

The public spec page follows the *physical-inspection rule*: it reveals
what inspecting the artifact would reveal — name, manufacturer, product
code, nominal and measured geometry, and derived usage totals — never
attribution. No owner, no machines, no history. Provenance sources are
reduced to their kind (`observed` / `asserted` / `derived`); the one full
source shown is `derived:usage-ledger`. **Publish the sum, never the
ledger.** (Enforced by allowlist construction in `public_view.py`; tested
as security assumptions #16–19.)

Labeling a record is what makes its public page exist. Unlabeled records
are never publicly reachable, and an unknown code is indistinguishable from
someone else's blank one.

**Previewing:** the owner can see exactly what anyone else's scan shows with
`/t/<code>?view=public` — byte-identical to the anonymous rendering (the
parameter can only reduce what is shown, so it needs no gating; for anyone
else it is a no-op). The Web UI's Labels tab links both views per label.

## Workflows

**Record first:** create the record, then `POST /api/v1/labels
{"entity_id": <record-id>}` and print it.

**Labels first (the drawer workflow):** pre-print a sheet of blank labels,
keep it in the shop, stick one on whatever you're holding, and label it
from the phone that scanned it. Mint-and-print is one call:

    POST /api/v1/labels/sheet  {"count": 30, "stock": "avery-5160"}

Then attach a code to a record:

    POST /api/v1/tool-instance-records/{id}/label    {"code": "T7KX3F9A"}
    POST /api/v1/tool-instance-records/{id}/unlabel  {"code": "T7KX3F9A"}

Only the **generating account** can use a label's code. Many labels may
point at one record (an existing asset-system tag and a Loobric label can
coexist).

Label lifecycle (founder decisions, 2026-08-04):

- **Unlabel** is the deliberate-reuse path: peel the sticker, the label
  reverts to blank, the code works again on the next thing.
- **Deleting a record BURNS its labels.** Delete is data management — a
  record that should never have existed — and a freed code resurrected on a
  different tool would make the old sticker lie. The codes resolve to the
  landing page forever; to keep a sticker reusable, unlabel first.
- **Retiring is not deleting.** A worn-out tool is a *valid record* of a
  tool no longer in use — assert `status: "retired"` (the first ratified
  status value; the Web UI has a Retire button). A retired tool keeps its
  labels and its public page; retirement itself is owner-only and never
  shown publicly.
- Deleting a label directly likewise makes its code resolve to the landing
  page forever.

## Printing

`POST /api/v1/labels/sheet` returns a PDF sized for real sticker stock:

| stock | for | layout |
|---|---|---|
| `avery-5160` | 30-up US Letter address sheets (and compatibles) | 3 × 10, 2⅝″ × 1″ |
| `thermal-4x6` | 4″ × 6″ adhesive shipping labels (thermal) | 12-up, 2 × 6 of 2″ × 1″, faint cut guides — cut apart |
| `thermal-4x6-wide` | the same 4″ × 6″ stock, wider cut | 4-up, single column of 57 × 32 mm (the thermal-57x32 roll footprint), cut guides incl. outline |
| `thermal-57x32` | 57 × 32 mm thermal rolls | one label per page |

Body: `{"count": N}` (mint and print blanks) **or** `{"label_ids": [...]}`
(reprint existing), plus `"stock"` and optional `"start_at"` — the 0-based
position to start at, so a partially-used Avery sheet goes back in the
printer.

Print at **100% scale** ("actual size" — not "fit to page"); the PDF's
geometry matches the die-cut stock exactly. The QR is vector, crisp at any
DPI, and encodes the full URL; the code is printed grouped (`T7KX-3F9A`)
for readability and normalizes back on entry.

Want the label itself to *say* what the tool is — specs in ink, for
reading instead of scanning? That is a **spec label**: a printed rendering
of the record (with the QR as one optional element), not a Label at all.
See `SPEC_LABELS.md`.

## Solo mode

In solo mode every request is the solo user, so **every scan gets the owner
view** — right for a one-person box on a trusted LAN, which is what solo
mode is. A solo box exposed to the internet has bigger problems than the
resolver (see `SECURITY_ASSUMPTIONS.md`); don't do that.
