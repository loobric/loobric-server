# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""DIN 4000 XML front-end: a ToolsUnited tool-data document → ``{code: value}``.

Handles both editions seen in the wild — the 2013 ``DIN_4000_Schema.dtd`` and the
2016 ``DIN_4000_Schema_2015.dtd`` — with one reader. They differ only in the
``Main-Data`` block (``ID21002`` vs ``PrimaryId``/``CustomerMaterialId``/
``NormVersion``) and in decimal format (point vs comma); both share the identical
``Category-Data``/``Property-Data`` → ``PropertyName``/``Value`` model that
carries the feature codes, so the parse is the same and number-format tolerance
lives in the shared mapper.

Stdlib ``xml.etree.ElementTree`` only. The ``<!DOCTYPE … SYSTEM "https://…">``
references an external DTD; ElementTree's parser does not fetch it (no network),
so parsing is offline and self-contained.
"""
import xml.etree.ElementTree as ET
from typing import Dict, List, Union


def parse_xml(data: Union[bytes, str]) -> List[Dict[str, str]]:
    root = ET.fromstring(data)
    out: List[Dict[str, str]] = []
    for tool in root.iter("Tool"):
        record: Dict[str, str] = {}
        # Category-Data (NSM/BLD — the class) and Property-Data (the features)
        # share the same PropertyName/Value shape.
        for pd in list(tool.iter("Category-Data")) + list(tool.iter("Property-Data")):
            code = pd.findtext("PropertyName")
            value = pd.findtext("Value")
            if code and code.strip():
                record[code.strip()] = (value or "").strip()
        # Manufacturer is a named Main-Data element in both editions; fall back to
        # it if the J3 feature code is absent.
        main = tool.find("Main-Data")
        if main is not None:
            manufacturer = main.findtext("Manufacturer")
            if manufacturer and manufacturer.strip():
                record.setdefault("J3", manufacturer.strip())
        out.append(record)
    return out
