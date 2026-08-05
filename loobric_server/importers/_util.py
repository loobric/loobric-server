# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""Small shared helpers for the param-based importers (SolidCAM, hyperMILL)."""
from typing import Any, Dict, Optional

# Geometry paths parsed as integers (counts), not floats.
INT_GEOM = {"geometry.flutes"}


def num_leaf(path: str, raw: Any, unit: Optional[str]) -> Optional[Dict[str, Any]]:
    """A numeric canonical leaf, decimal-comma tolerant. None if not parseable
    (so a bad value is dropped, never asserted as garbage)."""
    try:
        n = float(str(raw).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None
    if path in INT_GEOM:
        return {"value": int(n)}
    leaf: Dict[str, Any] = {"value": n}
    if unit:
        leaf["unit"] = unit
    return leaf


def assign(fields: Dict[str, Any], path: str, leaf: Dict[str, Any]) -> None:
    parts = path.split(".")
    node = fields
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = leaf
