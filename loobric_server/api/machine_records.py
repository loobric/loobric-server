# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Machine facade — a sectioned controller record (docs/TOOL_SCHEMA.md §7.5).

Follows the ToolInstanceRecord tracer exactly: responses are the three-section
shape, validated against loobric_server.contract before they leave the server; a client
writes ONLY its own section (`PUT .../clients/{name}`), lane-enforced by
loobric_server.contract.reject_out_of_lane (internal/canonical keys are a 400); canonical
changes only through the deliberate, audited `assert` door.

Difference from the instance tracer: a machine has NO `observe` endpoint. A
machine's own identity (name, controller_type, definition) is asserted by config
or a client — it is declared, never measured.
"""
import copy
from datetime import datetime, UTC
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.database.schema import User, MachineRecord as Row
from loobric_server.audit import create_audit_log
from loobric_server.contract import (
    Machine, MachineCanonical, Provenance, UNKNOWN,
    LaneViolation, reject_out_of_lane,
)

router = APIRouter(prefix="/api/v1/machine-records", tags=["machine-records"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _blank_canonical() -> dict:
    """A freshly-minted machine asserts nothing — its name is honestly unknown
    until asserted; controller_type/definition are optional and stay absent
    until asserted."""
    return {
        "name": {"value": None, "source": UNKNOWN},
    }


def _response(row: Row) -> dict:
    """Build the sectioned response and validate it against the contract — the
    server never emits a record that doesn't conform to its own schema."""
    doc = {
        "internal": {
            "id": row.id, "version": row.version,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
        },
        "canonical": row.canonical,
        "clients": row.clients,
    }
    Machine.model_validate(doc)
    return doc


def _owned(db: Session, user: User, record_id: str) -> Optional[Row]:
    return db.query(Row).filter(Row.id == record_id, Row.user_id == user.id).first()


def _validate_canonical(canonical: dict) -> None:
    try:
        MachineCanonical.model_validate(canonical)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid canonical: %s" % exc)


def _set_path(canonical: dict, path: str, field: dict) -> dict:
    """Return a copy of canonical with the dotted `path` leaf set to `field`."""
    out = copy.deepcopy(canonical)
    node = out
    parts = path.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
        if not isinstance(node, dict):
            raise HTTPException(status_code=400, detail="path %r is not a section" % path)
    node[parts[-1]] = field
    return out


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class CreateRequest(BaseModel):
    # optional initial client section (the creating client names itself here;
    # subsequent section writes name the client in the path instead)
    client: Optional[str] = None
    client_version: Optional[str] = None
    client_item_id: Optional[str] = None
    data: dict = {}


class AssertRequest(BaseModel):
    path: str
    value: Any = None
    unit: Optional[str] = None
    actor: str          # e.g. "linuxcnc" or "human@inbox"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("")
def create_machine(payload: CreateRequest, db: Session = Depends(get_db),
                   user: User = Depends(get_authenticated_user)):
    """Mint a machine. Canonical starts all-unknown (name only); an optional
    initial client section may be seeded. Canonical is populated only via the
    assert door thereafter."""
    clients = {}
    if payload.client:
        clients[payload.client] = {
            "client_version": payload.client_version or "",
            "client_item_id": payload.client_item_id,
            "created_at": _now(), "updated_at": _now(),
            "data": payload.data or {},
        }
    row = Row(canonical=_blank_canonical(), clients=clients,
              user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="CREATE",
                     entity_type="machine_record", entity_id=row.id)
    db.commit()
    return _response(row)


@router.get("")
def list_machines(db: Session = Depends(get_db),
                  user: User = Depends(get_authenticated_user)):
    rows = db.query(Row).filter(Row.user_id == user.id).order_by(Row.created_at).all()
    return {"items": [_response(r) for r in rows]}


@router.get("/{record_id}")
def get_machine(record_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_authenticated_user)):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _response(row)


@router.delete("/{record_id}")
def delete_machine(record_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_authenticated_user)):
    """Delete a machine and its tool-table entries (and their proposals). Tool
    instances are NOT deleted — only this machine and what it reported."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    from loobric_server.database.schema import (
        ToolTableEntryRecord as EntryRow, EntryProposal)
    entries = db.query(EntryRow).filter(
        EntryRow.user_id == user.id, EntryRow.machine_id == record_id).all()
    for entry in entries:
        db.query(EntryProposal).filter(EntryProposal.entry_id == entry.id).delete()
        db.delete(entry)
    db.delete(row)
    create_audit_log(session=db, user_id=user.id, operation="DELETE",
                     entity_type="machine_record", entity_id=record_id,
                     changes={"entries_removed": len(entries)})
    db.commit()
    return {"deleted": record_id, "entries_removed": len(entries)}


@router.put("/{record_id}/clients/{client}")
def write_client_section(record_id: str, client: str, payload: dict,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_authenticated_user)):
    """Routine sync: write THIS client's section. The client is named by the
    path; the body is the envelope (`client_version`, `client_item_id`) + opaque
    `data`. A body carrying `internal`/`canonical`/stray keys is a 400."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        write = reject_out_of_lane(payload)          # lane discipline
    except LaneViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    clients = copy.deepcopy(row.clients)
    existing = clients.get(client) or {}
    clients[client] = {
        "client_version": write.client_version,
        "client_item_id": write.client_item_id,
        "created_at": existing.get("created_at") or _now(),   # server-stamped
        "updated_at": _now(),
        "data": write.data,
    }
    row.clients = clients
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="SYNC",
                     entity_type="machine_record", entity_id=row.id,
                     changes={"client": client})
    db.commit()
    return _response(row)


@router.post("/{record_id}/assert")
def assert_canonical(record_id: str, req: AssertRequest,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_authenticated_user)):
    """Deliberately declare a canonical value (name, controller_type, the post
    definition). A machine's identity is declared, never measured — there is no
    observe door here. Audited; stamps source asserted:<actor>."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    field = {"value": req.value, "source": Provenance.asserted(req.actor)}
    if req.unit is not None:
        field["unit"] = req.unit
    canonical = _set_path(row.canonical, req.path, field)
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="machine_record", entity_id=row.id,
                     changes={"path": req.path, "source": field["source"]})
    db.commit()
    return _response(row)
