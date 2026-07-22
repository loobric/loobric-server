# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Content-addressed blob store for canonical media bytes.

Tool records carry media as *references* in their canonical section (small,
provenance-tagged, shared truth — see docs/TOOL_SCHEMA.md §Media). The bytes
themselves (3D STEP models, 2D drawings, images) live here, out of the record
JSON, so they never bloat record fetches, the changes feed, or backups.

Blobs are addressed by the SHA-256 of their content (`sha256:<hex>`), so storing
identical bytes twice is a no-op and the reference is stable and verifiable. The
store is a plain directory tree; back it up alongside the database.
"""
import hashlib
from pathlib import Path
from typing import Tuple

from loobric_server.config import settings

_ALGO = "sha256"


def _root() -> Path:
    """The blob-store root, read from settings at call time so tests (and a
    reconfigured deployment) can redirect it."""
    root = Path(settings.media_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path_for(ref: str) -> Path:
    """Map a `sha256:<hex>` reference to its on-disk path (sharded by the first
    two hex chars to keep directories shallow)."""
    if ":" not in ref:
        raise ValueError("malformed media ref %r (expected '<algo>:<hex>')" % ref)
    _, digest = ref.split(":", 1)
    if not digest or not all(c in "0123456789abcdef" for c in digest):
        raise ValueError("malformed media ref %r" % ref)
    return _root() / digest[:2] / digest


def store_blob(data: bytes) -> Tuple[str, int]:
    """Store bytes content-addressed; return (ref, size). Idempotent — identical
    content yields the same ref and is written at most once."""
    digest = hashlib.new(_ALGO, data).hexdigest()
    ref = "%s:%s" % (_ALGO, digest)
    path = _path_for(ref)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)            # atomic publish
    return ref, len(data)


def blob_exists(ref: str) -> bool:
    try:
        return _path_for(ref).exists()
    except ValueError:
        return False


def blob_path(ref: str) -> Path:
    """Filesystem path for a stored blob (for streaming responses)."""
    return _path_for(ref)


def read_blob(ref: str) -> bytes:
    return _path_for(ref).read_bytes()
