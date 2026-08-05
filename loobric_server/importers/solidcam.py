# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""SolidCAM tool-export reader (`<Results><Tools><Tool>` XML).

SolidCAM exports a self-describing XML: each `<Tool Type=… SubType=…>` carries a
flat list of `<param name= value=>` rows. Identity and geometry come straight out;
the manufacturer rides in a free-text `message2` ("company code: KH - Kennametal").
Stdlib `xml.etree` only.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Union

from loobric_server.importers._util import assign, num_leaf
from loobric_server.importers.base import CatalogRecordDraft

SOURCE = "solidcam-import"
CLIENT_NAME = "import:solidcam"

# SolidCAM param name -> (canonical path, unit).
_GEOM = {
    "diameter": ("geometry.diameter", "mm"),
    "arbor diameter": ("geometry.shank_diameter", "mm"),
    "total length": ("geometry.length", "mm"),
    "cutting edge length": ("geometry.cutting_edge_height", "mm"),
    "number of teeth": ("geometry.flutes", None),
}
# SolidCAM SubType -> canonical shape (the source's declared type).
_SUBTYPE_SHAPE = {
    "endmill": "endmill", "ballnosedmill": "endmill", "bullnosedmill": "endmill",
    "facemill": "facemill", "drill": "drill", "chamfermill": "chamfer",
}


def parse(path: Union[str, Path]) -> List[CatalogRecordDraft]:
    return parse_bytes(Path(path).read_bytes())


def parse_bytes(data: bytes) -> List[CatalogRecordDraft]:
    root = ET.fromstring(data)
    drafts: List[CatalogRecordDraft] = []
    for tool in root.iter("Tool"):
        params = {p.get("name"): p.get("value")
                  for p in tool.iter("param") if p.get("name")}
        fields: Dict[str, object] = {}

        # @UserType is "<order>_<name>"; strip the leading order-number prefix.
        name = re.sub(r"^\d+_", "", tool.get("UserType") or "").strip()
        if name:
            fields["name"] = {"value": name}
        manufacturer = _manufacturer(params)
        if manufacturer:
            fields["manufacturer"] = {"value": manufacturer}
        product_code = params.get("description") or _after_colon(params.get("message1"))
        if product_code:
            fields["product_code"] = {"value": product_code}

        shape = _SUBTYPE_SHAPE.get((tool.get("SubType") or "").lower())
        if shape:
            assign(fields, "geometry.shape", {"value": shape})
        for pname, (path_, unit) in _GEOM.items():
            val = params.get(pname)
            if val in (None, ""):
                continue
            leaf = num_leaf(path_, val, unit)
            if leaf is not None:
                assign(fields, path_, leaf)

        drafts.append(CatalogRecordDraft(
            fields=fields, raw=params, source_format="solidcam",
            source_class=tool.get("SubType"),
            source_actor=SOURCE, client_name=CLIENT_NAME))
    return drafts


def _manufacturer(params: Dict[str, str]) -> Optional[str]:
    """message2 is "company code: <acronym> - <name>" — take the name."""
    msg = params.get("message2") or ""
    if " - " in msg:
        return msg.split(" - ", 1)[1].strip() or None
    return None


def _after_colon(msg: Optional[str]) -> Optional[str]:
    if msg and ":" in msg:
        return msg.split(":", 1)[1].strip() or None
    return None
