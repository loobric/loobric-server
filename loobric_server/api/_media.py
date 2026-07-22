# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Shared canonical-media operations, reused by the catalog and instance records.

A record's `media` is one provenance-tagged canonical Field whose value is a list
of MediaRef descriptors (docs/TOOL_SCHEMA.md §Media). Uploading stores the bytes
in the blob store and appends a reference (stamped asserted:<actor> — the client
never writes provenance); serving streams the bytes back; deleting drops the
reference. The server never parses the media.
"""
import copy
from typing import Tuple

from fastapi import HTTPException
from fastapi.responses import FileResponse

from loobric_server import media_store
from loobric_server.contract import MediaRef, Provenance


def _media_items(canonical: dict) -> list:
    return list((canonical.get("media") or {}).get("value") or [])


def append_media(canonical: dict, *, data: bytes, role: str, content_type: str,
                 filename: str, actor: str) -> Tuple[dict, dict]:
    """Store `data` in the blob store and append its reference to canonical.media.
    Returns (new_canonical, media_entry). De-dupes on (ref, role) so re-uploading
    the same bytes for the same role is a no-op append. Raises 400 on a malformed
    descriptor (e.g. an unknown role)."""
    ref, size = media_store.store_blob(data)
    entry = {"role": role, "ref": ref,
             "content_type": content_type or "application/octet-stream",
             "filename": filename, "size": size}
    try:
        MediaRef.model_validate(entry)          # clear 400 before any record write
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid media: %s" % exc)

    out = copy.deepcopy(canonical)
    items = [m for m in _media_items(out)
             if not (m.get("ref") == ref and m.get("role") == role)]
    items.append(entry)
    out["media"] = {"value": items, "source": Provenance.asserted(actor)}
    return out, entry


def remove_media(canonical: dict, ref: str, *, actor: str) -> dict:
    """Drop the reference `ref` from canonical.media (the blob bytes are left in
    place — content-addressed, possibly shared; GC is a separate concern). 404 if
    the record does not carry that reference."""
    items = _media_items(canonical)
    kept = [m for m in items if m.get("ref") != ref]
    if len(kept) == len(items):
        raise HTTPException(status_code=404, detail="media reference not found on record")
    out = copy.deepcopy(canonical)
    out["media"] = {"value": kept, "source": Provenance.asserted(actor)}
    return out


def serve(canonical: dict, ref: str) -> FileResponse:
    """Stream a referenced media file. 404 unless the record carries the reference
    and the blob exists."""
    match = next((m for m in _media_items(canonical) if m.get("ref") == ref), None)
    if match is None or not media_store.blob_exists(ref):
        raise HTTPException(status_code=404, detail="media not found")
    return FileResponse(
        media_store.blob_path(ref),
        media_type=match.get("content_type") or "application/octet-stream",
        filename=match.get("filename") or None)
