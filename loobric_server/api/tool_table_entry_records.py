# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolTableEntryRecord facade — a machine entry, sectioned (docs/TOOL_SCHEMA.md).

Like the instance tracer, plus the install-once invariant: a physical instance
is in at most one entry, globally. The hard guarantee is the UNIQUE index on the
`bound_instance_id` column; the bind endpoint adds the friendly experience —
a 409 naming where the tool already lives, and an atomic `move`.
"""
import copy
from datetime import datetime, UTC
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.database.schema import (
    User, ToolTableEntryRecord as Row, ToolInstanceRecord as InstanceRow,
)
from loobric_server.audit import create_audit_log
from loobric_server.binding_v2 import (
    close_open_proposal_on_bind, requested_members_by_number,
    propose_for_requested_entry,
)
from loobric_server.contract import (
    ToolTableEntry, EntryCanonical, Provenance, UNKNOWN,
    LaneViolation, reject_out_of_lane,
)

router = APIRouter(prefix="/api/v1/tool-table-entry-records", tags=["tool-table-entries"])

# A machine may only OBSERVE these entry facts; the binding is set via /bind.
# `description` is the table comment the machine reports (observed table state).
OBSERVABLE_PATHS = {"tool_number", "description",
                    "offsets.diameter", "offsets.z", "offsets.x", "offsets.y"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _blank_canonical() -> dict:
    return {
        "tool_number": {"value": None, "source": UNKNOWN},
        "bound_instance_id": {"value": None, "source": UNKNOWN},
        "offsets": {},
    }


def _response(row: Row) -> dict:
    doc = {
        "internal": {
            "id": row.id, "machine_id": row.machine_id, "version": row.version,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
        },
        "canonical": row.canonical,
        "clients": row.clients,
    }
    ToolTableEntry.model_validate(doc)
    return doc


def _owned(db: Session, user: User, record_id: str) -> Optional[Row]:
    return db.query(Row).filter(Row.id == record_id, Row.user_id == user.id).first()


def _validate_canonical(canonical: dict) -> None:
    try:
        EntryCanonical.model_validate(canonical)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid canonical: %s" % exc)


def _set_path(canonical: dict, path: str, field: dict) -> dict:
    out = copy.deepcopy(canonical)
    node = out
    parts = path.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = field
    return out


def _entry_label(row: Row) -> str:
    n = (row.canonical.get("tool_number") or {}).get("value")
    return "machine %s entry %s" % (row.machine_id[:8], n if n is not None else "?")


# -- requests -----------------------------------------------------------------

class CreateRequest(BaseModel):
    machine_id: str
    client: Optional[str] = None
    client_version: Optional[str] = None
    client_item_id: Optional[str] = None
    data: dict = {}


class ObserveRequest(BaseModel):
    path: str
    value: Any = None
    unit: Optional[str] = None
    client: str
    machine: str


class BindRequest(BaseModel):
    instance_id: Optional[str] = None   # None => mint a new instance from this entry
    actor: str = "human@inbox"
    move: bool = False      # if the instance is installed elsewhere, relocate it
    name: Optional[str] = None          # caller-supplied name when minting (the UI's parsed label)


# -- endpoints ----------------------------------------------------------------

@router.post("")
def create_entry(payload: CreateRequest, db: Session = Depends(get_db),
                 user: User = Depends(get_authenticated_user)):
    clients = {}
    if payload.client:
        clients[payload.client] = {
            "client_version": payload.client_version or "",
            "client_item_id": payload.client_item_id,
            "created_at": _now(), "updated_at": _now(), "data": payload.data or {},
        }
    row = Row(machine_id=payload.machine_id, bound_instance_id=None,
              canonical=_blank_canonical(), clients=clients,
              user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="CREATE",
                     entity_type="tool_table_entry_record", entity_id=row.id)
    db.commit()
    return _response(row)


class EntryIn(BaseModel):
    tool_number: int
    description: Optional[str] = None  # the tool-table comment (the machine's label)
    offsets: dict = {}          # plain values + optional <key>_unit, e.g. {"diameter": 6.35, "diameter_unit": "mm"}
    data: dict = {}             # the client section's opaque payload
    client_item_id: Optional[str] = None


class EntrySyncRequest(BaseModel):
    machine_id: str
    client: str                 # e.g. "linuxcnc"
    machine_name: str           # observation source: observed:<client>@<machine_name>
    client_version: str = ""
    mode: Literal["merge", "snapshot"] = "merge"
    force: bool = False
    entries: List[EntryIn]


@router.post("/sync")
def sync_entries(req: EntrySyncRequest, db: Session = Depends(get_db),
               user: User = Depends(get_authenticated_user)):
    """The machine-table push: upsert a machine's entries by tool_number in one
    call. Each entry's number+offsets are OBSERVED (the machine measured them)
    and the client section is written. mode=snapshot reconciles away entries
    absent from the payload (the controller is authoritative), guarded against a
    mass-wipe. Bindings survive an update; a removed entry's proposals are dropped.
    """
    existing = {}
    for r in db.query(Row).filter(Row.user_id == user.id,
                                  Row.machine_id == req.machine_id).all():
        tn = (r.canonical.get("tool_number") or {}).get("value")
        if tn is not None:
            existing[tn] = r
    src = Provenance.observed(req.client, req.machine_name)

    if req.mode == "snapshot" and not req.force and existing:
        present = {s.tool_number for s in req.entries}
        doomed = [tn for tn in existing if tn not in present]
        if doomed and (not req.entries or len(doomed) * 2 > len(existing)):
            raise HTTPException(status_code=409,
                detail="snapshot would remove %d of %d entries — refusing as a likely "
                       "partial read; resend with force=true if intended"
                       % (len(doomed), len(existing)))

    items = []
    created = []
    present = set()
    for s in req.entries:
        present.add(s.tool_number)
        row = existing.get(s.tool_number)
        if row is None:
            row = Row(machine_id=req.machine_id, bound_instance_id=None,
                      canonical=_blank_canonical(), clients={},
                      user_id=user.id, created_by=user.id, updated_by=user.id)
            db.add(row)
            db.flush()
            created.append(row)
        canonical = copy.deepcopy(row.canonical)
        canonical["tool_number"] = {"value": s.tool_number, "source": src}
        if s.description is not None:
            canonical["description"] = {"value": s.description, "source": src}
        offsets = canonical.setdefault("offsets", {})
        for key, value in s.offsets.items():
            if key.endswith("_unit"):
                continue
            field = {"value": value, "source": src}
            unit = s.offsets.get(key + "_unit")
            if unit:
                field["unit"] = unit
            offsets[key] = field
        _validate_canonical(canonical)
        row.canonical = canonical
        clients = copy.deepcopy(row.clients)
        existing_sec = clients.get(req.client) or {}
        clients[req.client] = {
            "client_version": req.client_version,
            "client_item_id": s.client_item_id,
            "created_at": existing_sec.get("created_at") or _now(),
            "updated_at": _now(), "data": s.data,
        }
        row.clients = clients
        row.version += 1
        row.updated_by = user.id
        items.append(row)

    removed = []
    if req.mode == "snapshot":
        from loobric_server.database.schema import EntryProposal
        for tn, row in existing.items():
            if tn in present:
                continue
            db.query(EntryProposal).filter(EntryProposal.entry_id == row.id).delete()
            db.delete(row)
            removed.append(tn)

    # ROUNDTRIP_FIXES Fix 2 / S3 — the request-aware binding bridge: a tool
    # freshly mounted at a requested pocket should turn into a binding. For each
    # entry CREATED + still UNBOUND in this push, open a request-aware proposal
    # (number match to a machine-bound set's requested member, elevated
    # confidence) or fall back to the geometry heuristic, exactly as before.
    # Computed before any proposal is added so the requested members are read off
    # the pre-bridge state (a new proposal would otherwise flip them to pending).
    if created:
        requested = requested_members_by_number(db, user, req.machine_id)
        for row in created:
            if row.bound_instance_id is None:
                propose_for_requested_entry(db, user, row, requested)

    create_audit_log(session=db, user_id=user.id, operation="SYNC_TABLE",
                     entity_type="tool_table_entry_record", entity_id=req.machine_id,
                     changes={"client": req.client, "count": len(req.entries),
                              "removed": removed})
    db.commit()
    return {"items": [_response(r) for r in items], "removed_tool_numbers": removed}


@router.get("")
def list_entries(machine_id: Optional[str] = None, db: Session = Depends(get_db),
                 user: User = Depends(get_authenticated_user)):
    q = db.query(Row).filter(Row.user_id == user.id)
    if machine_id:
        q = q.filter(Row.machine_id == machine_id)
    return {"items": [_response(r) for r in q.order_by(Row.created_at).all()]}


@router.get("/{record_id}")
def get_entry(record_id: str, db: Session = Depends(get_db),
              user: User = Depends(get_authenticated_user)):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _response(row)


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
                     entity_type="tool_table_entry_record", entity_id=row.id,
                     changes={"client": client})
    db.commit()
    return _response(row)


@router.post("/{record_id}/observe")
def observe_canonical(record_id: str, req: ObserveRequest,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_authenticated_user)):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if req.path not in OBSERVABLE_PATHS:
        raise HTTPException(status_code=400,
                            detail="%r is not observable on a entry" % req.path)
    field = {"value": req.value, "source": Provenance.observed(req.client, req.machine)}
    if req.unit is not None:
        field["unit"] = req.unit
    canonical = _set_path(row.canonical, req.path, field)
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="OBSERVE",
                     entity_type="tool_table_entry_record", entity_id=row.id,
                     changes={"path": req.path, "source": field["source"]})
    db.commit()
    return _response(row)


def _set_binding(row: Row, instance_id: Optional[str], actor: str) -> None:
    field = ({"value": instance_id, "source": Provenance.asserted(actor)}
             if instance_id else {"value": None, "source": UNKNOWN})
    row.canonical = _set_path(row.canonical, "bound_instance_id", field)
    row.bound_instance_id = instance_id          # the unique-indexed column
    row.version += 1


def _mint_instance_from_entry(db: Session, user: User, row: Row, req: "BindRequest") -> str:
    """Mint a new ToolInstanceRecord seeded from this entry's observations and
    return its id — the inbox 'new tool' path, for a entry holding a tool the
    catalog doesn't know yet. The entry's measured diameter carries through with
    its provenance; the name is the human endorsing the entry's label, so it is
    asserted, not observed."""
    canonical = {
        "name": {"value": None, "source": UNKNOWN},
        "catalog_type_id": {"value": None, "source": UNKNOWN},
        "geometry": {},
    }
    name = req.name or (row.canonical.get("description") or {}).get("value")
    if name:
        canonical["name"] = {"value": name, "source": Provenance.asserted(req.actor)}
    entry_dia = (row.canonical.get("offsets") or {}).get("diameter")
    if entry_dia and entry_dia.get("value") is not None:
        canonical["geometry"]["diameter"] = dict(entry_dia)   # measured, with provenance
    inst = InstanceRow(canonical=canonical, clients={}, catalog_type_id=None,
                       user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(inst)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="CREATE",
                     entity_type="tool_instance_record", entity_id=inst.id,
                     changes={"minted_from_entry": row.id})
    return inst.id


@router.post("/{record_id}/bind")
def bind_instance(record_id: str, req: BindRequest, db: Session = Depends(get_db),
                  user: User = Depends(get_authenticated_user)):
    """Bind a physical instance into this entry. Pass an `instance_id` to bind an
    existing instance; omit it to mint a new instance from the entry's own
    observations (the 'new tool' path of the inbox) and bind that. Install-once:
    if the instance is already in another entry, 409 (with where) unless
    move=true, which relocates it atomically."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")

    minting = req.instance_id is None
    if minting:
        if row.bound_instance_id is not None:
            raise HTTPException(status_code=409, detail="entry is already bound")
        instance_id = _mint_instance_from_entry(db, user, row, req)
    else:
        instance_id = req.instance_id
        other = db.query(Row).filter(
            Row.user_id == user.id,
            Row.bound_instance_id == instance_id,
            Row.id != record_id,
        ).first()
        if other is not None:
            if not req.move:
                raise HTTPException(
                    status_code=409,
                    detail="instance %s is already installed in %s — unbind it "
                           "there first, or bind with move=true"
                           % (instance_id[:8], _entry_label(other)))
            _set_binding(other, None, req.actor)     # vacate the old entry
            other.updated_by = user.id
            create_audit_log(session=db, user_id=user.id, operation="UNBIND",
                             entity_type="tool_table_entry_record", entity_id=other.id,
                             changes={"reason": "moved", "to": record_id})

    _set_binding(row, instance_id, req.actor)
    row.updated_by = user.id
    close_open_proposal_on_bind(db, user, row.id, instance_id)
    create_audit_log(session=db, user_id=user.id, operation="BIND",
                     entity_type="tool_table_entry_record", entity_id=row.id,
                     changes={"instance_id": instance_id, "minted": minting})
    try:
        db.commit()
    except IntegrityError:                        # unique index is the backstop
        db.rollback()
        raise HTTPException(status_code=409,
                            detail="instance %s is already installed elsewhere"
                                   % instance_id[:8])
    return _response(row)


@router.delete("/{record_id}")
def delete_entry(record_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_authenticated_user)):
    """Remove a machine-reported entry (and its open proposals). The instance it
    held, if any, is not deleted. If the controller re-pushes, the entry returns."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    from loobric_server.database.schema import EntryProposal
    db.query(EntryProposal).filter(EntryProposal.entry_id == record_id).delete()
    db.delete(row)
    create_audit_log(session=db, user_id=user.id, operation="DELETE",
                     entity_type="tool_table_entry_record", entity_id=record_id)
    db.commit()
    return {"deleted": record_id}


@router.post("/{record_id}/unbind")
def unbind_instance(record_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_authenticated_user)):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    _set_binding(row, None, "human@inbox")
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="UNBIND",
                     entity_type="tool_table_entry_record", entity_id=row.id)
    db.commit()
    return _response(row)
