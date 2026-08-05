# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""Format importers: parse a vendor tool-data export into catalog records.

VENDORED from loobric-cli (loobric/importers, MIT) on 2026-08-05 so the
server's catalog-import endpoint can parse uploads — the web UI can't run
the CLI. The CLI keeps its own copy (offline parsing is a deliberate CLI
feature); keep the two in sync when either grows a format or a mapping.
The CLI's `run.py` network driver is deliberately NOT vendored — the
`/tool-catalog-records/import` endpoint is the server-side equivalent.

An importer is a *pure parse-and-map* step. It never opens a socket: it turns a
file into one or more :class:`CatalogRecordDraft` (canonical `fields` + the raw
source payload to preserve) — so parsing is offline, testable, and the network
concern lives in exactly one place (the import endpoint).

Importers create **ToolCatalogRecords only** (catalog *types*), with nominal
geometry the server stamps `asserted:<source>`. They never observe, never touch
instances or entries, and — critically — never *infer* a field the source did
not state. A code we cannot pin to a meaning is preserved verbatim, never
guessed (the "every imported tool became an endmill" failure the schema exists
to prevent).
"""
import re
from pathlib import Path
from typing import List, Union

from loobric_server.importers.base import CatalogRecordDraft, MediaFile

__all__ = ["CatalogRecordDraft", "MediaFile", "parse"]

# XML root element -> importer module name. Lets one `.xml` extension fan out to
# the ToolsUnited DIN 4000, SolidCAM, and hyperMILL formats.
_XML_ROOTS = {
    "tool-data": "din4000",     # ToolsUnited DIN 4000
    "results": "solidcam",      # SolidCAM <Results><Tools><Tool>
    "omtdx": "hypermill",       # OPEN MIND hyperMILL
}


def parse(path: Union[str, Path]) -> List[CatalogRecordDraft]:
    """Detect the format from the file and dispatch to the right importer.

    - ``.zip`` (or a PK header) → GTC package (ISO 13399, with media)
    - ``.p21`` / ``.stp`` / ``.step`` / an ``ISO-10303-21`` header → STEP P21
    - XML → by root element: DIN 4000 / SolidCAM / hyperMILL
    - ``.csv`` (or anything else) → DIN 4000
    """
    name = str(path).lower()
    head = Path(path).read_bytes()[:2048]
    if name.endswith(".zip") or head[:2] == b"PK":
        from loobric_server.importers import gtc
        return gtc.parse(path)
    if (name.endswith((".p21", ".stp", ".step"))
            or head.lstrip().startswith(b"ISO-10303-21")):
        from loobric_server.importers import p21
        return p21.parse(path)
    if name.endswith(".xml") or head.lstrip()[:1] == b"<":
        module = _XML_ROOTS.get(_xml_root_tag(head), "din4000")
        mod = __import__("loobric.importers." + module, fromlist=["parse"])
        return mod.parse(path)
    from loobric_server.importers import din4000
    return din4000.parse(path)


def _xml_root_tag(head: bytes) -> str:
    """The first element name (namespace/declaration/doctype stripped), lowercased."""
    text = head.decode("utf-8-sig", errors="replace")
    text = re.sub(r"<\?.*?\?>", "", text, flags=re.S)   # drop <?xml …?>
    text = re.sub(r"<!.*?>", "", text, flags=re.S)       # drop <!DOCTYPE …> / comments
    m = re.search(r"<([A-Za-z_][\w.\-]*)", text)
    return m.group(1).lower() if m else ""
