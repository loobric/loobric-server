# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Account-level operations on the caller's own tool data.

Both endpoints here act ONLY on the authenticated caller's data (everything is
user-scoped), so they are owner-gated — any signed-in user may manage their own
account. (Cross-account/factory operations live behind admin gating elsewhere:
see `/api/v1/admin/wipe` and `/api/v1/backup/*`.)

- `reset` wipes all of the caller's tool data — instance/catalog records, tool
  sets, machines, tool-table entries, and open binding proposals — while keeping
  the account itself and its API keys. Return to a clean slate in one call.
- `seed-demo` does the inverse: it populates a fresh account with a small demo
  (a machine, a two-manufacturer catalog, a couple of physical tools, a tool
  set, and a pushed tool table) so a first-time visitor has something to explore
  without touching the CLI. It refuses on an account that already has tool data,
  and rolls back to the clean slate it started from if any step fails.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from loobric_server.auth.doors import door
from loobric_server.api.auth import get_authenticated_user, get_db
from loobric_server.audit import create_audit_log
from loobric_server.database.schema import (
    Catalog,
    EntryProposal,
    MachineRecord,
    MachineSetMap,
    ToolCatalogRecord,
    ToolInstanceRecord,
    ToolSetRecord,
    ToolTableEntryRecord,
    User,
)

router = APIRouter(prefix="/api/v1/account", tags=["account"])

# The caller's tool-data tables, in delete-safe order (proposals/entries/setups
# before the records/sets/machines they reference).
_TOOL_DATA_MODELS = (
    ("binding_proposals", EntryProposal),
    ("tool_table_entries", ToolTableEntryRecord),
    ("setups", MachineSetMap),
    ("tool_sets", ToolSetRecord),
    ("tool_instances", ToolInstanceRecord),
    ("catalogs", Catalog),
    ("tool_catalogs", ToolCatalogRecord),
    ("machines", MachineRecord),
)

# The demo a fresh account is seeded with. Mirrors loobric-cli's
# examples/quickstart.sh so the web "Add demo data" and the CLI seed tell the
# same story. Catalog rows: (source, name, manufacturer, product_code, geometry)
# where each geometry leaf is (value, unit) — unit None for unitless counts.
_DEMO_ACTOR = "human@demo"
_DEMO_CATALOG = [
    ("manufacturer:kennametal", "1/4in 2-flute flat endmill", "Kennametal", "B201",
     {"diameter": (6.35, "mm"), "flutes": (2, None)}),
    ("manufacturer:kennametal", "1/8in 2-flute flat endmill", "Kennametal", "B101",
     {"diameter": (3.175, "mm"), "flutes": (2, None)}),
    ("manufacturer:kennametal", "6mm 3-flute endmill", "Kennametal", "B306",
     {"diameter": (6.0, "mm"), "flutes": (3, None)}),
    ("manufacturer:kennametal", "5mm jobber drill", "Kennametal", "D050",
     {"diameter": (5.0, "mm")}),
    ("manufacturer:sandvik", "60deg V-bit engraver", "Sandvik", "V160",
     {"diameter": (6.0, "mm")}),
    ("manufacturer:sandvik", "90deg chamfer mill", "Sandvik", "C290",
     {"diameter": (6.0, "mm")}),
    ("manufacturer:sandvik", "3mm ball-nose endmill", "Sandvik", "BN030",
     {"diameter": (3.0, "mm"), "flutes": (2, None)}),
    ("manufacturer:sandvik", "50mm face mill", "Sandvik", "F500",
     {"diameter": (50.0, "mm"), "flutes": (5, None)}),
]
_DEMO_INSTANCES = [("B201", "1/4in endmill (stock)"), ("V160", "60deg V-bit (stock)")]
_DEMO_ENTRIES = [(1, "1/4 downcut", 6.35), (2, "60 vee", 6.0)]


def _delete_all_tool_data(db: Session, uid: str) -> dict:
    """Delete every tool-data row owned by `uid`; return per-table counts.
    Does not commit — the caller owns the transaction."""
    return {label: db.query(model).filter(model.user_id == uid).delete()
            for label, model in _TOOL_DATA_MODELS}


def _has_tool_data(db: Session, uid: str) -> bool:
    return any(db.query(model).filter(model.user_id == uid).first() is not None
               for _, model in _TOOL_DATA_MODELS)


def _tool_data_counts(db: Session, uid: str) -> dict:
    return {label: db.query(model).filter(model.user_id == uid).count()
            for label, model in _TOOL_DATA_MODELS}


@router.post("/reset")
def reset_account(db: Session = Depends(get_db),
                  user: User = Depends(door("admin"))):
    """Delete ALL of the caller's tool data, keeping the account and API keys.
    Atomic. The account, its users, and its API keys are untouched."""
    uid = user.id
    deleted = _delete_all_tool_data(db, uid)
    create_audit_log(session=db, user_id=uid, operation="RESET",
                     entity_type="account", entity_id=uid, changes=deleted)
    db.commit()
    return {"reset": True, "deleted": deleted}


@router.post("/seed-demo")
def seed_demo(db: Session = Depends(get_db),
              user: User = Depends(door("admin"))):
    """Populate a fresh account with the demo dataset so there's something to
    explore. Owner-gated; touches only the caller's data. Refuses (409) when the
    account already holds tool data — load it on a clean slate (Reset first to
    reload). Built by replaying the normal create/assert/sync doors, so every
    seeded field carries the same provenance a real client would write. If any
    step fails, the caller's tool data is wiped back to the empty slate the
    pre-check guaranteed, so a retry is always clean."""
    uid = user.id
    if _has_tool_data(db, uid):
        raise HTTPException(
            status_code=409,
            detail="account already has tool data — reset first to load the demo")

    # Reuse the real route handlers (imported lazily to avoid any router
    # import-order coupling) so the demo goes through the exact validated paths.
    from loobric_server.api import machine_records as m  # noqa: I001
    from loobric_server.api import tool_catalog_records as c
    from loobric_server.api import tool_set_records as s
    from loobric_server.api import tool_table_entry_records as e
    try:
        machine = m.create_machine(payload=m.CreateRequest(), db=db, user=user)
        mid = machine["internal"]["id"]
        m.assert_canonical(record_id=mid, db=db, user=user,
                           req=m.AssertRequest(path="name", value="sandbox-mill",
                                               actor=_DEMO_ACTOR))
        m.assert_canonical(record_id=mid, db=db, user=user,
                           req=m.AssertRequest(path="controller_type",
                                               value="linuxcnc", actor=_DEMO_ACTOR))

        cat_ids = {}
        for source, name, mfr, code, geom in _DEMO_CATALOG:
            req = c.CreateRequest(
                actor=source,
                name=c.NominalField(value=name),
                manufacturer=c.NominalField(value=mfr),
                product_code=c.NominalField(value=code),
                geometry={k: c.NominalField(value=val[0],
                                            unit=(val[1] if len(val) > 1 else None))
                          for k, val in geom.items()},
            )
            rec = c.create_catalog_record(req=req, db=db, user=user)
            cat_ids[code] = rec["internal"]["id"]

        inst_ids = []
        for code, iname in _DEMO_INSTANCES:
            rec = c.create_instance_from_catalog(
                record_id=cat_ids[code], db=db, user=user,
                req=c.CreateInstanceRequest(name=iname))
            inst_ids.append(rec["internal"]["id"])

        sset = s.create_set(payload=s.CreateRequest(), db=db, user=user)
        sid = sset["internal"]["id"]
        s.assert_canonical(record_id=sid, db=db, user=user,
                           req=s.AssertRequest(path="name", value="Sandbox demo set",
                                               actor=_DEMO_ACTOR))
        s.set_members(record_id=sid, db=db, user=user,
                      req=s.MembersRequest(
                          members=[s.MemberIn(tool_record_id=i, number=n + 1)
                                   for n, i in enumerate(inst_ids)],
                          actor=_DEMO_ACTOR))

        # Make the demo set the machine's active setup BEFORE the table push, so
        # the push's request-aware bridge opens elevated-confidence proposals —
        # the demo lands with two `pending bind` claims to confirm.
        from datetime import datetime, UTC
        db.add(MachineSetMap(machine_id=mid, tool_set_id=sid, status="active",
                             activated_at=datetime.now(UTC),
                             user_id=uid, created_by=uid, updated_by=uid))
        db.flush()

        e.sync_entries(db=db, user=user, req=e.EntrySyncRequest(
            machine_id=mid, client="linuxcnc-sim", machine_name="sandbox-mill",
            entries=[e.EntryIn(tool_number=n, description=d,
                               offsets={"diameter": dia, "diameter_unit": "mm"})
                     for n, d, dia in _DEMO_ENTRIES]))
    except Exception:
        # The pre-check guaranteed an empty start, so returning the caller's tool
        # data to empty is exactly a rollback — and keeps a retry clean.
        db.rollback()
        _delete_all_tool_data(db, uid)
        db.commit()
        raise

    created = _tool_data_counts(db, uid)
    create_audit_log(session=db, user_id=uid, operation="SEED",
                     entity_type="account", entity_id=uid, changes=created)
    db.commit()
    return {"seeded": True, "created": created}


@router.get("/export")
def export_account(db: Session = Depends(get_db),
                   user: User = Depends(door("read"))):
    """Download the caller's OWN tool data as one zip — the owner-operated
    escape hatch (the first slice of account portability, #46): every record
    collection as sectioned JSON (canonical with provenance, client sections,
    presets — the records verbatim), the media blobs they reference, and a
    manifest. Admin `/backup` stays the operator's disaster-recovery tool;
    this is the user's.

    Read-shaped and read-gated: exporting changes nothing (an audit row
    records that it happened)."""
    import io
    import json as _json
    import zipfile
    from datetime import datetime, UTC

    from fastapi import Response

    from loobric_server import media_store
    from loobric_server.database.schema import Label

    def _iso(value):
        return value.isoformat() if value is not None else None

    def _record(row):
        return {"internal": {"id": row.id, "version": row.version,
                             "created_at": _iso(row.created_at),
                             "updated_at": _iso(row.updated_at)},
                "canonical": row.canonical or {},
                "clients": getattr(row, "clients", None) or {}}

    collections = {
        "tool_instance_records": ToolInstanceRecord,
        "tool_catalog_records": ToolCatalogRecord,
        "tool_set_records": ToolSetRecord,
        "machine_records": MachineRecord,
        "tool_table_entry_records": ToolTableEntryRecord,
        "catalogs": Catalog,
    }
    uid = user.id
    buffer = io.BytesIO()
    manifest = {"format": "loobric-account-export", "format_version": 1,
                "exported_at": datetime.now(UTC).isoformat(),
                "account": user.email, "counts": {}}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        media_refs = {}
        for name, model in collections.items():
            rows = db.query(model).filter(model.user_id == uid).all()
            records = [_record(row) for row in rows]
            zf.writestr(name + ".json", _json.dumps(records, indent=1))
            manifest["counts"][name] = len(records)
            for record in records:
                for m in ((record["canonical"].get("media") or {})
                          .get("value")) or []:
                    if m.get("ref"):
                        media_refs.setdefault(m["ref"], m)
        labels = db.query(Label).filter(Label.user_id == uid).all()
        zf.writestr("labels.json", _json.dumps([
            {"id": row.id, "code": row.code,
             "entity_type": row.entity_type, "entity_id": row.entity_id,
             "labeled_at": _iso(getattr(row, "labeled_at", None)),
             "created_at": _iso(row.created_at)}
            for row in labels], indent=1))
        manifest["counts"]["labels"] = len(labels)
        stored = missing = 0
        for ref, m in media_refs.items():
            if media_store.blob_exists(ref):
                zf.writestr("media/" + ref.replace(":", "_"),
                            media_store.read_blob(ref))
                stored += 1
            else:
                missing += 1                # honest gap, never invented
        manifest["counts"]["media_files"] = stored
        if missing:
            manifest["counts"]["media_missing"] = missing
        zf.writestr("manifest.json", _json.dumps(manifest, indent=1))

    create_audit_log(session=db, user_id=uid, operation="EXPORT",
                     entity_type="account", entity_id=uid,
                     changes=manifest["counts"])
    db.commit()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=buffer.getvalue(), media_type="application/zip",
        headers={"Content-Disposition":
                 'attachment; filename="loobric-export-%s.zip"' % stamp})
