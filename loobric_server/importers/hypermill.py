# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""hyperMILL tool-database export reader (OPEN MIND `omtdx` XML).

`omtdx` nests `<tool name= type=>` inside a `<tools folder=…>` hierarchy; each
tool carries a flat list of `<param name= value=>` rows (and `tecsets`/`geometry`
we don't need). Manufacturer and ordering code are named params, so identity and
geometry come straight out. Stdlib `xml.etree` only.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Union

from loobric_server.importers._util import assign, num_leaf
from loobric_server.importers.base import CatalogRecordDraft

SOURCE = "hypermill-import"
CLIENT_NAME = "import:hypermill"

# omtdx param name -> (canonical path, unit).
_GEOM = {
    "toolDiameter": ("geometry.diameter", "mm"),
    "toolShaftDiameter": ("geometry.shank_diameter", "mm"),
    "toolTotalLength": ("geometry.length", "mm"),
    "cuttingLength": ("geometry.cutting_edge_height", "mm"),
    "cuttingEdges": ("geometry.flutes", None),
}
# omtdx tool @type -> canonical shape (the source's declared type).
_TYPE_SHAPE = {
    "endmill": "endmill", "ballmill": "endmill", "bullnosemill": "endmill",
    "torusmill": "endmill", "facemill": "facemill", "drill": "drill",
    "chamfermill": "chamfer",
}


def parse(path: Union[str, Path]) -> List[CatalogRecordDraft]:
    return parse_bytes(Path(path).read_bytes())


def parse_bytes(data: bytes) -> List[CatalogRecordDraft]:
    root = ET.fromstring(data)
    drafts: List[CatalogRecordDraft] = []
    for tool in root.iter("tool"):
        # direct param children only — not the tecset's feeds/speeds params.
        params = {p.get("name"): p.get("value")
                  for p in tool.findall("param") if p.get("name")}
        fields: Dict[str, object] = {}

        if tool.get("name"):
            fields["name"] = {"value": tool.get("name")}
        if params.get("manufacturer"):
            fields["manufacturer"] = {"value": params["manufacturer"]}
        if params.get("orderingCode"):
            fields["product_code"] = {"value": params["orderingCode"]}

        shape = _TYPE_SHAPE.get((tool.get("type") or "").lower())
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
            fields=fields, raw=params, source_format="hypermill",
            source_class=tool.get("type"),
            source_actor=SOURCE, client_name=CLIENT_NAME))
    return drafts
