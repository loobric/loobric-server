# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Admin-only, server-wide operations.

`wipe` is a FACTORY RESET: it deletes ALL data, ALL accounts, and ALL API keys —
including the administrator who calls it. After it runs the database is empty and
the next account to register becomes the new admin (first-user-is-admin). It
exists to return a shared/sandbox deployment to a clean slate in one call.

It is guarded two ways: admin-only, and the caller must echo an exact
confirmation phrase in the body. There is no undo.

Distinct from `POST /api/v1/account/reset`, which wipes only the caller's *tool
data* and keeps every account and key.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from loobric_server.api.auth import clear_all_sessions, get_db
from loobric_server.api.backup_api import require_admin
from loobric_server.database.schema import ApiKey, Base, User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# The caller must echo this exactly — a deliberate, un-fat-fingerable phrase so a
# factory reset can never be a stray click or a default-empty body.
WIPE_CONFIRMATION = "WIPE ALL DATA AND ACCOUNTS"


class WipeRequest(BaseModel):
    confirm: str = ""


class UserSummary(BaseModel):
    """One account, as seen by an administrator. No secrets — never the password
    hash or any key material, only the count of keys the account holds."""
    id: str
    email: str
    role: str
    is_admin: bool
    is_active: bool
    is_verified: bool
    api_key_count: int
    created_at: datetime


class UserListResponse(BaseModel):
    total: int
    users: list[UserSummary]


@router.get("/users", response_model=UserListResponse)
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """List every account (admin-only). Read-only roster for operating a shared
    or sandbox deployment — answers "how many accounts exist, and who are they?"
    without exposing any password hashes or API keys.

    `total` is the account count; `users` is the per-account detail, newest first.
    """
    # One grouped query for key counts, so we don't fan out a query per user.
    key_counts = dict(
        db.query(ApiKey.user_id, func.count(ApiKey.id))
        .group_by(ApiKey.user_id)
        .all()
    )

    users = db.query(User).order_by(User.created_at.desc()).all()
    summaries = [
        UserSummary(
            id=u.id,
            email=u.email,
            role=u.role,
            is_admin=u.is_admin,
            is_active=u.is_active,
            is_verified=u.is_verified,
            api_key_count=key_counts.get(u.id, 0),
            created_at=u.created_at,
        )
        for u in users
    ]
    return UserListResponse(total=len(summaries), users=summaries)


@router.post("/wipe")
def wipe_everything(
    request: WipeRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FACTORY RESET — delete ALL data, accounts, and API keys (incl. the admin).

    Requires admin authentication AND an exact confirmation phrase. There is no
    undo. After this the database is empty; the next registration becomes the new
    admin. The schema and migration history are left intact.
    """
    if request.confirm != WIPE_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail=f"Refused. To wipe EVERYTHING (all data, accounts, and keys, "
                   f"including your own), set confirm to exactly "
                   f"'{WIPE_CONFIRMATION}'. There is no undo.",
        )

    # Delete every ORM-mapped table, children before parents (reverse FK order),
    # so users/keys are removed last without violating foreign keys. The
    # `schema_migrations` ledger is a raw table (not ORM-mapped), so the schema
    # and migration state survive — this empties the data, it doesn't un-migrate.
    deleted = {}
    for table in reversed(Base.metadata.sorted_tables):
        result = db.execute(table.delete())
        if result.rowcount:
            deleted[table.name] = result.rowcount
    db.commit()

    # Sessions live in memory, not the DB — clear them too, so no stale cookie
    # maps to a now-deleted user.
    clear_all_sessions()

    return {"wiped": True, "deleted": deleted}
