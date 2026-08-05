# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""The importer-internal intermediate: a parsed, not-yet-created catalog record."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# The identity floor every catalog record needs (the natural key is
# manufacturer + product_code; name is required by the contract).
IDENTITY_FIELDS = ("name", "manufacturer", "product_code")


@dataclass
class MediaFile:
    """A media file a parser extracted (a 3D model, drawing, image) to be
    uploaded to the record's canonical media after it is created. The bytes are
    carried here; the run driver streams them to the server's media endpoint."""

    role: str                                 # a MEDIA_ROLE: model_3d / image / ...
    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


@dataclass
class CatalogRecordDraft:
    """One catalog record a parser produced, before it is sent.

    Pure data — no provenance, no network. ``fields`` is the canonical
    ``{value, unit?}`` leaf map :meth:`Client.create_catalog_record` expects
    (the server stamps the ``asserted:<source>`` provenance). ``raw`` is the
    full source payload, kept verbatim so the import is lossless and the
    unmapped source codes survive for later promotion. ``media`` is any files to
    attach to the record's canonical media once it exists.
    """

    fields: Dict[str, Any]
    raw: Dict[str, Any]
    source_format: str                       # e.g. "din4000-csv" / "gtc" / "p21"
    source_class: Optional[str] = None        # e.g. "DIN4000-82" / "MILSQS"
    media: List[MediaFile] = field(default_factory=list)
    # Per-format defaults the run driver/CLI use when not overridden: the
    # declared actor (server stamps asserted:<actor>) and the client-section name
    # the raw payload is preserved under.
    source_actor: str = "import"
    client_name: str = "import"

    def _leaf_value(self, key: str) -> Any:
        leaf = self.fields.get(key)
        return leaf.get("value") if isinstance(leaf, dict) else None

    @property
    def name(self) -> Any:
        return self._leaf_value("name")

    @property
    def manufacturer(self) -> Any:
        return self._leaf_value("manufacturer")

    @property
    def product_code(self) -> Any:
        return self._leaf_value("product_code")

    def missing_identity(self) -> List[str]:
        """The identity fields with no value — a draft missing any of these
        should be skipped, not sent as a malformed record."""
        return [k for k in IDENTITY_FIELDS if not self._leaf_value(k)]
