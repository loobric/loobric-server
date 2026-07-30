# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Setups (machine_set_maps) — the transitory machine↔set relationship
(MAPPING_PLAN.md). Internal entity, user-facing verbs: users say
`loobric use-set <machine> <set>`; nobody sees the noun "machine_set_map".

A bare association row: identity, lifecycle, attribution. No tool data, no
stored reconciliation, no decisions. Activating a set on a machine atomically
ends the machine's prior active setup (one active per machine — DB constraint);
ended rows are never deleted, they ARE the machine's setup history.

Doors: lifecycle rides `bind` (grilled & locked 2026-07-29, MAPPING_PLAN §10
Q3) — an operator-side adjudication about a specific machine. Agent keys
(read sync assert) and bare controller sync keys (read sync observe) can never
switch setups. The derived view (GET /status) is `read`.
"""
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db
from loobric_server.auth.doors import door
from loobric_server.database.schema import (
    User, MachineSetMap as Row, ToolSetRecord,
)
from loobric_server.audit import create_audit_log
from loobric_server.binding_v2 import (
    active_map_for_machine, bridge_requested_claims, reconcile_machine,
)

router = APIRouter(prefix="/api/v1/machine-set-maps", tags=["machine-set-maps"])


def _iso(value) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


def _response(row: Row) -> dict:
    return {
        "id": row.id,
        "machine_id": row.machine_id,
        "tool_set_id": row.tool_set_id,
        "status": row.status,
        "activated_at": _iso(row.activated_at),
        "ended_at": _iso(row.ended_at),
        "activated_by": row.created_by,
        "activated_key": row.activated_key,
        "ended_by": row.ended_by,
        "ended_key": row.ended_key,
        "version": row.version,
    }


def _key_id(request: Request) -> Optional[str]:
    return getattr(request.state, "api_key_id", None)


def _end(row: Row, user: User, key_id: Optional[str]) -> None:
    row.status = "ended"
    row.ended_at = datetime.now(UTC)
    row.ended_by = user.id
    row.ended_key = key_id
    row.version += 1
    row.updated_by = user.id


# -- requests -----------------------------------------------------------------

class ActivateRequest(BaseModel):
    machine_id: str
    tool_set_id: str


# -- endpoints ----------------------------------------------------------------

@router.post("")
def activate(payload: ActivateRequest, request: Request,
             db: Session = Depends(get_db),
             user: User = Depends(door("bind"))):
    """`use-set`: make `tool_set_id` the machine's active setup.

    Atomically ends any prior active setup for the machine (its row survives as
    history). Activating the already-active set is a no-op returning the
    existing row. Changes NOTHING on either side — no entry, no binding, no
    member, no number (MAPPING_PLAN.md invariant 7); the only other effect is
    the CAM-first proposal bridge: existing unbound entries the newly active
    set claims by number get their elevated-confidence proposals now instead of
    at the machine's next push."""
    set_row = db.query(ToolSetRecord).filter(
        ToolSetRecord.id == payload.tool_set_id,
        ToolSetRecord.user_id == user.id).first()
    if set_row is None:
        raise HTTPException(status_code=404, detail="tool set not found")

    key_id = _key_id(request)
    current = active_map_for_machine(db, user.id, payload.machine_id)
    if current is not None:
        if current.tool_set_id == payload.tool_set_id:
            return _response(current)
        _end(current, user, key_id)
        create_audit_log(session=db, user_id=user.id, operation="END",
                         entity_type="machine_set_map", entity_id=current.id,
                         changes={"machine_id": current.machine_id,
                                  "tool_set_id": current.tool_set_id,
                                  "reason": "replaced"})

    row = Row(machine_id=payload.machine_id, tool_set_id=payload.tool_set_id,
              status="active", activated_at=datetime.now(UTC),
              activated_key=key_id,
              user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="ACTIVATE",
                     entity_type="machine_set_map", entity_id=row.id,
                     changes={"machine_id": row.machine_id,
                              "tool_set_id": row.tool_set_id})
    bridge_requested_claims(db, user, payload.machine_id)
    db.commit()
    return _response(row)


@router.post("/{record_id}/end")
def end(record_id: str, request: Request, db: Session = Depends(get_db),
        user: User = Depends(door("bind"))):
    """`use-set --none`: end a setup without a replacement. Idempotent on an
    already-ended row. The row survives as history; nothing else changes."""
    row = db.query(Row).filter(Row.id == record_id,
                               Row.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if row.status == "ended":
        return _response(row)
    _end(row, user, _key_id(request))
    create_audit_log(session=db, user_id=user.id, operation="END",
                     entity_type="machine_set_map", entity_id=row.id,
                     changes={"machine_id": row.machine_id,
                              "tool_set_id": row.tool_set_id})
    db.commit()
    return _response(row)


@router.get("")
def list_maps(machine_id: Optional[str] = None, status: Optional[str] = None,
              db: Session = Depends(get_db),
              user: User = Depends(door("read"))):
    """Setup rows, newest first: the active setup (status=active) or a
    machine's setup history."""
    q = db.query(Row).filter(Row.user_id == user.id)
    if machine_id:
        q = q.filter(Row.machine_id == machine_id)
    if status:
        q = q.filter(Row.status == status)
    rows = q.order_by(Row.activated_at.desc()).all()
    return {"items": [_response(r) for r in rows]}


@router.get("/status")
def setup_status(machine_id: str, db: Session = Depends(get_db),
                 user: User = Depends(door("read"))):
    """The machine's derived setup view (MAPPING_PLAN.md §5.4): `ready`,
    claims, notes. Computed at read time; stores nothing. With no active
    setup: active=False and empty lists — a display, never an error. (The
    path says `status`, the ratified user-facing word — the internal engine
    name `reconcile_machine` stays developer-side per the glossary.)"""
    return reconcile_machine(db, user, machine_id)
