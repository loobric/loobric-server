# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""The label resolver: `GET /t/{code}` (docs/LABELS.md).

The one HTML surface the server owns. A printed label is permanent ink, so
this route is the permanent indirection layer between the sticker and
whatever the right destination is *today* — it must outlive API versions,
which is why it lives outside `/api` and outside the OpenAPI contract
(include_in_schema=False keeps `/t` out of the published vocabulary
surface).

Four cells, by label state × caller identity:

                     anonymous / non-owner        owner
    blank label      landing page (404)           blank-label page
    labeled          PUBLIC spec page             owner view

Assumptions:
- The response for an UNKNOWN code and for someone else's BLANK label is
  the same 404 landing page — a foreign blank code's existence leaks
  nothing (docs/SECURITY_ASSUMPTIONS.md).
- A logged-in NON-owner gets exactly the anonymous public page: ownership,
  not authentication, is what unlocks more.
- `Cache-Control: no-store` everywhere: what a code resolves to changes
  with labeling, and a stale cached owner view on a shared machine would be
  a leak.
"""
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from loobric_server.audit import create_audit_log

from loobric_server.api.auth import get_db, get_optional_user
from loobric_server.database.schema import (
    Label, ToolCatalogRecord, ToolInstanceRecord, User,
)
from loobric_server.label_codes import normalize_code
from loobric_server.public_view import public_projection
from loobric_server.web.templating import render

router = APIRouter(tags=["resolver"], include_in_schema=False)

_HEADERS = {"Cache-Control": "no-store"}


def _page(template: str, status_code: int = 200, **context) -> HTMLResponse:
    return HTMLResponse(render(template, **context), status_code=status_code,
                        headers=_HEADERS)


def _landing(code: Optional[str]) -> HTMLResponse:
    return _page("label_landing.html", status_code=404, code=code)


@router.get("/t/{code}", response_class=HTMLResponse)
def resolve_label(code: str, request: Request, view: Optional[str] = None,
                  db: Session = Depends(get_db),
                  user: Optional[User] = Depends(get_optional_user)):
    try:
        normalized = normalize_code(code)
    except ValueError:
        return _landing(None)

    label = db.query(Label).filter(Label.code == normalized).first()
    if label is None:
        return _landing(normalized)

    is_owner = user is not None and user.id == label.user_id
    # ?view=public: the owner previewing what anyone else's scan shows —
    # byte-identical to the anonymous rendering (it can only ever REDUCE
    # what is shown, so it needs no gating; for a non-owner it's a no-op).
    if view == "public":
        is_owner = False

    instance = None
    if label.entity_id is not None and label.entity_type == "tool_instance":
        instance = db.query(ToolInstanceRecord).filter(
            ToolInstanceRecord.id == label.entity_id,
            ToolInstanceRecord.user_id == label.user_id).first()

    if instance is None:
        # Blank (or pointing at nothing, which is the same thing here).
        if is_owner:
            records = db.query(ToolInstanceRecord).filter(
                ToolInstanceRecord.user_id == user.id).order_by(
                ToolInstanceRecord.created_at.desc()).all()
            candidates = [
                {"id": r.id,
                 "name": ((r.canonical or {}).get("name") or {}).get("value")
                 or "unnamed tool"}
                for r in records]
            return _page("label_blank.html", code=normalized,
                         records=candidates)
        return _landing(normalized)

    catalog = None
    if instance.catalog_type_id:
        catalog = db.query(ToolCatalogRecord).filter(
            ToolCatalogRecord.id == instance.catalog_type_id,
            ToolCatalogRecord.user_id == label.user_id).first()

    tool = public_projection(instance, catalog)
    if is_owner:
        # The record id is owner-only context — it feeds the Web UI deep
        # link and never appears on the public template.
        return _page("label_owner.html", code=normalized, tool=tool,
                     record_id=instance.id)
    return _page("public_tool.html", code=normalized, tool=tool)


@router.post("/t/{code}/label")
def label_from_scan(code: str, request: Request,
                    record_id: Optional[str] = Form(None),
                    new_name: Optional[str] = Form(None),
                    db: Session = Depends(get_db),
                    user: Optional[User] = Depends(get_optional_user)):
    """The scan-and-label flow: the owner scanned a blank label at the
    drawer and labels an existing record — or creates one on the spot —
    from the phone in their hand.

    Session/solo only (a browser form; API keys use the record router's
    label endpoint, where the bind door is enforced). A non-owner — or an
    anonymous caller — gets the same landing 404 the GET gives them: this
    endpoint never confirms a foreign code exists. CSRF posture is the
    API's: the SameSite=Lax session cookie.
    """
    try:
        normalized = normalize_code(code)
    except ValueError:
        return _landing(None)
    label = db.query(Label).filter(Label.code == normalized).first()
    if label is None or user is None or user.id != label.user_id:
        return _landing(normalized)
    if getattr(request.state, "auth_channel", None) == "api-key":
        # Keys go through the API, where door scopes are enforced.
        return _landing(normalized)
    if label.entity_id is not None:
        # Already labeled (double-submit, stale tab): just show it.
        return RedirectResponse("/t/%s" % normalized, status_code=303)

    if record_id:
        instance = db.query(ToolInstanceRecord).filter(
            ToolInstanceRecord.id == record_id,
            ToolInstanceRecord.user_id == user.id).first()
        if instance is None:
            return _landing(normalized)
    elif new_name and new_name.strip():
        # Mint the record here, the way the create door would: blank
        # canonical, then the name as a human assertion from this page.
        instance = ToolInstanceRecord(
            canonical={
                "name": {"value": new_name.strip(),
                         "source": "asserted:human@label-page"},
                "catalog_type_id": {"value": None, "source": "unknown"},
                "geometry": {},
            },
            clients={}, catalog_type_id=None,
            user_id=user.id, created_by=user.id, updated_by=user.id)
        db.add(instance)
        db.flush()
        create_audit_log(session=db, user_id=user.id, operation="CREATE",
                         entity_type="tool_instance_record",
                         entity_id=instance.id)
        create_audit_log(session=db, user_id=user.id, operation="ASSERT",
                         entity_type="tool_instance_record",
                         entity_id=instance.id,
                         changes={"path": "name",
                                  "source": "asserted:human@label-page"})
    else:
        return _page("label_blank.html", status_code=400, code=normalized,
                     records=[], error="pick a record or name a new one")

    label.entity_type = "tool_instance"
    label.entity_id = instance.id
    label.labeled_at = datetime.now(UTC)
    label.version += 1
    label.updated_by = user.id
    create_audit_log(session=db, user_id=user.id, operation="LABEL",
                     entity_type="label", entity_id=label.id,
                     changes={"code": normalized, "record_id": instance.id})
    db.commit()
    return RedirectResponse("/t/%s" % normalized, status_code=303)
