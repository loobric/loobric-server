# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""DIN 4000 importer — CSV and ToolsUnited XML (2013 & 2016) → catalog drafts.

Stdlib only (``csv``, ``xml.etree``). CSV and XML carry the identical DIN 4000
feature codes, so each format is a thin front-end producing a ``{code: value}``
dict; one shared mapper (:mod:`._codes`) turns those into canonical fields. The
whole source payload is kept on each draft for lossless preservation.
"""
from pathlib import Path
from typing import List, Union

from loobric_server.importers.base import CatalogRecordDraft
from loobric_server.importers.din4000 import _codes, _csv, _xml

# The declared actor for DIN 4000 imports; the server stamps
# ``asserted:din4000-import`` on every canonical field.
SOURCE = "din4000-import"
CLIENT_NAME = "import:din4000"


def parse(path: Union[str, Path]) -> List[CatalogRecordDraft]:
    """Parse a DIN 4000 export file into catalog-record drafts. Dispatches on
    extension (``.xml``/``.csv``), falling back to content sniffing."""
    data = Path(path).read_bytes()
    if _is_xml(path, data):
        rows = _xml.parse_xml(data)               # bytes: ET honors the XML decl
        fmt = "din4000-xml"
    else:
        rows = _csv.parse_csv(_decode(data))
        fmt = "din4000-csv"

    drafts: List[CatalogRecordDraft] = []
    for props in rows:
        nsm = props.get("NSM")
        drafts.append(CatalogRecordDraft(
            fields=_codes.to_fields(nsm, props),
            raw=props,
            source_format=fmt,
            source_class=nsm,
            source_actor=SOURCE,
            client_name=CLIENT_NAME,
        ))
    return drafts


def _is_xml(path: Union[str, Path], data: bytes) -> bool:
    name = str(path).lower()
    if name.endswith(".xml"):
        return True
    if name.endswith(".csv"):
        return False
    return data.lstrip()[:1] == b"<"


def _decode(data: bytes) -> str:
    """Decode CSV bytes, tolerating a BOM and the latin-1/cp1252 encodings German
    tool data sometimes uses (umlauts in descriptions)."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")
