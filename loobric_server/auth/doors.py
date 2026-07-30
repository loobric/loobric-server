# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Door-aligned API key scopes (SCOPES_PLAN.md, grilled & locked 2026-07-27).

The seven scopes ARE the doors the schema already defines: read, sync,
observe, assert, bind, delete, admin. A key's writes are gated by the doors
it holds; sessions and solo mode are unscoped — a session is the human, and
scopes are a property of *delegated* credentials only.

Assumptions:
- LEGACY keys — any stored scope list that is not a non-empty subset of
  DOORS (e.g. ["read","write"], free text, []) — degrade to READ-ONLY at
  validation time. This is a deliberate, founder-chosen break (0.6.0): the
  old scope strings were never enforced, and grandfathering them as full
  access would silently perpetuate unscoped credentials. The legacy 403
  carries its own message so the fix is obvious.
- The 403 always names the missing scope and the remedy — never a bare
  "forbidden".
- `door(...)` replaces `get_authenticated_user` in a route signature; it
  resolves the same user and additionally enforces scopes for API-key auth.
  FastAPI's per-request dependency cache means the underlying auth runs once.
"""
from typing import Any

from fastapi import Depends, HTTPException, Request

DOORS = ("read", "sync", "observe", "assert", "bind", "delete", "admin")

LEGACY_DETAIL = (
    "This API key predates door scopes and is now read-only. Create a new "
    "key with the scopes you need (loobric create-key --preset, or the Web "
    "UI Account tab)."
)


def is_legacy(scopes: Any) -> bool:
    """A scope list the door model doesn't recognize (pre-0.6.0 key)."""
    s = set(scopes or [])
    return not (s and s.issubset(DOORS))


def effective_doors(scopes: Any) -> set:
    """The doors a key actually holds: its scopes, or {'read'} for legacy."""
    s = set(scopes or [])
    if s and s.issubset(DOORS):
        return s
    return {"read"}


def check_doors(request: Request, required: tuple) -> None:
    """Enforce `required` doors for API-key auth; sessions/solo pass.

    Reads the channel and scopes that get_authenticated_user stored on
    request.state. Raises 403 naming the missing scope."""
    channel = getattr(request.state, "auth_channel", None)
    if channel != "api-key":
        return                                    # session / solo / unset
    scopes = getattr(request.state, "scopes", [])
    held = effective_doors(scopes)
    missing = [d for d in required if d not in held]
    if not missing:
        return
    if is_legacy(scopes):
        raise HTTPException(status_code=403, detail=LEGACY_DETAIL)
    raise HTTPException(
        status_code=403,
        detail="This API key lacks the %r scope. Create a key that grants "
               "it, or use the Web UI." % missing[0])


def door(*required: str):
    """Dependency factory: authenticate AND require these door scopes.

    Use in place of get_authenticated_user:
        user: User = Depends(door("assert"))
    """
    unknown = [d for d in required if d not in DOORS]
    if unknown:                                   # programmer error, not 403
        raise ValueError("unknown door(s): %r" % unknown)

    from loobric_server.api.auth import get_authenticated_user

    def dependency(request: Request,
                   user=Depends(get_authenticated_user)):
        check_doors(request, required)
        return user

    return dependency


def door_any(*alternatives: str):
    """Dependency factory: authenticate AND require AT LEAST ONE of these
    door scopes. The rare or-shaped mapping — used where one act legitimately
    belongs to two credential kinds (machine self-registration: the controller
    key's `observe` OR a human/agent `assert`). Prefer `door()`; every use of
    this is a scope-mapping decision that belongs in SCOPES_PLAN.md."""
    unknown = [d for d in alternatives if d not in DOORS]
    if unknown:                                   # programmer error, not 403
        raise ValueError("unknown door(s): %r" % unknown)

    from loobric_server.api.auth import get_authenticated_user

    def dependency(request: Request,
                   user=Depends(get_authenticated_user)):
        channel = getattr(request.state, "auth_channel", None)
        if channel != "api-key":
            return user                           # session / solo / unset
        scopes = getattr(request.state, "scopes", [])
        held = effective_doors(scopes)
        if held.intersection(alternatives):
            return user
        if is_legacy(scopes):
            raise HTTPException(status_code=403, detail=LEGACY_DETAIL)
        raise HTTPException(
            status_code=403,
            detail="This API key lacks the %r scope (any one suffices). "
                   "Create a key that grants one, or use the Web UI."
                   % (list(alternatives),))

    return dependency


def session_or_solo_only():
    """Dependency: authenticate but refuse API-key auth outright.

    For key management and password change: a key must never create or
    revoke keys (privilege escalation) — that is session (human) or solo
    territory."""
    from loobric_server.api.auth import get_authenticated_user

    def dependency(request: Request,
                   user=Depends(get_authenticated_user)):
        if getattr(request.state, "auth_channel", None) == "api-key":
            raise HTTPException(
                status_code=403,
                detail="API keys cannot manage keys or credentials — sign "
                       "in (Web UI or loobric login) to do this.")
        return user

    return dependency
