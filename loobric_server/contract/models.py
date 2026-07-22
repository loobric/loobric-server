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

    @model_validator(mode="after")
    def _composition(self) -> "InstanceCanonical":
        _validate_composition(self.item_type, self.components)
        _validate_media(self.media)
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

    @model_validator(mode="after")
    def _composition(self) -> "CatalogCanonical":
        _validate_composition(self.item_type, self.components)
        _validate_media(self.media)
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


class SetMember(BaseModel):
    """A tool set member: which tool, at which canonical position."""

    model_config = ConfigDict(extra="forbid")

    tool_record_id: str
    number: Field                      # observed when machine-bound; else asserted
    # Derived at read time for a machine-bound set (never stored): the member's
    # state against the machine's tool-table entries — "loaded" | "requested" |
    # "pending bind". Absent (None) for a set with no machine link.
    state: Optional[str] = None


class ToolSetCanonical(BaseModel):
    """An agnostic named collection. `machine_id` (optional) links it to a
    machine whose entries its member numbers then inherit."""

    model_config = ConfigDict(extra="forbid")

    name: Field
    machine_id: Field                  # provenance-tagged; unknown for a general set
    members: List[SetMember] = []


class MachineCanonical(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Field
    controller_type: Optional[Field] = None
    definition: Optional[Field] = None


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
