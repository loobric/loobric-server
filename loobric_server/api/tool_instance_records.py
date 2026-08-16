# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
ToolInstanceRecord facade — the first sectioned entity (docs/TOOL_SCHEMA.md).

Tracer-bullet vertical proving the whole pattern end to end:
- responses are the three-section shape, validated against loobric_server.contract
  before they leave the server (the server emits provably-conformant data);
- a client writes ONLY its own section (`PUT .../clients/{name}`), lane-enforced
  by loobric_server.contract.reject_out_of_lane — internal/canonical keys are a 400;
- canonical changes only through the two doors: `observe` (machines, observable
  fields only) and `assert` (deliberate, audited). Routine sync cannot touch it.

Other entities (catalog, entry, set, machine) follow this template; the old
flat ToolRecord facade is retired as the slices land.
"""
import copy
from datetime import datetime, UTC
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from loobric_server.api import _media
from loobric_server.api.auth import get_db, get_authenticated_user
from loobric_server.auth.doors import door
from loobric_server.database.schema import User, ToolInstanceRecord as Row
from loobric_server.audit import create_audit_log
from loobric_server.contract import (
    ToolInstanceRecord, InstanceCanonical, Provenance, UNKNOWN,
    LaneViolation, reject_out_of_lane,
)

router = APIRouter(prefix="/api/v1/tool-instance-records", tags=["tool-instance-records"])

# Minimal scope rule for the tracer: a machine may only OBSERVE these canonical
# paths; everything else (notably geometry.shape) must be asserted. The full
# per-client scope manifest (docs/TOOL_SCHEMA.md §10) lands with the clients.
OBSERVABLE_PATHS = {"geometry.diameter", "geometry.length", "status"}

# Ratified status vocabulary (2026-08-04): `retired` — a valid record of a
# tool no longer in service (distinct from DELETE, which is for records that
# should never have existed). Absence of status = in service. Values are
# ratified, not accreted (the machine-capability precedent): anything else is
# a 400. `retired` is an administrative judgment, so it is ASSERT-only — no
# machine can measure retirement, and no observable status values exist yet.
STATUS_VALUES = {"retired"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _blank_canonical() -> dict:
    """A freshly-minted instance asserts nothing — every canonical field is
    honestly unknown until observed or asserted."""
    return {
        "name": {"value": None, "source": UNKNOWN},
        "catalog_type_id": {"value": None, "source": UNKNOWN},
        "geometry": {},
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
    ToolInstanceRecord.model_validate(doc)
    return doc


def _owned(db: Session, user: User, record_id: str) -> Optional[Row]:
    return db.query(Row).filter(Row.id == record_id, Row.user_id == user.id).first()


def _validate_canonical(canonical: dict) -> None:
    try:
        InstanceCanonical.model_validate(canonical)
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
    actor: str          # e.g. "freecad" or "human@inbox"


class ObserveRequest(BaseModel):
    path: str
    value: Any = None
    unit: Optional[str] = None
    client: str
    machine: str


class LabelRequest(BaseModel):
    code: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("")
def create_instance(payload: CreateRequest, db: Session = Depends(get_db),
                    user: User = Depends(door("assert"))):
    """Mint a physical-tool instance. Canonical starts all-unknown; an optional
    initial client section may be seeded. Canonical is populated only via the
    observe/assert doors thereafter."""
    clients = {}
    if payload.client:
        clients[payload.client] = {
            "client_version": payload.client_version or "",
            "client_item_id": payload.client_item_id,
            "created_at": _now(), "updated_at": _now(),
            "data": payload.data or {},
        }
    row = Row(canonical=_blank_canonical(), clients=clients, catalog_type_id=None,
              user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="CREATE",
                     entity_type="tool_instance_record", entity_id=row.id)
    db.commit()
    return _response(row)


@router.get("")
def list_instances(db: Session = Depends(get_db),
                   user: User = Depends(door("read"))):
    rows = db.query(Row).filter(Row.user_id == user.id).order_by(Row.created_at).all()
    return {"items": [_response(r) for r in rows]}


@router.get("/{record_id}")
def get_instance(record_id: str, db: Session = Depends(get_db),
                 user: User = Depends(door("read"))):
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _response(row)


@router.put("/{record_id}/clients/{client}")
def write_client_section(record_id: str, client: str, payload: dict,
                         db: Session = Depends(get_db),
                         user: User = Depends(door("sync"))):
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
                     entity_type="tool_instance_record", entity_id=row.id,
                     changes={"client": client})
    db.commit()
    return _response(row)


@router.post("/{record_id}/assert")
def assert_canonical(record_id: str, req: AssertRequest,
                     db: Session = Depends(get_db),
                     user: User = Depends(door("assert"))):
    """Deliberately declare a canonical value (shape, a nominal dimension, the
    catalog-type link). Rare, audited. Stamps source asserted:<actor>."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if req.path == "usage" or req.path.startswith("usage."):
        # §7.8: the lifetime total is derived from the usage ledger; nobody
        # ever claims it. (Observe refuses via OBSERVABLE_PATHS; this is the
        # assert-door half of the same rule.)
        raise HTTPException(
            status_code=400,
            detail="usage is derived from the usage ledger; no door writes "
                   "it directly")
    if req.path == "presets" or req.path.startswith("presets."):
        # docs/PRESETS.md: the union is derived from contributions; the
        # contribution door (POST …/presets) is the only way in.
        raise HTTPException(
            status_code=400,
            detail="presets is a derived union; contribute through "
                   "POST /tool-instance-records/{id}/presets instead")
    if req.path == "status" and req.value is not None \
            and req.value not in STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail="status must be one of %s (or null to clear it) — the "
                   "vocabulary is ratified, not accreted"
                   % sorted(STATUS_VALUES))
    field = {"value": req.value, "source": Provenance.asserted(req.actor)}
    if req.unit is not None:
        field["unit"] = req.unit
    canonical = _set_path(row.canonical, req.path, field)
    _validate_canonical(canonical)
    row.canonical = canonical
    if req.path == "catalog_type_id":
        row.catalog_type_id = req.value
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="tool_instance_record", entity_id=row.id,
                     changes={"path": req.path, "source": field["source"]})
    db.commit()
    return _response(row)


@router.delete("/{record_id}")
def delete_instance(record_id: str, db: Session = Depends(get_db),
                    user: User = Depends(door("delete"))):
    """Delete a tool instance. Any entry holding it is UNBOUND first (the entry
    keeps its observed data; only the install link dies) — never orphaned."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    from loobric_server.database.schema import ToolTableEntryRecord as EntryRow
    for entry in db.query(EntryRow).filter(
            EntryRow.user_id == user.id, EntryRow.bound_instance_id == record_id).all():
        canon = dict(entry.canonical)
        canon["bound_instance_id"] = {"value": None, "source": UNKNOWN}
        entry.canonical = canon
        entry.bound_instance_id = None
        entry.version += 1
        entry.updated_by = user.id
        create_audit_log(session=db, user_id=user.id, operation="UNBIND",
                         entity_type="tool_table_entry_record", entity_id=entry.id,
                         changes={"reason": "bound instance deleted"})
    from loobric_server.database.schema import PresetContribution
    db.query(PresetContribution).filter(
        PresetContribution.user_id == user.id,
        PresetContribution.record_kind == "instance",
        PresetContribution.record_id == record_id).delete()
    # Labels on the deleted record are BURNED, not freed (founder decision
    # 2026-08-04): delete is for records that should never have existed, and
    # a resurrected code on a different tool would make the old sticker lie.
    # The codes resolve to the landing page forever. Deliberate reuse exists
    # and is `unlabel` (peel the sticker off first); "retiring" a worn-out
    # tool is a future status concept, not deletion.
    from loobric_server.database.schema import Label
    for lbl in db.query(Label).filter(
            Label.user_id == user.id, Label.entity_id == record_id).all():
        db.delete(lbl)
        create_audit_log(session=db, user_id=user.id, operation="DELETE",
                         entity_type="label", entity_id=lbl.id,
                         changes={"code": lbl.code,
                                  "reason": "labeled record deleted"})
    db.delete(row)
    create_audit_log(session=db, user_id=user.id, operation="DELETE",
                     entity_type="tool_instance_record", entity_id=record_id)
    db.commit()
    return {"deleted": record_id}


@router.get("/{record_id}/usage")
def get_usage(record_id: str, db: Session = Depends(get_db),
              user: User = Depends(door("read"))):
    """The lifetime total AND its decomposition — 37.4 = 25.3 from one
    machine + 12.1 from another. The decomposition is the provenance of the
    derived total; owner-only, like everything on the record."""
    from loobric_server.usage_ledger import contributions, instance_total
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    rows = contributions(db, user, record_id)
    by_machine: dict = {}
    for c in rows:
        by_machine[c.machine_id] = by_machine.get(c.machine_id, 0.0) + c.amount
    return {
        "total": round(instance_total(db, user, record_id), 6),
        "unit": "h",
        "contributions": [
            {"machine_id": c.machine_id, "entry_id": c.entry_id,
             "amount": c.amount, "source": c.source,
             "at": _iso(c.created_at)}
            for c in rows],
        "by_machine": {m: round(v, 6) for m, v in by_machine.items()},
    }


class PresetContributeRequest(BaseModel):
    """One cutting data preset contribution (docs/PRESETS.md): the G5
    engineering values plus a verbatim extras bag. `origin` is the
    recommender; `actor` is the transcriber the server stamps."""
    model_config = ConfigDict(extra="forbid")

    origin: str
    label: str
    material: dict
    op_type: Optional[str] = None
    vc: Optional[dict] = None
    fz: Optional[dict] = None
    ratio: Optional[dict] = None
    extras: Optional[dict] = None
    machine_id: Optional[str] = None
    actor: str = "human@cli"

    def payload(self) -> dict:
        data = self.model_dump()
        data.pop("actor")
        return {k: v for k, v in data.items() if v is not None}


@router.post("/{record_id}/presets")
def contribute_preset(record_id: str, req: PresetContributeRequest,
                      db: Session = Depends(get_db),
                      user: User = Depends(door("assert"))):
    """Contribute one cutting data preset through the audited door
    (docs/PRESETS.md). Replace-own: a same-(origin, label) re-contribution
    supersedes its predecessor. The record's canonical `presets` union is
    rematerialized (derived:preset-union) — no door writes it directly."""
    from loobric_server import presets as presets_mod
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        presets_mod.contribute(db, user, presets_mod.KIND_INSTANCE, row.id,
                               req.payload(), actor=req.actor.strip())
    except presets_mod.PresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    presets_mod.materialize(db, user, row, presets_mod.KIND_INSTANCE)
    db.commit()
    return _response(row)


@router.get("/{record_id}/presets")
def list_presets(record_id: str, origin: Optional[str] = None,
                 material: Optional[str] = None,
                 op_type: Optional[str] = None,
                 machine_id: Optional[str] = None,
                 db: Session = Depends(get_db),
                 user: User = Depends(door("read"))):
    """The instance's FULL preset union: its own entries plus its linked
    catalog type's, each marked with `scope` — composed at read time so
    catalog changes never go stale here. Filters are exact (origin,
    op_type, machine_id) or case-insensitive verbatim-name (material)."""
    from loobric_server import presets as presets_mod
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    entries = presets_mod.union_for_instance(db, user, row)
    return {"presets": presets_mod.filter_entries(
        entries, origin=origin, material=material, op_type=op_type,
        machine_id=machine_id)}


@router.delete("/{record_id}/presets/{entry_id}")
def delete_preset(record_id: str, entry_id: str,
                  db: Session = Depends(get_db),
                  user: User = Depends(door("delete"))):
    """Remove one preset contribution — a deliberate act on the delete door
    (agent preset keys don't hold it; replace-own is the agent's only
    revision path)."""
    from loobric_server import presets as presets_mod
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if not presets_mod.remove(db, user, presets_mod.KIND_INSTANCE, row.id,
                              entry_id):
        raise HTTPException(status_code=404, detail="not found")
    presets_mod.materialize(db, user, row, presets_mod.KIND_INSTANCE)
    db.commit()
    return _response(row)


@router.post("/{record_id}/label")
def label_instance(record_id: str, req: LabelRequest,
                   db: Session = Depends(get_db),
                   user: User = Depends(door("bind"))):
    """Put one of the caller's blank labels on this record — the deliberate
    physical↔digital act that makes the record's public spec page exist
    (docs/LABELS.md). Rides the bind door for the same reason entry↔instance
    binding does: it adjudicates what a physical artifact IS."""
    from loobric_server.database.schema import Label
    from loobric_server.label_codes import normalize_code
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        code = normalize_code(req.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Only the generating account may use a label: someone else's code — or a
    # nonexistent one — is the same 404.
    lbl = db.query(Label).filter(
        Label.code == code, Label.user_id == user.id).first()
    if lbl is None:
        raise HTTPException(status_code=404, detail="not found")
    if lbl.entity_id is not None:
        raise HTTPException(
            status_code=409,
            detail="label %s is already on a record — unlabel it first" % code)
    lbl.entity_type = "tool_instance"
    lbl.entity_id = row.id
    lbl.labeled_at = datetime.now(UTC)
    lbl.version += 1
    lbl.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="LABEL",
                     entity_type="label", entity_id=lbl.id,
                     changes={"code": code, "record_id": row.id})
    db.commit()
    return {"labeled": {"code": code, "record_id": row.id}}


@router.post("/{record_id}/unlabel")
def unlabel_instance(record_id: str, req: LabelRequest,
                     db: Session = Depends(get_db),
                     user: User = Depends(door("bind"))):
    """Take a label off this record. The label reverts to blank (reusable);
    the record keeps all its data but loses that public route to it."""
    from loobric_server.database.schema import Label
    from loobric_server.label_codes import normalize_code
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        code = normalize_code(req.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    lbl = db.query(Label).filter(
        Label.code == code, Label.user_id == user.id).first()
    if lbl is None:
        raise HTTPException(status_code=404, detail="not found")
    if lbl.entity_id != row.id:
        raise HTTPException(
            status_code=409, detail="label %s is not on this record" % code)
    lbl.entity_id = None
    lbl.labeled_at = None
    lbl.version += 1
    lbl.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="UNLABEL",
                     entity_type="label", entity_id=lbl.id,
                     changes={"code": code, "record_id": row.id})
    db.commit()
    return {"unlabeled": {"code": code, "record_id": row.id}}


@router.post("/{record_id}/media")
async def upload_media(record_id: str, file: UploadFile = File(...),
                       role: str = Form(...), actor: str = Form("human@cli"),
                       db: Session = Depends(get_db),
                       user: User = Depends(door("assert"))):
    """Attach a media file (e.g. an as-built 3D scan, a photo) to this physical
    instance. Bytes go to the blob store; canonical.media gains a reference the
    server stamps asserted:<actor>. The server does not parse the file."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    data = await file.read()
    canonical, entry = _media.append_media(
        row.canonical, data=data, role=role,
        content_type=file.content_type, filename=file.filename,
        actor=(actor or "human@cli").strip())
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="tool_instance_record", entity_id=row.id,
                     changes={"path": "media", "role": role, "ref": entry["ref"]})
    db.commit()
    return _response(row)


@router.get("/{record_id}/media/{ref:path}")
def get_media(record_id: str, ref: str, db: Session = Depends(get_db),
              user: User = Depends(door("read"))):
    """Stream a referenced media file's bytes."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _media.serve(row.canonical, ref)


@router.delete("/{record_id}/media/{ref:path}")
def delete_media(record_id: str, ref: str, actor: str = "human@cli",
                 db: Session = Depends(get_db),
                 user: User = Depends(door("delete"))):
    """Drop a media reference from this record (bytes remain in the blob store)."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    canonical = _media.remove_media(row.canonical, ref, actor=actor)
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="tool_instance_record", entity_id=row.id,
                     changes={"path": "media", "removed": ref})
    db.commit()
    return _response(row)


@router.post("/{record_id}/observe")
def observe_canonical(record_id: str, req: ObserveRequest,
                      db: Session = Depends(get_db),
                      user: User = Depends(door("observe"))):
    """A machine reports a measurement for an OBSERVABLE field. Scope-gated: a
    machine may not observe (let alone assert) something it cannot measure —
    e.g. geometry.shape is rejected."""
    row = _owned(db, user, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if req.path not in OBSERVABLE_PATHS:
        raise HTTPException(
            status_code=400,
            detail="%r is not observable; it must be asserted (a machine cannot "
                   "measure it)" % req.path)
    if req.path == "status":
        # No observable status values are ratified: `retired` is an
        # administrative judgment, not a measurement — assert it.
        raise HTTPException(
            status_code=400,
            detail="no observable status values exist; status is asserted")
    field = {"value": req.value, "source": Provenance.observed(req.client, req.machine)}
    if req.unit is not None:
        field["unit"] = req.unit
    canonical = _set_path(row.canonical, req.path, field)
    _validate_canonical(canonical)
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="OBSERVE",
                     entity_type="tool_instance_record", entity_id=row.id,
                     changes={"path": req.path, "source": field["source"]})
    db.commit()
    return _response(row)
