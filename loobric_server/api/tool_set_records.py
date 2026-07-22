# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolSetRecord facade — an agnostic named collection, sectioned
(docs/TOOL_SCHEMA.md). NOT a FreeCAD library; a .fctl/Fusion lib/drawer is one
client's representation in clients.<name>.data.

Members carry a canonical, provenance-tagged `number`. When the set is linked to
a machine (machine_id asserted), member numbers are inherited from that machine's
entries — the machine is observed fact, the set conforms.
"""
import copy
from datetime import datetime, UTC
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.database.schema import (
    User, ToolSetRecord as Row,
)
from loobric_server.audit import create_audit_log
from loobric_server.binding_v2 import reconcile_set_membership
from loobric_server.contract import (
    ToolSet, ToolSetCanonical, Provenance, UNKNOWN, LaneViolation, reject_out_of_lane,
)

router = APIRouter(prefix="/api/v1/tool-set-records", tags=["tool-set-records"])

ASSERTABLE_PATHS = {"name", "machine_id"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _blank_canonical() -> dict:
    return {
        "name": {"value": None, "source": UNKNOWN},
        "machine_id": {"value": None, "source": UNKNOWN},
        "members": [],
    }


def _doc(row: Row) -> dict:
    return {
        "internal": {
            "id": row.id, "version": row.version,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
        },
        "canonical": copy.deepcopy(row.canonical),
        "clients": row.clients,
    }


def _response(row: Row) -> dict:
    doc = _doc(row)
    ToolSet.model_validate(doc)
    return doc


def _read_response(db: Session, row: Row) -> dict:
    """The GET projection. For a machine-bound set, each member is classified
    against the machine's tool-table entries (loaded / requested / pending bind)
    and loaded members inherit the entry's observed tool_number — derived at read
    time, never persisted (docs/ROUNDTRIP.md). A non-machine-bound set is
    returned unchanged."""
    doc = _doc(row)
    if row.machine_id:
        result = reconcile_set_membership(db, row)
        doc["canonical"]["members"] = [
            {"tool_record_id": ms.tool_record_id, "number": ms.number,
             "state": ms.state}
            for ms in result.members
        ]
    ToolSet.model_validate(doc)
    return doc


def _owned(db: Session, user: User, record_id: str) -> Optional[Row]:
    return db.query(Row).filter(Row.id == record_id, Row.user_id == user.id).first()


def _validate_canonical(canonical: dict) -> None:
    try:
        ToolSetCanonical.model_validate(canonical)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid canonical: %s" % exc)


# -- requests -----------------------------------------------------------------

class CreateRequest(BaseModel):
    client: Optional[str] = None
    client_version: Optional[str] = None
    client_item_id: Optional[str] = None
    data: dict = {}


class AssertRequest(BaseModel):
    path: str
    value: Any = None
    actor: str


class MemberIn(BaseModel):
    tool_record_id: str
    number: Optional[int] = None


class MembersRequest(BaseModel):
    members: List[MemberIn]
    actor: str


class RefreshRequest(BaseModel):
    actor: Optional[str] = None


# -- endpoints ----------------------------------------------------------------

@router.post("")
def create_set(payload: CreateRequest, db: Session = Depends(get_db),
               user: User = Depends(get_authenticated_user)):
    clients = {}
    if payload.client:
        clients[payload.client] = {
            "client_version": payload.client_version or "",
            "client_item_id": payload.client_item_id,
            "created_at": _now(), "updated_at": _now(), "data": payload.data or {},
        }
    row = Row(machine_id=None, canonical=_blank_canonical(), clients=clients,
              user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="CREATE",
                     entity_type="tool_set_record", entity_id=row.id)
    db.commit()
    return _response(row)


@router.get("")
def list_sets(db: Session = Depends(get_db),
              user: User = Depends(get_authenticated_user)):
    rows = db.query(Row).filter(Row.user_id == user.id).order_by(Row.created_at).all()
    return {"items": [_read_response(db, r) for r in rows]}


@router.get("/{record_id}")
def get_set(record_id: str, db: Session = Depends(get_db),
            user: User = Depends(get_authenticated_user)):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _read_response(db, row)


@router.delete("/{record_id}")
def delete_set(record_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_authenticated_user)):
    """Delete a tool set. The member tool instances are NOT deleted — only the
    collection."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(row)
    create_audit_log(session=db, user_id=user.id, operation="DELETE",
                     entity_type="tool_set_record", entity_id=record_id)
    db.commit()
    return {"deleted": record_id}


@router.put("/{record_id}/clients/{client}")
def write_client_section(record_id: str, client: str, payload: dict,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_authenticated_user)):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        write = reject_out_of_lane(payload)
    except LaneViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    clients = copy.deepcopy(row.clients)
    existing = clients.get(client) or {}
    clients[client] = {
        "client_version": write.client_version,
        "client_item_id": write.client_item_id,
        "created_at": existing.get("created_at") or _now(),
        "updated_at": _now(), "data": write.data,
    }
    row.clients = clients
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="SYNC",
                     entity_type="tool_set_record", entity_id=row.id,
                     changes={"client": client})
    db.commit()
    return _response(row)


@router.post("/{record_id}/assert")
def assert_canonical(record_id: str, req: AssertRequest,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_authenticated_user)):
    """Assert `name` or the `machine_id` link. Linking a machine makes the set
    machine-bound (its member numbers are then inherited from the machine's entries)."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if req.path not in ASSERTABLE_PATHS:
        raise HTTPException(status_code=400, detail="cannot assert %r" % req.path)
    canonical = copy.deepcopy(row.canonical)
    canonical[req.path] = {"value": req.value, "source": Provenance.asserted(req.actor)}
    _validate_canonical(canonical)
    row.canonical = canonical
    if req.path == "machine_id":
        row.machine_id = req.value
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="tool_set_record", entity_id=row.id,
                     changes={"path": req.path})
    db.commit()
    return _response(row)


@router.post("/{record_id}/members")
def set_members(record_id: str, req: MembersRequest, db: Session = Depends(get_db),
                user: User = Depends(get_authenticated_user)):
    """Replace membership. A supplied number is asserted; an omitted one is
    unknown (until inherited from a machine's entries, if the set is machine-bound)."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    members = []
    for m in req.members:
        number = ({"value": m.number, "source": Provenance.asserted(req.actor)}
                  if m.number is not None else {"value": None, "source": UNKNOWN})
        members.append({"tool_record_id": m.tool_record_id, "number": number})
    canonical = copy.deepcopy(row.canonical)
    canonical["members"] = members
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="MEMBERS",
                     entity_type="tool_set_record", entity_id=row.id,
                     changes={"count": len(members)})
    db.commit()
    return _response(row)


@router.post("/{record_id}/refresh")
def refresh_from_machine(record_id: str, req: RefreshRequest = RefreshRequest(),
                         db: Session = Depends(get_db),
                         user: User = Depends(get_authenticated_user)):
    """Refresh a machine-bound set from its machine — a MERGE, not a replace.

    This is the MACHINE-DRIVEN counterpart to set_members (POST /members, the
    human "replace membership" operation). It runs `reconcile_set_membership`
    (ROUNDTRIP_FIXES S1) and writes back what the machine observes:

    - **loaded** members inherit the bound entry's observed `tool_number`
      (observed provenance), persisted into canonical;
    - **requested** members (no machine entry yet) are PRESERVED with their
      asserted-preference / unknown number — never deleted;
    - **pending bind** members surface the proposed entry's observed number.

    The machine is authoritative for numbers/offsets, NEVER for membership: the
    member set is conserved (no additions, no deletions). Ambiguities surfaced by
    the engine (e.g. an observed number colliding with an asserted preference)
    are returned under `ambiguities` rather than silently renumbered. 400 when
    the set is not machine-bound (there is nothing to refresh against)."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if not row.machine_id:
        raise HTTPException(status_code=400,
                            detail="set is not machine-bound; nothing to refresh")
    result = reconcile_set_membership(db, row)
    canonical = copy.deepcopy(row.canonical)
    canonical["members"] = [
        {"tool_record_id": ms.tool_record_id, "number": ms.number}
        for ms in result.members
    ]
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="REFRESH",
                     entity_type="tool_set_record", entity_id=row.id,
                     changes={"count": len(result.members),
                              "ambiguities": len(result.ambiguities),
                              "actor": req.actor})
    db.commit()
    # A refresh report, not a bare record: the merged set plus any ambiguities
    # the engine surfaced (kept out of the ToolSet doc, which forbids extras).
    return {"set": _read_response(db, row), "ambiguities": result.ambiguities}
