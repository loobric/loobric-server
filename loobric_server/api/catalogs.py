# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalogs: named collections of catalog records (grilled 2026-08-16).

A Catalog organizes ToolCatalogRecords the way a ToolSet organizes physical
tools — a sectioned record whose canonical carries `name` and `members` (a
provenance-tagged list of catalog-record ids). The rules:

- Membership is ORGANIZATION, never identity: a record may sit in any
  number of catalogs, uncataloged records are fine (the UI surfaces them),
  and the account-wide natural key is untouched by grouping.
- Deleting a catalog never deletes records.
- Members are replace-only (the ToolSet members door): the caller sends the
  full list; unknown record ids are a 400 naming them — membership must
  never silently point at nothing.

This file's previous occupant — the v1 ManufacturerCatalog router (deep
model, ToolItem ids, manufacturer-role accounts) — is retired by migration
0008; this is the R6 evict-the-squatter move, same as "preset".
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db
from loobric_server.auth.doors import door
from loobric_server.audit import create_audit_log
from loobric_server.contract import Provenance
from loobric_server.database.schema import Catalog, ToolCatalogRecord, User

router = APIRouter(prefix="/api/v1/catalogs", tags=["catalogs"])


def _iso(value):
    return value.isoformat() if value is not None else None


def _response(row: Catalog) -> dict:
    return {"internal": {"id": row.id, "version": row.version,
                         "created_at": _iso(row.created_at),
                         "updated_at": _iso(row.updated_at)},
            "canonical": row.canonical or {},
            "clients": row.clients or {}}


def _owned(db: Session, user: User, catalog_id: str) -> Optional[Catalog]:
    return db.query(Catalog).filter(Catalog.id == catalog_id,
                                    Catalog.user_id == user.id).first()


def _validate_member_ids(db: Session, user: User, ids: List[str]) -> None:
    """Every member must be an existing, owned catalog record — membership
    never silently points at nothing."""
    if not ids:
        return
    owned = {row.id for row in db.query(ToolCatalogRecord.id).filter(
        ToolCatalogRecord.user_id == user.id,
        ToolCatalogRecord.id.in_(ids)).all()}
    unknown = [i for i in ids if i not in owned]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={"message": "unknown catalog record id(s)",
                    "unknown_record_ids": unknown})


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    actor: str = "human@cli"


class MembersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: List[str]
    actor: str = "human@cli"


class RenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    actor: str = "human@cli"


@router.post("", status_code=201)
def create_catalog(req: CreateRequest, db: Session = Depends(get_db),
                   user: User = Depends(door("assert"))):
    """Create a named, empty catalog."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name must not be empty")
    row = Catalog(canonical={
        "name": {"value": name, "source": Provenance.asserted(req.actor)},
        "members": {"value": [], "source": Provenance.asserted(req.actor)},
    }, user_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    create_audit_log(session=db, user_id=user.id, operation="CREATE",
                     entity_type="catalog", entity_id=row.id,
                     changes={"name": name})
    db.commit()
    return _response(row)


@router.get("")
def list_catalogs(db: Session = Depends(get_db),
                  user: User = Depends(door("read"))):
    rows = db.query(Catalog).filter(Catalog.user_id == user.id).order_by(
        Catalog.created_at).all()
    return {"items": [_response(row) for row in rows]}


@router.get("/{catalog_id}")
def get_catalog(catalog_id: str, db: Session = Depends(get_db),
                user: User = Depends(door("read"))):
    row = _owned(db, user, catalog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _response(row)


@router.post("/{catalog_id}/rename")
def rename_catalog(catalog_id: str, req: RenameRequest,
                   db: Session = Depends(get_db),
                   user: User = Depends(door("assert"))):
    row = _owned(db, user, catalog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name must not be empty")
    canonical = dict(row.canonical or {})
    canonical["name"] = {"value": name,
                         "source": Provenance.asserted(req.actor)}
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="catalog", entity_id=row.id,
                     changes={"path": "name", "name": name})
    db.commit()
    return _response(row)


@router.post("/{catalog_id}/members")
def set_members(catalog_id: str, req: MembersRequest,
                db: Session = Depends(get_db),
                user: User = Depends(door("assert"))):
    """Replace membership (the ToolSet members door, without numbers —
    catalogs organize types, they claim nothing). Duplicates collapse;
    unknown ids are a 400 naming them."""
    row = _owned(db, user, catalog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    members = list(dict.fromkeys(req.members))       # de-dupe, keep order
    _validate_member_ids(db, user, members)
    canonical = dict(row.canonical or {})
    canonical["members"] = {"value": members,
                            "source": Provenance.asserted(req.actor)}
    row.canonical = canonical
    row.version += 1
    row.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                     entity_type="catalog", entity_id=row.id,
                     changes={"path": "members", "count": len(members)})
    db.commit()
    return _response(row)


@router.delete("/{catalog_id}")
def delete_catalog(catalog_id: str, db: Session = Depends(get_db),
                   user: User = Depends(door("delete"))):
    """Delete a catalog. Its records STAY — a catalog is organization,
    and organization is never identity."""
    row = _owned(db, user, catalog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(row)
    create_audit_log(session=db, user_id=user.id, operation="DELETE",
                     entity_type="catalog", entity_id=catalog_id)
    db.commit()
    return {"deleted": catalog_id}


def upsert_import_catalog(db: Session, user: User, name: str,
                          record_ids: List[str], actor: str) -> Optional[str]:
    """The importer lane (grilled: auto-catalog per import): find the
    caller's catalog by name or create it, and UNION the given record ids
    into its members. Idempotent — re-importing the same file grows
    nothing. Caller commits. Returns the catalog id, or None for no-ops."""
    if not name or not record_ids:
        return None
    row = next((c for c in db.query(Catalog).filter(
        Catalog.user_id == user.id).all()
        if ((c.canonical or {}).get("name") or {}).get("value") == name), None)
    if row is None:
        row = Catalog(canonical={
            "name": {"value": name, "source": Provenance.asserted(actor)},
            "members": {"value": [], "source": Provenance.asserted(actor)},
        }, user_id=user.id, created_by=user.id, updated_by=user.id)
        db.add(row)
        db.flush()
        create_audit_log(session=db, user_id=user.id, operation="CREATE",
                         entity_type="catalog", entity_id=row.id,
                         changes={"name": name, "via": "import"})
    canonical = dict(row.canonical or {})
    current = ((canonical.get("members") or {}).get("value")) or []
    merged = list(dict.fromkeys(list(current) + list(record_ids)))
    if merged != current:
        canonical["members"] = {"value": merged,
                                "source": Provenance.asserted(actor)}
        row.canonical = canonical
        row.version += 1
        row.updated_by = user.id
        create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                         entity_type="catalog", entity_id=row.id,
                         changes={"path": "members", "count": len(merged),
                                  "via": "import"})
    return row.id
