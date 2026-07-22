# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Loobric tool-schema contract — the single source of truth.

These models are the machine-readable form of docs/TOOL_SCHEMA.md. They
validate the wire on the server AND drive the client conformance suite, so a
client and the server cannot drift from the same definition.

Three sections, identical on every entity:
  internal   — server-owned (id, version, timestamps); read-only to clients
  canonical  — agreed truth; every leaf is a provenance-tagged Field
  clients    — per-client envelope + opaque data

See docs/TOOL_SCHEMA.md for the prose.
"""
from loobric_server.contract.models import (
    # provenance
    Field, Provenance, UNKNOWN,
    # sections
    Internal, EntryInternal, ClientSection, ClientWrite, LaneViolation,
    reject_out_of_lane,
    # canonical shapes
    Geometry, InstanceCanonical, CatalogCanonical, EntryCanonical,
    EntryOffsets, ToolSetCanonical, SetMember, MachineCanonical,
    # composition (ISO 13399)
    Component, ITEM_TYPES, COMPONENT_ROLES,
    # media
    MediaRef, MEDIA_ROLES,
    # entities
    ToolInstanceRecord, ToolCatalogRecord, ToolTableEntry, ToolSet, Machine,
)

__all__ = [
    "Field", "Provenance", "UNKNOWN",
    "Internal", "EntryInternal", "ClientSection", "ClientWrite",
    "LaneViolation", "reject_out_of_lane",
    "Geometry", "InstanceCanonical", "CatalogCanonical", "EntryCanonical",
    "EntryOffsets", "ToolSetCanonical", "SetMember", "MachineCanonical",
    "Component", "ITEM_TYPES", "COMPONENT_ROLES",
    "MediaRef", "MEDIA_ROLES",
    "ToolInstanceRecord", "ToolCatalogRecord", "ToolTableEntry", "ToolSet",
    "Machine",
]
