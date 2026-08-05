# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""GTC (Generic Tool Catalog) package reader — the ISO 13399 distribution format.

A GTC package is a ZIP carrying, per product: an attribute `.p21` (ISO 13399
cutting-tool data) plus 3D STEP models, drawings, and images. This one reader
covers both layouts seen in the wild:

- **GTC 2.x** (`package_assortment.xml`, `product_data_files/*.p21`,
  `product_3d_models_detailed/*.stp`, `product_pictures/*`, …).
- **GTC 2017 / ToolsUnited "TU"** — each file individually inner-zipped
  (`…/KH_6676918.p21.zip`), `Documents/Brands/TU/…` paths.

It builds one flat `{path: bytes}` map (transparently unwrapping the GTC17 inner
zips), finds the attribute `.p21` and parses it (loobric.importers.p21 —
identity + geometry from readable mnemonics), then collects the product's media
files (STEP models, images, logo) onto the draft for upload as canonical media.
The 3D BREP geometry itself is never parsed — it is carried, not interpreted.
"""
import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Union

from loobric_server.importers import p21
from loobric_server.importers.base import CatalogRecordDraft, MediaFile

SOURCE = "gtc-import"
CLIENT_NAME = "import:gtc"

# GTC generic class id -> the shape the class declares (read, not inferred). A
# small verified set; unknown classes leave shape unset.
_CLASS_SHAPE = {
    "MILSQS": "endmill",     # square-end solid milling cutter
    "MILBNS": "endmill",     # ball-nose solid milling cutter
}

_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".bmp": "image/bmp"}
_MODEL_TYPES = {".stp": "model/step", ".step": "model/step", ".p21": "model/step"}


def parse(path: Union[str, Path]) -> List[CatalogRecordDraft]:
    with zipfile.ZipFile(path) as zf:
        files = _flatten(zf)
    return _drafts_from_files(files)


def _flatten(zf: zipfile.ZipFile) -> Dict[str, bytes]:
    """Read every member into a {path: bytes} map, unwrapping GTC17's per-file
    inner zips (`foo.ext.zip` -> `foo.ext`) so both layouts look the same."""
    out: Dict[str, bytes] = {}
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        data = zf.read(name)
        if name.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    for inner_name in inner.namelist():
                        if not inner_name.endswith("/"):
                            out[inner_name] = inner.read(inner_name)
                continue
            except zipfile.BadZipFile:
                pass
        out[name] = data
    return out


def _drafts_from_files(files: Dict[str, bytes]) -> List[CatalogRecordDraft]:
    p21_name = _find(files, lambda n: n.lower().endswith(".p21"))
    if p21_name is None:
        return []
    text = files[p21_name].decode("utf-8-sig", errors="replace")
    draft = p21.parse_text(text, source_format="gtc")
    if draft is None:
        return []

    # shape + class from the assortment (GTC 2.x); identity/geometry already from
    # the p21. The p21 has no readable shape, so the GTC class supplies it.
    assortment = _find(files, lambda n: n.lower().endswith("package_assortment.xml"))
    if assortment is not None:
        gtc_class, unit_system = _read_assortment(files[assortment])
        if gtc_class:
            draft.source_class = gtc_class
            draft.raw["gtc_generic_class_id"] = gtc_class
            shape = _CLASS_SHAPE.get(gtc_class)
            if shape:
                draft.fields.setdefault("geometry", {})["shape"] = {"value": shape}

    draft.media = _collect_media(files)
    return [draft]


def _collect_media(files: Dict[str, bytes]) -> List[MediaFile]:
    """Gather the product's own media (models, pictures, logo). Class-level assets
    (class_icons/, class_drawings/, the hierarchy XML, disclaimers, package logo)
    are skipped — they describe the catalog, not this tool."""
    media: List[MediaFile] = []
    for name, data in files.items():
        low = name.lower()
        ext = Path(low).suffix
        role: Optional[str] = None
        if ext in (".stp", ".step") and "p21" not in low:
            role = "model_3d_basic" if "basic" in low else "model_3d"
            ctype = "model/step"
        elif ext in _IMAGE_TYPES and ("product_pictures" in low or "/draw" in low):
            role, ctype = "image", _IMAGE_TYPES[ext]
        elif ext in _IMAGE_TYPES and ("product_brand_logos" in low or "/logo" in low):
            role, ctype = "logo", _IMAGE_TYPES[ext]
        if role is None:
            continue
        media.append(MediaFile(role=role, filename=Path(name).name, data=data,
                               content_type=ctype))
    # Deterministic order: detailed model, basic model, then the rest by name.
    order = {"model_3d": 0, "model_3d_basic": 1, "image": 2, "logo": 3}
    media.sort(key=lambda m: (order.get(m.role, 9), m.filename))
    return media


def _read_assortment(data: bytes):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None, None
    gtc_class = _text(root, "gtc_generic_class_id")
    unit_system = _text(root, "unit_system")
    return gtc_class, unit_system


def _text(root, tag: str) -> Optional[str]:
    """First descendant element whose tag (namespace-stripped) matches."""
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag and el.text:
            return el.text.strip()
    return None


def _find(files: Dict[str, bytes], pred) -> Optional[str]:
    for name in files:
        if pred(name):
            return name
    return None
