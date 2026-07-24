# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authentication API endpoints.

Provides REST API for user registration, login, and API key management.

Assumptions:
- All endpoints under /api/v1/auth
- API key management requires authentication (or AUTH_ENABLED=false)
- Returns JSON responses
"""
from datetime import datetime
from typing import Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie, Header, Request
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.orm import Session

from loobric_server.auth.apikey import (
    create_api_key, list_user_api_keys, revoke_api_key, delete_api_key
)
from loobric_server.auth.user import create_user, authenticate_user, get_user_by_id, get_user_by_email
from loobric_server.config import settings
from loobric_server.database.schema import Base, init_db, User
from loobric_server.database.session import get_db
import os
import secrets

SOLO_USER_EMAIL = "solo@localhost.loobric_server"


def solo_mode_enabled() -> bool:
    """Whether the server runs in solo mode (LOOBRIC_SOLO=1).

    Solo mode (v2 decision G1/D1): a single-user box — no registration,
    login, or API-key ceremony. Unauthenticated requests act as the
    built-in solo user. Checked at request time (not import time) so
    tests and process managers can toggle it via the environment.
    """
    return os.getenv("LOOBRIC_SOLO", "").strip().lower() in ("1", "true", "yes")


def get_solo_user(db: Session) -> User:
    """Return the built-in solo user, creating it on first use."""
    user = get_user_by_email(db, SOLO_USER_EMAIL)
    if user is None:
        user = create_user(db, SOLO_USER_EMAIL, secrets.token_urlsafe(24))
    return user


def open_registration_enabled() -> bool:
    """Whether non-first-user self-registration is open (LOOBRIC_OPEN_REGISTRATION=1).

    Default is CLOSED (hardening decision, MCP_PLAN.md §5/§8, 2026-07-24):
    once the first user exists, only an authenticated admin may create
    accounts, so a self-hosted server on an exposed port is safe by default.
    The public sandbox deliberately sets the flag — open registration is its
    tester funnel. Checked at request time (not import time) so tests and
    process managers can toggle it via the environment.
    """
    return os.getenv("LOOBRIC_OPEN_REGISTRATION", "").strip().lower() in ("1", "true", "yes")


def session_cookie_secure(request: Optional[Request]) -> bool:
    """Whether the session cookie should carry the Secure attribute.

    LOOBRIC_COOKIE_SECURE forces it on ("1"/"true"/"yes") or off
    ("0"/"false"/"no"). Unset means auto: Secure exactly when the request
    arrived over https. Auto keeps plain-http LAN/solo logins working; a
    hosted deployment behind a TLS terminator that doesn't forward the
    protocol must set the env var explicitly (loobric-deploy does).
    """
    raw = os.getenv("LOOBRIC_COOKIE_SECURE", "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return request is not None and request.url.scheme == "https"


# Request/Response models
class UserRegister(BaseModel):
    """Request model for user registration."""
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    """Request model for user login."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Response model for user (without password)."""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    email: str
    is_active: bool
    is_admin: bool
    role: str
    created_at: datetime


class ApiKeyCreate(BaseModel):
    """Request model for creating API key."""
    name: str
    scopes: list[str]
    tags: list[str] = []
    expires_at: Optional[datetime] = None


class ApiKeyResponse(BaseModel):
    """Response model for API key (without plain key)."""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    name: str
    scopes: list[str]
    tags: list[str]
    expires_at: Optional[datetime]
    is_active: bool
    created_at: datetime


class ApiKeyCreateResponse(ApiKeyResponse):
    """Response model for API key creation (includes plain key)."""
    key: str


# Session management
# Simple in-memory session storage (replace with Redis/DB in production)
_sessions: dict[str, str] = {}  # session_id -> user_id


def create_session(user_id: str) -> str:
    """Create a new session for a user.
    
    Args:
        user_id: User ID
        
    Returns:
        str: Session ID
        
    Assumptions:
    - Session ID is cryptographically secure
    - Stored in-memory (for production, use Redis/database)
    """
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = user_id
    return session_id


def get_session_user(session_id: Optional[str], db: Session) -> Optional[User]:
    """Get user from session ID.
    
    Args:
        session_id: Session ID from cookie
        db: Database session
        
    Returns:
        User: User object if session is valid, None otherwise
    """
    if not session_id:
        return None
    
    user_id = _sessions.get(session_id)
    if not user_id:
        return None
    
    return get_user_by_id(db, user_id)


def delete_session(session_id: str) -> None:
    """Delete a session.

    Args:
        session_id: Session ID to delete
    """
    _sessions.pop(session_id, None)


def clear_all_sessions() -> None:
    """Drop every in-memory session. Used by the admin factory-reset wipe, so no
    stale session can map to a now-deleted user."""
    _sessions.clear()


def require_auth(
    session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    request: Request = None
) -> User:
    """Require authentication for API endpoints.
    
    Args:
        session: Session ID from cookie
        authorization: Authorization header (Bearer token)
        db: Database session
        request: FastAPI request object (injected by FastAPI)
        
    Returns:
        User: Authenticated user
        
    Raises:
        HTTPException: 401 if not authenticated
        
    Assumptions:
    - Supports both session-based (cookie) and API key (Bearer) auth
    - Tries session first, then API key
    - For API key auth, stores scopes and tags in request.state for authorization
    - Solo mode (LOOBRIC_SOLO=1) bypasses authentication entirely: every
      request acts as the built-in solo user (v2 decision G1/D1)
    """
    from loobric_server.auth.apikey import validate_api_key

    # Solo mode: single-user box, no auth ceremony
    if solo_mode_enabled():
        user = get_solo_user(db)
        if request:
            request.state.scopes = []
            request.state.is_api_key_auth = False
        return user

    # Try session authentication first
    user = get_session_user(session, db)
    if user:
        if request:
            # For session auth, don't set api_key_tags (leave as None)
            # This signals session auth vs API key auth
            request.state.scopes = []
            request.state.is_api_key_auth = False
        return user
    
    # Try API key authentication
    if authorization and authorization.startswith("Bearer "):
        api_key = authorization.replace("Bearer ", "")
        result = validate_api_key(db, api_key)
        if result:
            # validate_api_key returns (user, scopes, tags)
            user, scopes, tags = result
            if request:
                # Store scopes and tags in request state for authorization
                request.state.scopes = scopes or []
                request.state.api_key_tags = tags or []
                request.state.is_api_key_auth = True
            return user
    
    raise HTTPException(
        status_code=401,
        detail="Authentication required"
    )


def get_authenticated_user(
    request: Request,
    session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db)
) -> User:
    """Return an authenticated user if auth is enabled, otherwise a test user.
    
    This allows integration tests (with auth disabled) to exercise endpoints
    without performing login flows.
    
    Args:
        request: FastAPI request object
        session: Session ID from cookie
        authorization: Authorization header (Bearer token)
        db: Database session
    """
    # Solo mode: act as the built-in solo user (no auth ceremony)
    if solo_mode_enabled():
        return get_solo_user(db)

    # If auth is enabled, enforce normal authentication
    if settings.auth_enabled:
        return require_auth(
            session=session,
            authorization=authorization,
            db=db,
            request=request
        )
    
    # Auth disabled: return or create a test user
    user = get_user_by_email(db, "test@example.com")
    if user is None:
        user = create_user(db, "test@example.com", "test-password-123")
    return user


# Router
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


# User endpoints
def _get_current_user_if_not_first(
    session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    request: Request = None
) -> Optional[User]:
    """Get current user only if this is not the first user registration.
    
    Returns None for first user (allows open registration).
    Returns authenticated user for subsequent registrations.
    """
    user_count = db.query(User).count()
    if user_count == 0:
        return None
    return require_auth(session, authorization, db, request)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserRegister,
    request: Request = None,
    session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db)
):
    """Register a new user account.

    First user registration is ALWAYS open and creates an admin account.
    After that, registration is closed by default: only an authenticated
    admin may create accounts. LOOBRIC_OPEN_REGISTRATION=1 restores open
    self-registration (the sandbox posture).

    Args:
        user_data: User registration data
        request: FastAPI request object
        session: Session ID from cookie (used only when registration is closed)
        authorization: Authorization header (used only when registration is closed)
        db: Database session

    Returns:
        UserResponse: Created user object

    Raises:
        HTTPException: 400 if email already exists; 401 if registration is
            closed and the caller is unauthenticated; 403 if closed and the
            caller is not an admin

    Assumptions:
    - Registration creates "user" role by default; first user becomes admin
    - Default posture is closed (open_registration_enabled() gate, 2026-07-24)
    - Admins can upgrade users to other roles via /api/v1/users/{id}/roles
    """
    from sqlalchemy.exc import IntegrityError

    # Check if this is the first user
    user_count = db.query(User).count()
    is_first_user = user_count == 0

    # Closed registration (the default): after the first user, only an
    # authenticated admin may create accounts.
    if not is_first_user and not open_registration_enabled():
        requester = require_auth(session=session, authorization=authorization,
                                 db=db, request=request)
        if not requester.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Registration is closed; only an administrator may create accounts"
            )

    try:
        user = create_user(
            session=db,
            email=user_data.email,
            password=user_data.password
        )
        
        # Make first user an admin
        if is_first_user:
            user.is_admin = True
            user.role = "admin"
        else:
            # Explicitly set role for subsequent users (should default to "user" but be explicit)
            user.role = "user"
        
        db.commit()
        db.refresh(user)
        
        return UserResponse(
            id=user.id,
            email=user.email,
            is_active=user.is_active,
            is_admin=user.is_admin,
            role=user.role,
            created_at=user.created_at
        )
    except IntegrityError:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )


@router.post("/login", response_model=UserResponse)
def login(
    user_data: UserLogin,
    response: Response,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Login with email and password.

    Args:
        user_data: Login credentials
        response: Response object to set cookie
        request: FastAPI request object (scheme drives the Secure default)
        db: Database session

    Returns:
        UserResponse: User object

    Raises:
        HTTPException: 401 if credentials are invalid

    Assumptions:
    - Sets session cookie on successful login
    - Cookie is httponly, samesite=lax; Secure per session_cookie_secure()
      (forced by LOOBRIC_COOKIE_SECURE, else auto on https)
    """
    user = authenticate_user(
        session=db,
        email=user_data.email,
        password=user_data.password
    )
    
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    
    # Create session and set cookie
    session_id = create_session(user.id)
    response.set_cookie(
        key="session",
        value=session_id,
        httponly=True,
        secure=session_cookie_secure(request),
        max_age=86400,  # 24 hours
        samesite="lax"
    )
    
    return UserResponse(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
        role=user.role,
        created_at=user.created_at
    )


@router.post("/logout")
def logout(
    response: Response,
    session: Annotated[str | None, Cookie()] = None
):
    """Logout and clear session.
    
    Args:
        response: Response object to clear cookie
        session: Session ID from cookie
        
    Returns:
        dict: Success message
    """
    if session:
        delete_session(session)
    
    # Clear cookie
    response.delete_cookie(key="session")
    
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_current_user(
    user: User = Depends(get_authenticated_user)
):
    """Get current authenticated user.

    Accepts either auth mechanism — a session cookie or an `Authorization:
    Bearer <api-key>` header (and solo mode) — by depending on
    get_authenticated_user, the same dependency the rest of the API uses. (It
    previously read only the session cookie, so API-key clients got a 401 here
    even though every data endpoint accepted their key.)

    Args:
        user: Authenticated user (from session, API key, or solo mode)

    Returns:
        UserResponse: Current user object

    Raises:
        HTTPException: 401 if not authenticated
    """
    return UserResponse(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
        role=user.role,
        created_at=user.created_at
    )


@router.post("/keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
def create_key(
    key_data: ApiKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user)
):
    """Create a new API key for the authenticated user.
    
    Args:
        key_data: API key creation data
        db: Database session
        user: Authenticated user (from session or API key)
        
    Returns:
        ApiKeyCreateResponse: Created key with plain text key value
    """
    from loobric_server.auth.apikey import create_api_key
    
    try:
        # Create the API key
        plain_key = create_api_key(
            session=db,
            user_id=user.id,
            name=key_data.name,
            scopes=key_data.scopes,
            tags=key_data.tags,
            expires_at=key_data.expires_at
        )
        
        # Get the created key to return full details
        keys = list_user_api_keys(db, user.id)
        created_key = keys[0]  # Most recent
        
        # Return key with plain text value
        return ApiKeyCreateResponse(
            id=created_key.id,
            name=created_key.name,
            scopes=created_key.scopes,
            tags=created_key.tags,
            expires_at=created_key.expires_at,
            is_active=created_key.is_active,
            created_at=created_key.created_at,
            key=plain_key
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/keys", response_model=list[ApiKeyResponse])
def list_keys(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    """List all API keys for the authenticated user.
    
    Args:
        db: Database session
        user: Authenticated user
        
    Returns:
        list[ApiKeyResponse]: List of API keys (without plain key values)
    """
    from loobric_server.auth.apikey import list_user_api_keys
    
    keys = list_user_api_keys(db, user.id)
    
    return [
        ApiKeyResponse(
            id=key.id,
            name=key.name,
            scopes=key.scopes,
            tags=key.tags,
            expires_at=key.expires_at,
            is_active=key.is_active,
            created_at=key.created_at
        )
        for key in keys
    ]


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(key_id: str, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    """Revoke an API key (soft delete; the key must belong to the caller).

    Args:
        key_id: API key ID to revoke
        db: Database session
        user: Authenticated user

    Returns:
        None: 204 No Content on success
    """
    from loobric_server.database.schema import ApiKey
    api_key = db.get(ApiKey, key_id)
    # 404 (not 403) for a missing OR non-owned key, so a caller cannot probe
    # which key ids exist for other users.
    if api_key is None or api_key.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")
    try:
        revoke_api_key(db, key_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class PasswordChangeRequest(BaseModel):
    """Request to change password."""
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    request: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user)
):
    """Change user password.
    
    Args:
        request: Password change request
        db: Database session
        user: Authenticated user
        
    Returns:
        dict: Success message
        
    Raises:
        HTTPException: 400 if current password is incorrect
    """
    from loobric_server.auth.user import update_user_password, AuthenticationError
    
    try:
        update_user_password(
            session=db,
            user_id=user.id,
            old_password=request.current_password,
            new_password=request.new_password
        )
        return {"message": "Password updated successfully"}
    except AuthenticationError:
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect"
        )
