# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""The public spec-page projection (docs/LABELS.md).

What an anonymous scan of a labeled tool may see, built by ALLOWLIST
CONSTRUCTION: this module assembles the public dict from scratch, naming
every field it includes — it never filters a record, so a new private field
elsewhere in the schema cannot leak here by default.

The rule ("physical inspection with better instruments"): the public page
reveals what inspecting the physical artifact would reveal — what the tool
IS (catalog identity, geometry) and its accumulated condition (derived usage
totals) — never attribution. Publish the sum, never the ledger.

INVARIANT (docs/SECURITY_ASSUMPTIONS.md): the anonymous view never
identifies the owner. Nothing here may include emails, user ids, record
UUIDs, machine names, client names, notes, client sections, or audit data.
Provenance sources are reduced to their KIND (`observed`/`asserted`/
`derived`) because a full source (`observed:linuxcnc@vf2`) names a machine.
The single exception is the exact string `derived:usage-ledger`, which is
non-identifying by construction and tells a buyer HOW the hour total is
known.
"""
from typing import Optional

# Geometry keys shown publicly, in display order. Mirrors the named keys of
# contract.models.Geometry; extra (open-vocabulary) geometry keys are NOT
# shown — allowlist, not filter.
GEOMETRY_KEYS = (
    "shape", "diameter", "cutting_diameter", "shank_diameter", "length",
    "cutting_edge_height", "gauge_length", "flutes",
)

_VERBATIM_SOURCES = {"derived:usage-ledger"}


def _kind(source) -> str:
    """Reduce a provenance source to its non-identifying kind token."""
    if not isinstance(source, str) or not source:
        return "unknown"
    if source in _VERBATIM_SOURCES:
        return source
    return source.split(":", 1)[0]


def _leaf(section, key) -> Optional[dict]:
    """A public {value, unit?, provenance} leaf from a canonical Field, or
    None when the field is absent or honestly unknown."""
    field = (section or {}).get(key)
    if not isinstance(field, dict):
        return None
    value = field.get("value")
    if value is None:
        return None
    out = {"value": value, "provenance": _kind(field.get("source"))}
    if field.get("unit") is not None:
        out["unit"] = field["unit"]
    return out


def _geometry(canonical) -> dict:
    geo = (canonical or {}).get("geometry") or {}
    out = {}
    for key in GEOMETRY_KEYS:
        leaf = _leaf(geo, key)
        if leaf is not None:
            out[key] = leaf
    return out


def public_projection(instance_row, catalog_row=None) -> dict:
    """The public spec page's data, from an owned instance row and its
    optionally-linked catalog row. Everything included is named here;
    everything else on the records does not exist as far as this page is
    concerned."""
    instance_canonical = instance_row.canonical or {}
    out = {
        "name": (_leaf(instance_canonical, "name") or {}).get("value"),
        "catalog": None,
        # Measured geometry on the physical tool.
        "geometry": _geometry(instance_canonical),
        # Lit by the usage ledger (docs/TOOL_SCHEMA.md §7.8) once derived
        # totals exist; None until then.
        "usage_hours": None,
    }
    usage = instance_canonical.get("usage") or {}
    hours = _leaf(usage, "hours")
    if hours is not None and hours["provenance"] in _VERBATIM_SOURCES:
        out["usage_hours"] = hours
    if catalog_row is not None:
        catalog_canonical = catalog_row.canonical or {}
        out["catalog"] = {
            "name": (_leaf(catalog_canonical, "name") or {}).get("value"),
            "manufacturer": (_leaf(catalog_canonical, "manufacturer") or {}).get("value"),
            "product_code": (_leaf(catalog_canonical, "product_code") or {}).get("value"),
            # Nominal geometry on the type.
            "geometry": _geometry(catalog_canonical),
        }
    return out
