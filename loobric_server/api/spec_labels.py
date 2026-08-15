# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Spec-labels API — printed spec plates (docs/SPEC_LABELS.md).

A spec label is a RENDERING of a record, not a Label: the sheet endpoint
takes record ids and resolves the merged instance+catalog view, the bound
entry's tool number, and (for QR templates) each record's label code.
Everything returned is a snapshot at print time.

Assumptions:
- Printing rides the READ door and never mints: unlabeled records under a
  QR template are a 400 naming the ids (label first, or pick a QR-less
  template). Auto-mint was ratified out — accidental prints must not
  allocate permanent codes.
- v1 accepts tool-instance records only; the payload stays entity-generic
  in spirit (record_ids) so catalog prints can layer on later.
- A record with several labels prints its newest one, overridable per
  record via `labels` — deliberate, so an existing asset tag can be the
  printed code.
- format=json/csv is the bring-your-own-layout escape hatch: the same
  resolved data the canned templates draw, flat.
- Cross-account access is 404, never 403 (docs/SECURITY_ASSUMPTIONS.md #8).
"""
import csv
from io import StringIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from loobric_server.api.auth import get_db
from loobric_server.api.labels import label_url
from loobric_server.auth.doors import door
from loobric_server.database.schema import (Label, ToolCatalogRecord,
                                            ToolInstanceRecord,
                                            ToolTableEntryRecord, User)
from loobric_server.spec_label_sheets import (EXPORT_COLUMNS, SPEC_STOCKS,
                                              TEMPLATES, export_rows,
                                              render_spec_sheet, resolve_spec)

router = APIRouter(prefix="/api/v1/spec-labels", tags=["spec-labels"])

MAX_BATCH = 100
FORMATS = ("pdf", "json", "csv")


class SheetRequest(BaseModel):
    record_ids: list[str]
    template: str = "qr-specs"
    stock: str = "avery-5160"
    start_at: int = 0
    format: str = "pdf"
    # Per-record label override: {record_id: label_id}. Default is the
    # record's newest label.
    labels: Optional[dict[str, str]] = None


def _leaf_value(canonical, path):
    node = canonical or {}
    for part in path.split("."):
        node = node.get(part) or {}
    return node.get("value") if isinstance(node, dict) else None


def _newest_label(db: Session, user: User, record_id: str) -> Optional[Label]:
    return (db.query(Label)
            .filter(Label.user_id == user.id,
                    Label.entity_type == "tool_instance",
                    Label.entity_id == record_id)
            .order_by(Label.labeled_at.desc(), Label.created_at.desc())
            .first())


def _resolve_items(payload: SheetRequest, request: Request, db: Session,
                   user: User) -> list[dict]:
    """Records → resolved spec items: merged geometry, bound entry's T#,
    and (QR templates) the label code/url."""
    needs_qr = payload.template == "qr-specs"
    overrides = payload.labels or {}
    items, unlabeled = [], []
    for record_id in payload.record_ids:
        record = db.query(ToolInstanceRecord).filter(
            ToolInstanceRecord.id == record_id,
            ToolInstanceRecord.user_id == user.id).first()
        if record is None:
            raise HTTPException(status_code=404, detail="not found")

        catalog = None
        if record.catalog_type_id:
            catalog = db.query(ToolCatalogRecord).filter(
                ToolCatalogRecord.id == record.catalog_type_id,
                ToolCatalogRecord.user_id == user.id).first()

        item = resolve_spec(record.canonical,
                            catalog.canonical if catalog else None)
        item["record_id"] = record_id

        # T# from the bound entry ONLY (install-once makes it unique);
        # unbound prints nothing, set claims never print.
        entry = db.query(ToolTableEntryRecord).filter(
            ToolTableEntryRecord.bound_instance_id == record_id,
            ToolTableEntryRecord.user_id == user.id).first()
        item["tool_number"] = \
            _leaf_value(entry.canonical, "tool_number") if entry else None

        label = None
        if record_id in overrides:
            label = db.query(Label).filter(
                Label.id == overrides[record_id],
                Label.user_id == user.id,
                Label.entity_id == record_id).first()
            if label is None:
                raise HTTPException(status_code=404, detail="not found")
        else:
            label = _newest_label(db, user, record_id)
        if label is not None:
            item["code"] = label.code
            item["url"] = label_url(request, label.code)
        elif needs_qr:
            unlabeled.append(record_id)
        items.append(item)

    if needs_qr and unlabeled:
        raise HTTPException(status_code=400, detail={
            "message": "these records have no label — label them first, "
                       "or use a QR-less template (spec-plaque)",
            "unlabeled_record_ids": unlabeled})
    return items


@router.post("/sheet")
def print_spec_sheet(payload: SheetRequest, request: Request,
                     db: Session = Depends(get_db),
                     user: User = Depends(door("read"))):
    """A PDF of spec labels for owned records — or, with format=json/csv,
    the resolved print data for bring-your-own-layout printing."""
    if payload.template not in TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail="template must be one of %s" % sorted(TEMPLATES))
    if payload.stock not in SPEC_STOCKS:
        raise HTTPException(
            status_code=400,
            detail="stock must be one of %s" % sorted(SPEC_STOCKS))
    if payload.format not in FORMATS:
        raise HTTPException(
            status_code=400,
            detail="format must be one of %s" % sorted(FORMATS))
    if not 1 <= len(payload.record_ids) <= MAX_BATCH:
        raise HTTPException(
            status_code=400,
            detail="record_ids must have 1..%d items" % MAX_BATCH)
    per_page = (SPEC_STOCKS[payload.stock]["columns"]
                * SPEC_STOCKS[payload.stock]["rows"])
    if not 0 <= payload.start_at < per_page:
        raise HTTPException(
            status_code=400,
            detail="start_at must be 0..%d for %s" % (per_page - 1,
                                                      payload.stock))

    items = _resolve_items(payload, request, db, user)

    if payload.format == "json":
        return {"items": export_rows(items)}
    if payload.format == "csv":
        out = StringIO()
        writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(export_rows(items))
        return Response(
            content=out.getvalue(), media_type="text/csv",
            headers={"Content-Disposition":
                     'attachment; filename="loobric-spec-labels.csv"'})

    pdf = render_spec_sheet(items, payload.template, payload.stock,
                            start_at=payload.start_at)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 'attachment; filename="loobric-spec-labels.pdf"'})
