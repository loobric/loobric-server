# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""DIN 4000 feature-code → canonical mapping, keyed by DIN 4000 class (NSM).

DIN 4000 describes a tool as a *Sachmerkmal-Leiste*: a fixed table of feature
codes (``A1``, ``B2``, ``C3``, ``J22`` …) for one object class. The codes are
**class-specific** — the same letter means different things in different DIN 4000
parts — so every mapping is keyed by the ``NSM`` class value. CSV and XML carry
the identical codes, so this one table serves all DIN 4000 front-ends.

Discipline: only codes whose meaning we can *verify* (cross-checked against the
human-readable description / order code and the published value) are mapped to
canonical fields. Every other code is preserved verbatim by the importer and
**never asserted** — a code we cannot pin to a meaning is left out, not guessed.

DIN 4000-82 (solid shank milling cutters / endmills). Mapping derived from a real
Kennametal export of article 6767731 — ``ENDMILL H1TE 1/16X1/8X1/8X1 1/2 S``, a
1/16″ (1.588 mm) 4-flute endmill — cross-checked against its description and
order code ``H1TE4SE0063R013HA_KCPM15``. The DIN 4000-82 standard text is
paywalled; codes that could not be pinned to a meaning (``B2``, ``B3``, ``C4``,
the ``D``/``F``/``H`` series, …) are deliberately unmapped and survive in the
preserved raw payload for promotion once a legend is available.
"""
from typing import Any, Dict, Optional, Tuple

# Class → the canonical geometry.shape the class itself declares. This is NOT
# inference from geometry (forbidden): the source's NSM field explicitly states
# the class, and reading that stated class is a legitimate assertion.
CLASS_SHAPE = {
    "DIN4000-82": "endmill",
}

# Per-class code → (canonical dotted-path, unit). Identity at the top level;
# dimensions under geometry. Units are SI (DIN 4000 is metric).
_DIN4000_82 = {
    "J23": ("name", None),
    "J3":  ("manufacturer", None),
    "J22": ("product_code", None),
    "A1":  ("geometry.diameter", "mm"),        # nominal/cutting diameter
    "C3":  ("geometry.shank_diameter", "mm"),  # shank diameter
    "B5":  ("geometry.length", "mm"),          # overall length
    "F21": ("geometry.flutes", None),          # number of flutes
}

CLASS_MAPS: Dict[str, Dict[str, Tuple[str, Optional[str]]]] = {
    "DIN4000-82": _DIN4000_82,
}

# Geometry paths parsed as numbers (decimal-comma tolerant); flutes as an int.
_FLOAT_PATHS = {"geometry.diameter", "geometry.shank_diameter", "geometry.length"}
_INT_PATHS = {"geometry.flutes"}


def supported(nsm: Optional[str]) -> bool:
    """Whether we have a verified mapping for this DIN 4000 class."""
    return nsm in CLASS_MAPS


def to_fields(nsm: Optional[str], props: Dict[str, str]) -> Dict[str, Any]:
    """Map a ``{code: value}`` payload to the canonical ``fields`` dict.

    Only mapped, non-empty codes are emitted; unknown classes yield ``{}`` (the
    caller still preserves the raw payload). ``geometry.shape`` is added from the
    class declaration, not from any dimension.
    """
    fields: Dict[str, Any] = {}
    for code, (path, unit) in CLASS_MAPS.get(nsm, {}).items():
        raw = props.get(code)
        if raw is None or str(raw).strip() == "":
            continue
        leaf = _leaf(path, raw, unit)
        if leaf is not None:
            _assign(fields, path, leaf)

    shape = CLASS_SHAPE.get(nsm)
    if shape is not None:
        _assign(fields, "geometry.shape", {"value": shape})
    return fields


def _leaf(path: str, raw: Any, unit: Optional[str]) -> Optional[Dict[str, Any]]:
    """Build one canonical leaf, parsing numbers tolerantly. A value that should
    be numeric but cannot be parsed is dropped (preserved in raw, never a bad
    canonical assertion)."""
    if path in _INT_PATHS:
        n = _num(raw)
        return None if n is None else {"value": int(n)}
    if path in _FLOAT_PATHS:
        n = _num(raw)
        if n is None:
            return None
        leaf = {"value": n}
        if unit:
            leaf["unit"] = unit
        return leaf
    return {"value": str(raw).strip()}


def _num(raw: Any) -> Optional[float]:
    """Parse a DIN 4000 numeric value, tolerating a decimal comma (``1,588`` in
    the 2016 XML vs ``1.588`` in CSV / 2013 XML). Returns None on non-numeric so
    the caller can drop it rather than assert a garbage value."""
    s = str(raw).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _assign(fields: Dict[str, Any], path: str, leaf: Dict[str, Any]) -> None:
    parts = path.split(".")
    node = fields
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = leaf
