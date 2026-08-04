# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Labels API — physical QR/short-code stickers (docs/LABELS.md).

A Label points at one record via (entity_type, entity_id); a NULL entity_id
is a BLANK label (pre-printed, not yet on anything digital). Labels are
owner-private like every other resource — only the generating account can
see them or put them on a record — but the code RESOLVES publicly at
`/t/{code}` (api/resolver.py): labeling a record is the deliberate act that
makes its public spec page exist.

The label↔record verbs live on the record routers (`POST
/tool-instance-records/{id}/label` / `/unlabel`) — you label a TOOL, the way
you bind an ENTRY; this router owns only the label lifecycle itself.

Assumptions:
- v1 accepts only entity_type="tool_instance"; the schema stays generic.
- Creating labels rides the `assert` door (declaring a physical artifact
  into existence); deletion rides `delete`.
- Cross-account access is 404, never 403 (docs/SECURITY_ASSUMPTIONS.md #8).
"""
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db
from loobric_server.auth.doors import door
from loobric_server.audit import create_audit_log
from loobric_server.config import settings
from loobric_server.database.schema import Label, User
from loobric_server.label_codes import new_unique_code

router = APIRouter(prefix="/api/v1/labels", tags=["labels"])

ENTITY_TYPES = {"tool_instance"}
MAX_BATCH = 100


def label_base_url(request: Request) -> str:
    """The base for printed label URLs: the configured public_base_url, or
    (LAN/solo default) the address this request arrived at."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return "%s://%s" % (request.url.scheme, request.url.netloc)


def label_url(request: Request, code: str) -> str:
    return "%s/t/%s" % (label_base_url(request), code)


def _iso(value) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


def _response(request: Request, row: Label) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "url": label_url(request, row.code),
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "labeled_at": _iso(row.labeled_at),
        "created_at": _iso(row.created_at),
        "version": row.version,
    }


def _owned(db: Session, user: User, label_id: str) -> Optional[Label]:
    return db.query(Label).filter(
        Label.id == label_id, Label.user_id == user.id).first()


class CreateRequest(BaseModel):
    count: int = 1
    entity_type: str = "tool_instance"
    # Convenience: create ONE label already on a record (count must be 1).
    entity_id: Optional[str] = None


@router.post("")
def create_labels(payload: CreateRequest, request: Request,
                  db: Session = Depends(get_db),
                  user: User = Depends(door("assert"))):
    """Mint labels — blank by default (pre-print a sheet, stick them on
    things over time), or one label directly on an owned record."""
    if payload.entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail="entity_type must be one of %s" % sorted(ENTITY_TYPES))
    if not 1 <= payload.count <= MAX_BATCH:
        raise HTTPException(
            status_code=400, detail="count must be 1..%d" % MAX_BATCH)
    if payload.entity_id is not None and payload.count != 1:
        raise HTTPException(
            status_code=400, detail="entity_id requires count=1")
    if payload.entity_id is not None:
        from loobric_server.database.schema import ToolInstanceRecord
        target = db.query(ToolInstanceRecord).filter(
            ToolInstanceRecord.id == payload.entity_id,
            ToolInstanceRecord.user_id == user.id).first()
        if target is None:
            raise HTTPException(status_code=404, detail="not found")

    rows = []
    for _ in range(payload.count):
        row = Label(
            code=new_unique_code(db),
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            labeled_at=datetime.now(UTC) if payload.entity_id else None,
            user_id=user.id, created_by=user.id, updated_by=user.id)
        db.add(row)
        db.flush()
        create_audit_log(session=db, user_id=user.id, operation="CREATE",
                         entity_type="label", entity_id=row.id,
                         changes={"code": row.code,
                                  "entity_id": payload.entity_id})
        rows.append(row)
    db.commit()
    return {"items": [_response(request, r) for r in rows]}


class SheetRequest(BaseModel):
    # Exactly one of these: print existing labels, or mint-and-print a
    # blank batch in one act (the pre-print workflow).
    label_ids: Optional[list[str]] = None
    count: Optional[int] = None
    stock: str = "avery-5160"
    # 0-based grid position to start at — a partially-used sheet goes back
    # in the printer and the next batch starts where the stickers do.
    start_at: int = 0


@router.post("/sheet")
def print_sheet(payload: SheetRequest, request: Request,
                db: Session = Depends(get_db),
                user: User = Depends(door("assert"))):
    """A PDF of labels on sticker stock. `count` mints that many blank
    labels and prints them; `label_ids` reprints existing ones."""
    from loobric_server.label_sheets import STOCKS, render_sheet
    if payload.stock not in STOCKS:
        raise HTTPException(
            status_code=400,
            detail="stock must be one of %s" % sorted(STOCKS))
    if (payload.label_ids is None) == (payload.count is None):
        raise HTTPException(
            status_code=400, detail="provide exactly one of label_ids, count")

    if payload.count is not None:
        if not 1 <= payload.count <= MAX_BATCH:
            raise HTTPException(
                status_code=400, detail="count must be 1..%d" % MAX_BATCH)
        rows = []
        for _ in range(payload.count):
            row = Label(code=new_unique_code(db),
                        entity_type="tool_instance", entity_id=None,
                        user_id=user.id, created_by=user.id,
                        updated_by=user.id)
            db.add(row)
            db.flush()
            create_audit_log(session=db, user_id=user.id, operation="CREATE",
                             entity_type="label", entity_id=row.id,
                             changes={"code": row.code, "entity_id": None})
            rows.append(row)
        db.commit()
    else:
        if not payload.label_ids:
            raise HTTPException(status_code=400, detail="label_ids is empty")
        rows = []
        for label_id in payload.label_ids:
            row = _owned(db, user, label_id)
            if row is None:
                raise HTTPException(status_code=404, detail="not found")
            rows.append(row)

    per_page = STOCKS[payload.stock]["columns"] * STOCKS[payload.stock]["rows"]
    if not 0 <= payload.start_at < per_page:
        raise HTTPException(
            status_code=400,
            detail="start_at must be 0..%d for %s" % (per_page - 1,
                                                      payload.stock))
    pdf = render_sheet([(r.code, label_url(request, r.code)) for r in rows],
                       payload.stock, start_at=payload.start_at)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 'attachment; filename="loobric-labels.pdf"'})


@router.get("")
def list_labels(request: Request, blank: Optional[bool] = None,
                entity_id: Optional[str] = None,
                db: Session = Depends(get_db),
                user: User = Depends(door("read"))):
    q = db.query(Label).filter(Label.user_id == user.id)
    if blank is True:
        q = q.filter(Label.entity_id.is_(None))
    elif blank is False:
        q = q.filter(Label.entity_id.isnot(None))
    if entity_id is not None:
        q = q.filter(Label.entity_id == entity_id)
    rows = q.order_by(Label.created_at).all()
    return {"items": [_response(request, r) for r in rows]}


@router.get("/{label_id}")
def get_label(label_id: str, request: Request,
              db: Session = Depends(get_db),
              user: User = Depends(door("read"))):
    row = _owned(db, user, label_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _response(request, row)


@router.delete("/{label_id}")
def delete_label(label_id: str, db: Session = Depends(get_db),
                 user: User = Depends(door("delete"))):
    """Delete a label. Its code stops resolving (a stale sticker scans to the
    generic landing page); the record it pointed at is untouched."""
    row = _owned(db, user, label_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(row)
    create_audit_log(session=db, user_id=user.id, operation="DELETE",
                     entity_type="label", entity_id=label_id,
                     changes={"code": row.code})
    db.commit()
    return {"deleted": label_id}
