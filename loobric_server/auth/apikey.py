# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
API key management functions.

Handles API key creation, validation, listing, and revocation.

Assumptions:
- Functional programming style
- API keys are hashed with bcrypt (like passwords)
- Keys are single-use tokens shown only at creation
- Validation returns None for invalid/expired/inactive keys
- Machine ID and expiration are optional
"""
import secrets
from datetime import datetime, UTC
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from loobric_server.auth.password import hash_password, verify_password
from loobric_server.database.schema import ApiKey, User


def create_api_key(
    session: Session,
    user_id: str,
    name: str,
    scopes: list[str],
    tags: Optional[list[str]] = None,
    expires_at: Optional[datetime] = None
) -> str:
    """Create a new API key for a user.
    
    Args:
        session: Database session
        user_id: User ID who owns the key
        name: Descriptive name for the key
        scopes: List of permission scopes (e.g., ["read", "write:items"])
        tags: Optional list of tags for access control
        expires_at: Optional expiration datetime
        
    Returns:
        str: Plain text API key (only shown once)
        
    Raises:
        ValueError: If user not found
        IntegrityError: If database constraint violated
        
    Assumptions:
    - Key is cryptographically secure (32 bytes)
    - Key is hashed before storage
    - Plain key returned only at creation time
    """
    # Verify user exists
    user = session.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    
    # Generate cryptographically secure key
    plain_key = secrets.token_urlsafe(32)
    
    # Hash key for storage
    key_hash = hash_password(plain_key)
    
    # Create API key record
    api_key = ApiKey(
        user_id=user_id,
        name=name,
        key_hash=key_hash,
        scopes=scopes,
        tags=tags or [],
        expires_at=expires_at,
        is_active=True
    )
    
    session.add(api_key)
    session.commit()
    
    return plain_key


def validate_api_key(
    session: Session,
    plain_key: str
) -> Optional[Tuple[User, list[str], list[str]]]:
    """Validate an API key and return user, scopes, and tags.
    
    Args:
        session: Database session
        plain_key: Plain text API key to validate
        
    Returns:
        Tuple[User, list[str], list[str]]: User object, scopes, and tags if valid, None otherwise
        
    Assumptions:
    - Returns None for invalid keys (no exception)
    - Returns None for expired keys
    - Returns None for inactive keys
    - Checks expiration during validation
    - Returns tuple of (user, scopes, tags) on success
    """
    # Find all active API keys (need to check hashes)
    stmt = select(ApiKey).where(ApiKey.is_active == True)
    all_keys = session.scalars(stmt).all()
    
    matching_key = None
    for api_key in all_keys:
        if verify_password(plain_key, api_key.key_hash):
            matching_key = api_key
            break
    
    if matching_key is None:
        return None
    
    # Check expiration
    if matching_key.expires_at is not None:
        expires_at = matching_key.expires_at
        if expires_at.tzinfo is None:
            # Make naive datetime timezone-aware (assume UTC)
            expires_at = expires_at.replace(tzinfo=UTC)
        
        if datetime.now(UTC) > expires_at:
            return None
    
    # Get user
    user = session.get(User, matching_key.user_id)
    if user is None or not user.is_active:
        return None
    
    return (user, matching_key.scopes, matching_key.tags or [])


def list_user_api_keys(session: Session, user_id: str) -> list[ApiKey]:
    """List all API keys for a user.
    
    Args:
        session: Database session
        user_id: User ID
        
    Returns:
        list[ApiKey]: List of API key objects (without plain keys)
        
    Assumptions:
    - Returns all keys (active and inactive)
    - Does not include plain key values
    """
    stmt = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
    return list(session.scalars(stmt).all())


def revoke_api_key(session: Session, key_id: str) -> None:
    """Revoke an API key (soft delete).
    
    Args:
        session: Database session
        key_id: API key ID to revoke
        
    Raises:
        ValueError: If key not found
        
    Assumptions:
    - Sets is_active to False
    - Key remains in database (audit trail)
    - Revoked keys cannot be validated
    """
    api_key = session.get(ApiKey, key_id)
    
    if api_key is None:
        raise ValueError(f"API key {key_id} not found")
    
    api_key.is_active = False
    api_key.version += 1
    api_key.updated_at = datetime.now(UTC)
    
    session.commit()


def delete_api_key(session: Session, key_id: str) -> None:
    """Permanently delete an API key.
    
    Args:
        session: Database session
        key_id: API key ID to delete
        
    Raises:
        ValueError: If key not found
        
    Assumptions:
    - Hard delete from database
    - Cannot be recovered
    - Use revoke_api_key() for soft delete
    """
    api_key = session.get(ApiKey, key_id)
    
    if api_key is None:
        raise ValueError(f"API key {key_id} not found")
    
    session.delete(api_key)
    session.commit()


def get_api_key_by_id(session: Session, key_id: str) -> Optional[ApiKey]:
    """Get API key by ID.
    
    Args:
        session: Database session
        key_id: API key ID
        
    Returns:
        ApiKey: API key object if found, None otherwise
        
    Assumptions:
    - Does not include plain key
    """
    return session.get(ApiKey, key_id)
