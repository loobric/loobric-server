# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolSetRecord facade — an agnostic named collection, sectioned
(docs/TOOL_SCHEMA.md). NOT a FreeCAD library; a .fctl/Fusion lib/drawer is one
client's representation in clients.<name>.data.

Members carry a canonical, provenance-tagged `number` — the CAM side's durable
claim, only ever changed by an assert (MAPPING_PLAN.md §5.1). The machine
relationship is a setup (machine_set_maps, api/machine_set_maps.py), never a
field on the set; when a setup is active, reads return each member's derived
`state` and `observed` number alongside the untouched claim.
"""
import copy
from datetime import datetime, UTC
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.auth.doors import door
from loobric_server.database.schema import (
    User, ToolSetRecord as Row,
)
from loobric_server.audit import create_audit_log
from loobric_server.binding_v2 import (
    reconcile_set_membership, active_maps_for_set, bridge_requested_claims,
)
from loobric_server.contract import (
    ToolSet, ToolSetCanonical, Provenance, UNKNOWN, LaneViolation, reject_out_of_lane,
)

router = APIRouter(prefix="/api/v1/tool-set-records", tags=["tool-set-records"])

ASSERTABLE_PATHS = {"name"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _blank_canonical() -> dict:
    return {
        "name": {"value": None, "source": UNKNOWN},
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
    """The GET projection. When the set has an active setup, each member is
    classified against that machine's tool-table entries and the entry's
    observed number rides alongside — derived at read time, never persisted.
    The stored claim (`number`) is returned verbatim in both cases: observation
    overlays, it never overwrites (MAPPING_PLAN.md §5.1). A set with no active
    setup is returned unchanged — every number is simply its claim.

    A set may be active on several machines (the one-active constraint is per
    machine); the projection reconciles against the longest-active one, and the
    machine-scoped view (GET /machine-set-maps/status) is the
    unambiguous surface."""
    doc = _doc(row)
    maps = active_maps_for_set(db, row.user_id, row.id)
    if maps:
        result = reconcile_set_membership(db, row, maps[0].machine_id)
        doc["canonical"]["members"] = [
            {"tool_record_id": ms.tool_record_id, "number": ms.number,
             "observed": ms.observed, "state": ms.state}
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


# -- endpoints ----------------------------------------------------------------

@router.post("")
def create_set(payload: CreateRequest, db: Session = Depends(get_db),
               user: User = Depends(door("assert"))):
    clients = {}
    if payload.client:
        clients[payload.client] = {
            "client_version": payload.client_version or "",
            "client_item_id": payload.client_item_id,
            "created_at": _now(), "updated_at": _now(), "data": payload.data or {},
        }
    row = Row(canonical=_blank_canonical(), clients=clients,
              user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="CREATE",
                     entity_type="tool_set_record", entity_id=row.id)
    db.commit()
    return _response(row)


@router.get("")
def list_sets(db: Session = Depends(get_db),
              user: User = Depends(door("read"))):
    rows = db.query(Row).filter(Row.user_id == user.id).order_by(Row.created_at).all()
    return {"items": [_read_response(db, r) for r in rows]}


@router.get("/{record_id}")
def get_set(record_id: str, db: Session = Depends(get_db),
            user: User = Depends(door("read"))):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _read_response(db, row)


@router.delete("/{record_id}")
def delete_set(record_id: str, db: Session = Depends(get_db),
               user: User = Depends(door("delete"))):
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
                         user: User = Depends(door("sync"))):
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
                     user: User = Depends(door("assert"))):
    """Assert `name`. (The machine relationship is a setup —
    POST /api/v1/machine-set-maps — not a set field.)"""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if req.path not in ASSERTABLE_PATHS:
        raise HTTPException(status_code=400, detail="cannot assert %r" % req.path)
    canonical = copy.deepcopy(row.canonical)
    canonical[req.path] = {"value": req.value, "source": Provenance.asserted(req.actor)}
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="tool_set_record", entity_id=row.id,
                     changes={"path": req.path})
    db.commit()
    return _response(row)


@router.post("/{record_id}/members")
def set_members(record_id: str, req: MembersRequest, db: Session = Depends(get_db),
                user: User = Depends(door("assert"))):
    """Replace membership; MERGE numbers (MAPPING_PLAN.md §5.1).

    Membership is the CAM side's to replace. Numbers are durable claims: a
    supplied number is asserted; an OMITTED number on a member the set already
    holds keeps that member's stored claim — it is never nulled or overwritten
    by a push that simply didn't carry it (the round-trip laundering fix). A
    genuinely new member without a number is honestly unknown.

    If the set is active on a machine (a setup), freshly asserted claims are
    bridged against that machine's existing unbound entries — the CAM-first
    ordering of the number-match proposal (slice 0b); the machine push covers
    the machine-first ordering."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    stored = {m["tool_record_id"]: m.get("number")
              for m in (row.canonical.get("members") or [])}
    members = []
    for m in req.members:
        if m.number is not None:
            number = {"value": m.number, "source": Provenance.asserted(req.actor)}
        else:
            number = stored.get(m.tool_record_id) or {"value": None, "source": UNKNOWN}
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
    for map_row in active_maps_for_set(db, user.id, row.id):
        bridge_requested_claims(db, user, map_row.machine_id)
    db.commit()
    return _response(row)
