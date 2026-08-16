# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tool-schema contract models. See docs/TOOL_SCHEMA.md.

Design notes for contributors:
- A canonical leaf is always a `Field` ({value, unit?, source}); `source`
  encodes provenance and a `null` value is only legal when source is "unknown".
- A client *write* is a `ClientWrite`: the envelope it asserts (client,
  client_version, client_item_id) plus opaque `data`. `extra="forbid"` is what
  makes lane discipline real — a write carrying `internal`/`canonical` fails
  validation, which the API turns into a 400.
- `internal` timestamps and the section `created_at`/`updated_at` are
  server-stamped; clients never send them.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, model_validator


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

UNKNOWN = "unknown"


class Provenance:
    """Helpers for building/parsing the `source` string of a canonical field."""

    OBSERVED = "observed"
    ASSERTED = "asserted"
    DERIVED = "derived"
    UNKNOWN = UNKNOWN

    @staticmethod
    def observed(client: str, machine: str) -> str:
        """A machine measured it — the only provenance a machine may write."""
        return "observed:%s@%s" % (client, machine)

    @staticmethod
    def asserted(actor: str) -> str:
        """A software client or a human declared it, e.g. 'freecad' or
        'human@inbox'."""
        return "asserted:%s" % actor

    @staticmethod
    def derived(by: str) -> str:
        """Computed by the system from other canonical data (e.g. an assembly's
        gauge length from its components). Recomputable; goes stale when its
        inputs change — which is why it is distinct from an assertion."""
        return "derived:%s" % by

    @staticmethod
    def kind(source: str) -> str:
        """The leading token: 'observed' | 'asserted' | 'derived' | 'unknown'."""
        return source.split(":", 1)[0]


class Field(BaseModel):
    """A canonical leaf: a value with its provenance.

    The whole point of the schema: you cannot read a value without seeing where
    it came from, and an unstated value is honestly null, never a guess.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any = None
    unit: Optional[str] = None
    source: str

    @model_validator(mode="after")
    def _check(self) -> "Field":
        k = Provenance.kind(self.source)
        if k not in (Provenance.OBSERVED, Provenance.ASSERTED,
                     Provenance.DERIVED, UNKNOWN):
            raise ValueError("invalid provenance kind in source %r" % self.source)
        if k == UNKNOWN:
            if self.source != UNKNOWN:
                raise ValueError("unknown source must be exactly 'unknown'")
            if self.value is not None:
                raise ValueError("a field with source 'unknown' must have value null")
        if k == Provenance.OBSERVED and "@" not in self.source:
            raise ValueError(
                "observed source must be 'observed:<client>@<machine>', got %r"
                % self.source
            )
        if k in (Provenance.ASSERTED, Provenance.DERIVED) and ":" not in self.source:
            raise ValueError("%s source must be '%s:<actor>'" % (k, k))
        return self


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

class Internal(BaseModel):
    """Server-owned plumbing. Read-only to clients."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    created_at: str
    updated_at: str


class EntryInternal(Internal):
    """A tool-table entry additionally carries its owning machine."""

    machine_id: str


class ClientSection(BaseModel):
    """One client's section as it appears in a server *response*: the envelope
    (timestamps server-stamped) plus opaque data.

    The client is identified by this section's KEY in the `clients` map — there
    is deliberately no redundant `client` field inside, since a second copy of
    the key could only diverge (the anti-pattern we removed for tool numbers).
    """

    model_config = ConfigDict(extra="forbid")

    client_version: str
    client_item_id: Optional[str] = None
    created_at: Optional[str] = None   # server-stamped
    updated_at: Optional[str] = None   # server-stamped
    data: Dict[str, Any] = {}


class ClientWrite(BaseModel):
    """What a client *sends* to write its own section. The client name is
    carried by the request path (`…/clients/{name}`), not this body.

    `extra="forbid"` is load-bearing: a write that includes `internal` or
    `canonical` (or any stray key) fails validation. That is lane discipline —
    routine sync physically cannot mutate canonical.
    """

    model_config = ConfigDict(extra="forbid")

    client_version: str
    client_item_id: Optional[str] = None
    data: Dict[str, Any] = {}


class LaneViolation(ValueError):
    """A client write crossed into the internal/canonical lane."""


def reject_out_of_lane(payload: Dict[str, Any]) -> ClientWrite:
    """Validate a raw client-section write, rejecting any internal/canonical
    keys. Raises LaneViolation (→ HTTP 400) on a violation."""
    for forbidden in ("internal", "canonical"):
        if forbidden in payload:
            raise LaneViolation(
                "a client sync may not write the %r section; canonical changes "
                "go through the observe/assert endpoints" % forbidden
            )
    try:
        return ClientWrite.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError → lane violation
        raise LaneViolation(str(exc)) from exc


# ---------------------------------------------------------------------------
# Canonical shapes (entity-specific content; uniform Field leaves)
# ---------------------------------------------------------------------------

class Geometry(BaseModel):
    """Canonical geometry; every present key is a provenance-tagged Field.
    Extra geometry keys are allowed but must also be Fields."""

    model_config = ConfigDict(extra="allow")

    diameter: Optional[Field] = None
    shape: Optional[Field] = None
    length: Optional[Field] = None
    flutes: Optional[Field] = None
    cutting_edge_height: Optional[Field] = None
    shank_diameter: Optional[Field] = None
    # assembly-level geometry (ISO 13399 §Composition): the cutting diameter
    # comes from the cutting item; the gauge/functional length is EMERGENT from
    # the whole stack — typically source "derived:components", or
    # "observed:presetter@…" when measured on a tool presetter.
    cutting_diameter: Optional[Field] = None
    gauge_length: Optional[Field] = None


# -- Composition (ISO 13399) --------------------------------------------------
# A record may be a leaf (a single item) or an assembly (a stack of items that
# couple through interfaces). The assembly is itself a record; `components`
# references the items it is built from. See docs/TOOL_SCHEMA.md §Composition.

ITEM_TYPES = {"cutting_item", "tool_item", "adaptive_item", "assembly_item",
              "assembly"}
COMPONENT_ROLES = {"cutting_item", "tool_item", "adaptive_item", "assembly_item"}


class Component(BaseModel):
    """One entry in an assembly's `components` list: a reference to another
    record, the ISO role it plays, and an opaque connection/interface coupling
    (HSK/BT/Capto interface, gauge offset, stick-out, …) left flexible for now."""

    model_config = ConfigDict(extra="forbid")

    component_id: str
    role: str
    connection: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _role(self) -> "Component":
        if self.role not in COMPONENT_ROLES:
            raise ValueError("invalid component role %r" % self.role)
        return self


def _validate_composition(item_type: Optional[Field],
                          components: Optional[Field]) -> None:
    """Shared rules for the two record canonicals that may be assemblies."""
    if item_type is not None and item_type.value is not None:
        if item_type.value not in ITEM_TYPES:
            raise ValueError("invalid item_type %r" % item_type.value)
    if components is not None and components.value is not None:
        if not isinstance(components.value, list):
            raise ValueError("components value must be a list")
        for entry in components.value:
            Component.model_validate(entry)


# -- Media (docs/TOOL_SCHEMA.md §Media) ---------------------------------------
# A tool carries media — 3D models (STEP), 2D drawings, images, logos — as
# canonical *references*. The bytes live in the blob store (loobric_server.media_store)
# and are served out-of-band; the record holds only a small, shareable, verifiable
# reference. Like `components`, the whole media set is one provenance-tagged Field
# (value = list[MediaRef]); the server never parses the media — clients (FreeCAD)
# and the web UI render it.

MEDIA_ROLES = {
    "model_3d",        # detailed 3D solid (e.g. a GTC detailed STEP)
    "model_3d_basic",  # simplified/basic 3D solid
    "drawing_2d",      # a 2D product/technical drawing
    "image",           # a product photo/picture
    "icon",            # a class/product icon
    "logo",            # a brand/manufacturer logo
    "document",        # any other document (datasheet, disclaimer, …)
}


class MediaRef(BaseModel):
    """One media file referenced by a record: the role it plays, its blob-store
    reference, and enough metadata to serve/render it. The bytes are NOT here —
    `ref` keys them in the blob store."""

    model_config = ConfigDict(extra="forbid")

    role: str
    ref: str                              # blob-store key, e.g. "sha256:<hex>"
    content_type: str                     # MIME, e.g. "model/step", "image/png"
    filename: Optional[str] = None        # original filename, for download
    size: Optional[int] = None            # bytes

    @model_validator(mode="after")
    def _role(self) -> "MediaRef":
        if self.role not in MEDIA_ROLES:
            raise ValueError("invalid media role %r" % self.role)
        return self


def _validate_media(media: Optional[Field]) -> None:
    """A `media` Field's value is a list of MediaRef descriptors (or null)."""
    if media is not None and media.value is not None:
        if not isinstance(media.value, list):
            raise ValueError("media value must be a list")
        for entry in media.value:
            MediaRef.model_validate(entry)


# Cutting data presets (docs/PRESETS.md, grilled 2026-08-16): canonical
# `presets` is a DERIVED union of source-preserved contributions — a
# recommendation with a source, never a fact about the tool. The server never
# reconciles; the list is materialized with source `derived:preset-union` and
# no door writes it directly.

OP_TYPES = {
    "profiling", "slotting", "pocketing", "adaptive", "facing",
    "drilling", "boring", "threading", "engraving", "chamfering",
}

PRESET_SCHEMA = 1


class PresetMaterial(BaseModel):
    """Material as the source stated it — verbatim, normalization deferred
    (the materials vocabulary is its own future ratification)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    uuid: Optional[str] = None


class PresetEntry(BaseModel):
    """One cutting data preset in the derived union: G5 engineering values
    (raw feed/RPM never persisted) plus a verbatim, non-comparable extras
    bag. `origin` is the RECOMMENDER (manufacturer, freecad, user, an
    agent); the provenance `source` records the transcriber — the same
    split the manufacturer-QA door uses. Identity is (origin, label)."""

    model_config = ConfigDict(extra="forbid")

    id: str                               # contribution row id
    origin: str                           # recommender: "manufacturer", "freecad", …
    label: str                            # per-origin name ("Aggressive", "6061 profiling")
    material: PresetMaterial
    op_type: Optional[str] = None         # ratified OP_TYPES member, or absent
    vc: Optional[dict] = None             # surface speed {value, unit}
    fz: Optional[dict] = None             # chipload {value, unit}
    ratio: Optional[dict] = None          # vertical-feed ratio {value}
    extras: Optional[dict] = None         # verbatim, non-comparable
    machine_id: Optional[str] = None      # optional machine qualifier
    preset_schema: int = PRESET_SCHEMA
    source: str = "unknown"               # asserted:<transcriber>
    updated_at: Optional[str] = None

    @model_validator(mode="after")
    def _floor(self) -> "PresetEntry":
        if self.op_type is not None and self.op_type not in OP_TYPES:
            raise ValueError(
                "op_type must be one of %s (or absent) — the vocabulary is "
                "ratified, not accreted" % sorted(OP_TYPES))
        if self.vc is None and self.fz is None and self.ratio is None:
            raise ValueError(
                "a preset needs at least one engineering value (vc, fz, or "
                "ratio) — an entry with none has no comparable surface")
        return self


def _validate_presets(presets: Optional[Field]) -> None:
    """A `presets` Field's value is a list of PresetEntry dicts (or null)."""
    if presets is not None and presets.value is not None:
        if not isinstance(presets.value, list):
            raise ValueError("presets value must be a list")
        for entry in presets.value:
            PresetEntry.model_validate(entry)


class InstanceCanonical(BaseModel):
    """A physical tool's agreed truth: measured geometry, optional catalog
    link (unknown until asserted), install status. May be an assembly (a built
    physical stack) via item_type/components — the assembly instance is what a
    machine tool-table entry binds."""

    model_config = ConfigDict(extra="forbid")

    name: Field
    catalog_type_id: Field            # provenance-tagged; unknown until asserted
    status: Optional[Field] = None
    item_type: Optional[Field] = None     # ISO role; None ~ leaf, or "assembly"
    components: Optional[Field] = None    # list[Component] when an assembly
    media: Optional[Field] = None         # list[MediaRef]; bytes in the blob store
    geometry: Geometry = Geometry()
    usage: Optional["InstanceUsage"] = None  # derived:usage-ledger only (§7.8)
    presets: Optional[Field] = None       # list[PresetEntry]; derived:preset-union only

    @model_validator(mode="after")
    def _composition(self) -> "InstanceCanonical":
        _validate_composition(self.item_type, self.components)
        _validate_media(self.media)
        _validate_presets(self.presets)
        return self


class CatalogCanonical(BaseModel):
    """A catalog type's agreed truth: nominal (asserted) geometry + identity.
    May be a catalog assembly (a reusable recipe) via item_type/components."""

    model_config = ConfigDict(extra="forbid")

    name: Field
    manufacturer: Optional[Field] = None
    product_code: Optional[Field] = None
    item_type: Optional[Field] = None
    components: Optional[Field] = None
    media: Optional[Field] = None         # list[MediaRef]; bytes in the blob store
    geometry: Geometry = Geometry()
    presets: Optional[Field] = None       # list[PresetEntry]; derived:preset-union only

    @model_validator(mode="after")
    def _composition(self) -> "CatalogCanonical":
        _validate_composition(self.item_type, self.components)
        _validate_media(self.media)
        _validate_presets(self.presets)
        return self


class EntryOffsets(BaseModel):
    model_config = ConfigDict(extra="allow")

    diameter: Optional[Field] = None
    z: Optional[Field] = None
    x: Optional[Field] = None
    y: Optional[Field] = None


class EntryCanonical(BaseModel):
    """A machine tool-table entry's agreed truth."""

    model_config = ConfigDict(extra="forbid")

    tool_number: Field                 # the CAM<->CNC contract; observed
    bound_instance_id: Field           # the physical tool in the entry
    description: Optional[Field] = None  # the table comment (observed label), e.g. "Probe"
    offsets: EntryOffsets = EntryOffsets()
    # The controller's own tool-life counter, verbatim (§7.8): that machine's
    # ledger for this row, nothing more. Observed; resets when the
    # controller's does. The usage ledger turns its deltas into attributed
    # contributions — this field is never a tool's total.
    usage_hours: Optional[Field] = None


class InstanceUsage(BaseModel):
    """Lifetime usage on a physical tool (§7.8). Always derived — the source
    is the usage ledger and no door writes it directly; it decomposes into
    per-machine contributions on demand."""

    model_config = ConfigDict(extra="forbid")

    hours: Optional[Field] = None


class SetMember(BaseModel):
    """A tool set member: which tool, at which claimed position.

    `number` is the member's durable CAM-side claim (asserted, or unknown) —
    it is only ever changed by an assert, never overwritten by observation
    (MAPPING_PLAN.md §5.1). `observed` and `state` are derived at read time
    against the machine the set is currently active on (its setup) and are
    never stored:

    - `observed` — the tool_number Field of the machine entry actually holding
      this member's instance (or the entry at the claimed number, for a
      pending bind), verbatim with its observed provenance.
    - `state` — "satisfied" | "mismounted" | "blocked" | "pending bind" |
      "requested". Both absent (None) when no setup maps the set to a machine.
    """

    model_config = ConfigDict(extra="forbid")

    tool_record_id: str
    number: Field                      # the claim: asserted, or unknown
    observed: Optional[Field] = None   # derived at read time; never stored
    state: Optional[str] = None        # derived at read time; never stored


class ToolSetCanonical(BaseModel):
    """An agnostic named collection — purely CAM-owned. The machine
    relationship lives on the setup (machine_set_maps), never on the set."""

    model_config = ConfigDict(extra="forbid")

    name: Field
    members: List[SetMember] = []


class MachineSpindle(BaseModel):
    """Spindle capability — declared limits, not runtime telemetry. The
    canonical home for what CAM (and agent sessions) need to reason about
    feeds/speeds without tool-list archaeology. `extra="forbid"`: capability
    vocabulary is deliberate — new fields are ratified, not accreted."""

    model_config = ConfigDict(extra="forbid")

    max_rpm: Optional[Field] = None
    min_rpm: Optional[Field] = None
    power: Optional[Field] = None      # rated power; unit e.g. "kW"
    taper: Optional[Field] = None      # spindle nose interface, e.g. "R8", "BT30", "HSK63A"


class MachineCoolant(BaseModel):
    """Coolant capability flags — what the machine HAS, not what is running.
    Each present leaf is a provenance-tagged Field with a boolean value."""

    model_config = ConfigDict(extra="forbid")

    flood: Optional[Field] = None
    mist: Optional[Field] = None
    through_spindle: Optional[Field] = None


class MachineCanonical(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Field
    controller_type: Optional[Field] = None
    definition: Optional[Field] = None
    spindle: MachineSpindle = MachineSpindle()
    coolant: MachineCoolant = MachineCoolant()


# ---------------------------------------------------------------------------
# Entities (identical three-section shape)
# ---------------------------------------------------------------------------

class ToolInstanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    internal: Internal
    canonical: InstanceCanonical
    clients: Dict[str, ClientSection] = {}


class ToolCatalogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    internal: Internal
    canonical: CatalogCanonical
    clients: Dict[str, ClientSection] = {}


class ToolTableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    internal: EntryInternal
    canonical: EntryCanonical
    clients: Dict[str, ClientSection] = {}


class ToolSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    internal: Internal
    canonical: ToolSetCanonical
    clients: Dict[str, ClientSection] = {}


class Machine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    internal: Internal
    canonical: MachineCanonical
    clients: Dict[str, ClientSection] = {}
