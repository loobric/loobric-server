# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""STEP Part 21 (ISO 10303-21) reader for ISO 13399 cutting-tool data.

A `.p21` file (the attribute file inside a GTC package, or a standalone export)
describes one cutting tool. We do NOT need the paywalled ISO 13399 PLIB
dictionary: the CIMSOURCE/ToolsUnited generator writes the **human-readable ISO
13399 mnemonic** into every value entity — `NUMERICAL_VALUE('DC', $, #119,
'6.35')`, `STRING_VALUE('GRADE', …)` — so a lightweight tokenizer plus a curated
mnemonic map gets us identity and geometry directly. (We do not parse the 3D BREP
geometry; that lives in separate `.stp` model files carried as media.)

Stdlib only — a pragmatic line-oriented tokenizer, not a full STEP kernel. These
generators write one entity instance per line, which is all this relies on.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from loobric_server.importers.base import CatalogRecordDraft

SOURCE = "gtc-import"
CLIENT_NAME = "import:gtc"

# ISO 13399 property mnemonic -> (canonical path, unit). Only mnemonics whose
# meaning is published (Sandvik/Mitsubishi refs) and that the server's Geometry
# model holds. Every other mnemonic is preserved in raw, never asserted.
_GEOM: Dict[str, Tuple[str, Optional[str]]] = {
    "DC":     ("geometry.diameter", "mm"),         # cutting diameter
    "DCONMS": ("geometry.shank_diameter", "mm"),   # connection (shank) diameter
    "DCON":   ("geometry.shank_diameter", "mm"),
    "OAL":    ("geometry.length", "mm"),           # overall length
    "APMX":   ("geometry.cutting_edge_height", "mm"),  # max depth of cut
    "LCF":    ("geometry.cutting_edge_height", "mm"),
    "ZEFF":   ("geometry.flutes", None),           # effective cutting edges
}
_INT_PATHS = {"geometry.flutes"}

# ISO item classification text -> canonical item_type (the ISO role).
_ITEM_TYPES = {
    "tool item": "tool_item", "cutting item": "cutting_item",
    "adaptive item": "adaptive_item", "assembly item": "assembly_item",
    "assembly": "assembly",
}

_ENTITY_RE = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$")


def parse(path: Union[str, Path]) -> List[CatalogRecordDraft]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    draft = parse_text(text)
    return [draft] if draft is not None else []


def parse_text(text: str, *, source_format: str = "p21") -> Optional[CatalogRecordDraft]:
    """Parse P21 text into one draft, or None if it carries no tool ITEM (e.g. a
    plain 3D-geometry STEP file fed by mistake)."""
    entities = _entities(text)
    item = _first(entities, "ITEM")
    if item is None:
        return None
    item_args = entities[item][1]

    fields: Dict[str, object] = {}
    raw: Dict[str, object] = {}

    name = _resolve_string(entities, _ref(item_args[0])) if len(item_args) >= 1 else None
    product_id = _qstr(item_args[1]) if len(item_args) >= 2 else None
    product_code = (_resolve_string(entities, _ref(item_args[2]))
                    if len(item_args) >= 3 else None)
    if name:
        fields["name"] = {"value": name}
    manufacturer = _manufacturer(entities)
    if manufacturer:
        fields["manufacturer"] = {"value": manufacturer}
    if product_code:
        fields["product_code"] = {"value": product_code}
    if product_id:
        raw["product_id"] = product_id

    item_type = _item_type(entities)
    if item_type:
        fields["item_type"] = {"value": item_type}

    # Geometry + the full readable mnemonic dump (raw, lossless).
    for eid, (typ, args) in entities.items():
        if typ not in ("NUMERICAL_VALUE", "STRING_VALUE") or not args:
            continue
        mnem = _qstr(args[0])
        value = _qstr(args[-1])
        if mnem is None or value is None:
            continue
        raw.setdefault("mnemonics", {})[mnem] = value
        spec = _GEOM.get(mnem)
        if spec and typ == "NUMERICAL_VALUE":
            leaf = _num_leaf(spec[0], value, spec[1])
            if leaf is not None:
                _assign(fields, spec[0], leaf)

    return CatalogRecordDraft(
        fields=fields, raw=raw, source_format=source_format,
        source_class=None, source_actor=SOURCE, client_name=CLIENT_NAME)


# -- entity tokenizer ---------------------------------------------------------

def _entities(text: str) -> Dict[int, Tuple[str, List[str]]]:
    out: Dict[int, Tuple[str, List[str]]] = {}
    for line in text.splitlines():
        m = _ENTITY_RE.match(line.strip())
        if m:
            out[int(m.group(1))] = (m.group(2), _split_args(m.group(3)))
    return out


def _split_args(s: str) -> List[str]:
    """Split an entity's top-level, comma-separated args, respecting nested
    parens/brackets and single-quoted strings (with '' escapes)."""
    out: List[str] = []
    buf: List[str] = []
    depth = 0
    in_q = False
    i = 0
    while i < len(s):
        c = s[i]
        if in_q:
            buf.append(c)
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":   # '' -> literal '
                    buf.append(s[i + 1]); i += 2; continue
                in_q = False
        elif c == "'":
            in_q = True; buf.append(c)
        elif c in "([":
            depth += 1; buf.append(c)
        elif c in ")]":
            depth -= 1; buf.append(c)
        elif c == "," and depth == 0:
            out.append("".join(buf).strip()); buf = []
        else:
            buf.append(c)
        i += 1
    if buf:
        out.append("".join(buf).strip())
    return out


def _qstr(token: str) -> Optional[str]:
    token = token.strip()
    if len(token) >= 2 and token[0] == "'" and token[-1] == "'":
        return token[1:-1].replace("''", "'")
    return None


def _ref(token: str) -> Optional[int]:
    token = token.strip()
    return int(token[1:]) if token.startswith("#") and token[1:].isdigit() else None


def _first(entities, typ: str) -> Optional[int]:
    for eid, (t, _args) in entities.items():
        if t == typ:
            return eid
    return None


def _resolve_string(entities, eid: Optional[int]) -> Optional[str]:
    """Resolve a STRING_WITH_LANGUAGE / MULTI_LANGUAGE_STRING ref to its text."""
    if eid is None:
        return None
    ent = entities.get(eid)
    if ent is None:
        return None
    typ, args = ent
    if typ == "STRING_WITH_LANGUAGE" and args:
        return _qstr(args[0])
    if typ == "MULTI_LANGUAGE_STRING" and args:
        return _resolve_string(entities, _ref(args[-1]))   # default string is last
    return None


def _manufacturer(entities) -> Optional[str]:
    eid = _first(entities, "ORGANIZATION")
    if eid is None:
        return None
    args = entities[eid][1]
    # ORGANIZATION ($, '<acronym>', '<name>', 'company', $, $) — prefer the name.
    name = _qstr(args[2]) if len(args) >= 3 else None
    return name or (_qstr(args[1]) if len(args) >= 2 else None)


def _item_type(entities) -> Optional[str]:
    for eid, (typ, args) in entities.items():
        if typ == "SPECIFIC_ITEM_CLASSIFICATION" and len(args) >= 2:
            role = _ITEM_TYPES.get((_qstr(args[1]) or "").lower())
            if role:
                return role
    return None


# -- helpers (shared shape with din4000) --------------------------------------

def _num_leaf(path: str, raw_value: str, unit: Optional[str]):
    try:
        num = float(str(raw_value).strip().replace(",", "."))
    except ValueError:
        return None
    if path in _INT_PATHS:
        return {"value": int(num)}
    leaf = {"value": num}
    if unit:
        leaf["unit"] = unit
    return leaf


def _assign(fields: dict, path: str, leaf: dict) -> None:
    parts = path.split(".")
    node = fields
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = leaf
