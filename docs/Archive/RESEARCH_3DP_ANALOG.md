# Research: The Multi-Material 3D-Printing Analog

**Question:** How do multi-material 3D-printing ecosystems keep "which material is in
which slot" synchronized between the physical machine and the slicer — and what
design patterns, vocabulary, and concepts transfer to Loobric's tool-number problem?

**Method:** Deep-research workflow (2026-06-12): 5 search angles, 22 sources fetched,
107 claims extracted, 25 top claims put through 3-vote adversarial verification →
19 confirmed. Standards-angle gaps filled by direct source reads (OpenTag3D spec,
ISO 23247 overview, MTConnect Part 4, Bambu RFID reverse-engineering). Claims below
are cited; the few unverified-but-plausible items are marked.

**Verdict up front:** the analogy is exact, and the 3DP world — with vastly more
units in the field and cheaper failure modes — has independently converged on the
*same architecture Loobric already has*, which is strong validation. It has also
evolved three ideas Loobric does not have yet, all of which bear directly on open
decisions D14/D15.

---

## 1. The same problem, the same split

Every ecosystem surveyed structures the problem as two halves of a slot-indexed
contract, exactly like Loobric's CAM-half / machine-half of "what is T3":

- **Prusa:** "the resulting G-code carries information on how individual materials
  and extruders are assigned … to various parts of the object" — the *job artifact
  itself* carries the slicer's half of the contract; the printer-side **Tools
  Mapping / Filament Mapping** screen reconciles it against physical reality at
  print start. ([help.prusa3d.com 732461](https://help.prusa3d.com/article/tools-mapping-and-filament-mapping-xl-mmu3_732461), [668277](https://help.prusa3d.com/article/tools-mapping-xl_668277))
- **Bambu:** at job dispatch, Bambu Studio "automatically maps the 'sliced preset
  filament' to the 'actually loaded filament in AMS'" — slicer assumption vs.
  machine reality, joined by an explicit mapping step. ([wiki.bambulab.com filament-mapping-principle](https://wiki.bambulab.com/en/software/bambu-studio/filament-mapping-principle))
- **OpenPrintTag (Prusa's open NFC standard):** the stated purpose is removing the
  human-error failure mode: "It's incredibly easy to grab a spool of black PETG,
  thinking it's PLA … The printer simply knows what material is loaded, so the user
  can't select the wrong profile by mistake." ([blog.prusa3d.com](https://blog.prusa3d.com/the-openprinttag-is-here-a-brand-new-nfc-tag-standard-for-smart-filament-is-now-shipped-with-a-new-redesigned-prusament-spool_123878/))

## 2. Identity-carrying vs identity-less media — independently confirmed

Loobric's taxonomy (CONCEPTS.md) distinguishes clients whose representation can carry
a server identity (.fctb) from those that can't (.tbl → human-confirmed Binding).
Bambu's ecosystem draws **exactly the same line, with the same consequence**:

- AMS slots are identity-carrying: official spools have RFID tags on both sides,
  the AMS has two reader boards, and slot contents are machine-identified rather
  than human-asserted. ([wiki.bambulab.com ams-function-introduction](https://wiki.bambulab.com/en/ams/manual/ams-function-introduction))
- External (non-AMS) spools are identity-less, and the system's response is the
  Loobric response: "If an external spool is used, automatic matching will not be
  performed on the print submission page, and **you need to manually confirm** the
  filament type." ([filament-mapping-principle](https://wiki.bambulab.com/en/software/bambu-studio/filament-mapping-principle))

So the rule generalizes across domains: **automate identity where the medium can
carry it; require human confirmation where it can't; never guess.** Same pattern in
the registry-based tools: OctoPrint-SpoolManager bindings are human-maintained
(manual spool→tool selection, optional QR/barcode scan as deliberate human action —
no auto-ID). ([github.com/OllisGit/OctoPrint-SpoolManager](https://github.com/OllisGit/OctoPrint-SpoolManager))

### The trust spectrum within identity-carrying media

The 3DP world also surfaces a dimension Loobric hasn't needed yet — *who vouches for
the identity the medium carries*:

| Trust model | Example | Mechanism |
|---|---|---|
| Manufacturer-signed, closed | Bambu RFID | Per-tag derived keys + 2048-bit RSA signature; only Bambu can mint tags; cloning possible, forging not. ([Bambu-Research-Group/RFID-Tag-Guide](https://github.com/Bambu-Research-Group/RFID-Tag-Guide)) |
| Open, self-describing | OpenTag3D | Plain memory-mapped fields, no signature, no central registry — "rejected lookup tables to avoid dependency on maintained databases." ([opentag3d.info/spec.html](https://opentag3d.info/spec.html)) |
| Open, record-on-medium | OpenSpool / OpenPrintTag | NDEF JSON with `protocol`/`version` + material attributes (`type`, `color_hex`, `brand`, `min_temp`, `max_temp`) — the tag carries the *record*, not just an opaque id. ([github.com/spuder/OpenSpool](https://github.com/spuder/OpenSpool)) |
| Registry + human assertion | SpoolManager/Spoolman | Identity lives server-side; the physical link is a human act (select or scan). |

Note the design tension OpenTag3D resolved: **id-on-medium + central registry**
(Loobric's .fctb model — tag carries a key, server holds the record) versus
**record-on-medium** (works offline, no registry dependency, but copies can drift).
Loobric is registry-shaped by design; worth knowing the alternative exists and why
the open 3DP standards chose it (decentralization, no licensing/lock-in — kindred
goals to Loobric's no-lock-in posture).

## 3. Patterns Loobric doesn't have yet (the transferable ideas)

### P1 — The job-dispatch verification gate ("pre-flight check")

In both major ecosystems, reconciliation has a **moment**: job start.

- Prusa: selecting a G-code and pressing Print opens the mapping screen *before the
  job runs* — a mandatory pass-through gate where the operator confirms or remaps
  logical filament indexes to physical slots. ([732461](https://help.prusa3d.com/article/tools-mapping-and-filament-mapping-xl-mmu3_732461))
- Bambu: dispatch triggers auto-mapping with a human override window. ([ams-function-introduction](https://wiki.bambulab.com/en/ams/manual/ams-function-introduction))

Loobric currently verifies *continuously* (sync + bindings make mismatch visible) but
has no notion of "this specific job's tool assumptions, checked at the moment of
running it." **D14's mismatch alarm becomes much stronger reframed as a dispatch-time
gate:** given the tool list a job was posted against, check each number against the
machine's current bindings — green/red per tool — before the spindle turns. The 3DP
precedent says this is where the check belongs, because it is the last point where
divergence is recoverable.

### P2 — The job artifact carries its assumptions

Prusa embeds the material→extruder assignment *in the G-code file itself*; the
printer-side gate reconciles the file's own metadata against the machine. ([668277](https://help.prusa3d.com/article/tools-mapping-xl_668277))
Loobric records CAM numbering with the ToolSet on the server, but a posted CNC
G-code file is mute about which ToolRecords its T-numbers meant. A post-processor
that stamps the assumption into the artifact (header comment block or sidecar:
`T3 = ToolRecord <id> "1/4in downcut"`) makes every job self-describing and makes
the P1 gate implementable by *anything* that can read the file and the API — even
retroactively, for a job posted months ago. This is cheap, additive, and
client-side.

### P3 — Re-verify on state-change events, not just on schedule

The AMS re-reads slot identity at exactly the moments physical state may have
changed: **on insertion**, **on startup**, and **on demand**. ([ams-function-introduction](https://wiki.bambulab.com/en/ams/manual/ams-function-introduction))
The CNC analog: trigger a sync/verification pass on controller restart and on tool
change/touch-off events rather than only cron cadence. (LinuxCNC client today is
cron-shaped; the event hooks exist controller-side.)

### P4 — Parameter-keyed matching, cosmetic tie-break

Bambu's auto-mapping "prioritize[s] print success rate and quality first, then
consider[s] color consistency": match first on the parameters that cause physical
failure (material/model — volumetric flow, melt temp), only then on appearance
(hex code, then nearest color family). ([filament-mapping-principle](https://wiki.bambulab.com/en/software/bambu-studio/filament-mapping-principle))
Direct guidance for Loobric's binding-proposal heuristics: rank by
failure-relevant parameters (diameter, type, flute count) before
cosmetic/labeling similarity (names, descriptions) — and document the ranking, as
Bambu does, so users can predict the proposals.

### P5 — What does NOT transfer: print-time *remapping*

Prusa/Bambu let the operator remap logical index → physical slot at job start
without re-slicing, because for filament the assignment is genuinely late-bindable
(any slot can feed the nozzle). For CNC, T-numbers are baked into a posted program
along with feeds, offsets and kinematic assumptions; "just run T3 as T8" is not
generally safe and most controllers don't support per-job remap. The transferable
part is the **gate** (verify), not the **remap** (mutate). Loobric should verify and
block/warn — re-posting is the CNC-correct fix.

## 4. Vocabulary harvest

| 3DP term | Meaning there | Loobric resonance |
|---|---|---|
| **Mapping / remapping** | Joining logical filament indexes to physical slots at job time | Candidate verb for the dispatch-time check; distinct from (durable) *binding* |
| **Slot / tray** | Physical magazine position | = pocket — and 3DP also treats it as non-identity |
| **Filament profile / preset** | Parameter record for a material | = Preset (already adopted from FreeCAD) |
| **Read on insertion / read on startup** | Event-triggered identity re-verification | Naming for sync triggers (P3) |
| **External spool** | Identity-less medium requiring manual confirmation | = identity-less client representation |
| **Smart spool** | Identity-carrying medium | Marketing term; concept = identity-carrying |
| **Mismatch** | Job assumption ≠ machine reality | Already implicit in D14; worth a vocabulary entry when the gate is designed |

A real distinction the 3DP language keeps that Loobric should preserve:
**mapping** (per-job, ephemeral, at dispatch) vs **binding** (durable, sticky,
machine-state). Prusa's mapping screen does not create lasting state; Loobric's
Binding does. Don't let the words blur.

## 5. Standards & academic framing

- **MTConnect Part 4 (Cutting Tool assets)** is the industry-standard vocabulary for
  exactly Loobric's nouns, and it independently validates both open decisions:
  - `CuttingToolDefinition` (type) vs `CuttingTool` (instance, with `serialNumber`)
    vs `CuttingToolLifeCycle` — the type/instance split is first-class → supports
    **D15** (facade-level physical-instance identity).
  - **`ProgramToolNumber`** is a first-class element: "the tool designation used
    within NC programs, enabling correlation between part program tool calls and
    physical asset management" — the standard models the CAM-side number as
    promotable, structured data, not opaque passthrough → supports **D14(a)**.
  - Pocket/pot/station numbers are modeled as *location*, separate from identity —
    matching the "pocket is not the tool number" doc. ([docs.mtconnect.org Part 4](https://docs.mtconnect.org/MBSD_MTConnect_Part_4_2-2-0.pdf))
- **ISO 23247 (digital twin framework for manufacturing)** gives the academic frame:
  Loobric's tool table is a **digital twin** of an *observable manufacturing element*
  (the controller's table); sync is *twin synchronization*; the D14 alarm is
  **discrepancy detection** raising an **Exception** ("monitor differences between
  predicted … and measured … to identify when physical state diverges from digital
  representation"). Useful citation language for docs/marketing; the architecture
  itself (4-layer, OPC-UA/MTConnect transport) is heavier than Loobric needs. ([ap238.org/iso23247](https://www.ap238.org/iso23247/))
- **RFID tool identification in machining exists commercially** (chip-in-toolholder,
  e.g. Balluff/CaronEng ToolConnect-style presetter→machine transfer) — the CNC
  world's identity-carrying medium. Rare outside high-end shops; Loobric's
  human-confirmed Binding is the right default for the long tail, with
  chip-carrying toolholders as a future identity-carrying client (same slot in the
  taxonomy as a barcode controller, D15).

## 6. Mapping onto Loobric — summary table

| 3DP finding | Loobric disposition |
|---|---|
| Identity-carrying vs identity-less media split | **Already have it** — independently validated (Bambu external-spool manual confirm = our Binding) |
| Never guess; human confirms where media is mute | **Already have it** (G5, Inbox) |
| Parameter-first proposal ranking | **Adopt** in binding-proposal heuristics (P4) |
| Event-triggered re-verification | **Adopt** as sync-trigger guidance for controller clients (P3) |
| Job-dispatch verification gate | **New — candidate D16.** Reframes D14's alarm as a pre-flight check per job |
| Job artifact carries its tool assumptions | **New — candidate D17.** Post-processor stamps ToolRecord ids into G-code header/sidecar |
| Print-time remapping (mutate the mapping at dispatch) | **Reject** for CNC — verify, don't remap (P5) |
| Record-on-medium (no registry) | **Reject** — Loobric is registry-shaped; know the tradeoff exists |
| Cryptographically signed identity media | **Out of scope** — Bambu's closed model is the opposite of Loobric's posture; OpenTag3D/OpenPrintTag are the kindred designs |
| MTConnect `ProgramToolNumber`, `CuttingTool` instance | **Naming/precedent input to D14(a) and D15** — align field names where sensible |

## Caveats

The verification phase hit a session limit near the end: 19/25 claims were
adversarially confirmed; three further claims (Bambu's manual override of
auto-mapping; the AMS edit-tray UI for manual entry; the two-column layout of
Prusa's mapping dialog) died on abstentions, not refutations — they match product
documentation and are very likely true, but treat them as unverified detail. The
academic angle was source-fetched but under-verified by the panel; the MTConnect /
ISO 23247 / OpenTag3D summaries above come from direct reads of the primary
documents.
