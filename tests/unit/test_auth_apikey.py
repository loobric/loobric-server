# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Unit tests for API key authentication.

Tests API key creation, hashing, validation, scopes, and machine restrictions.

Assumptions:
- API keys belong to user accounts
- Keys have scopes (read, write:items, write:presets, etc.)
- Keys can be machine-specific
- Keys can have expiration dates
- Keys are single-use tokens (hashed in database)
"""
import pytest
from datetime import datetime, UTC, timedelta


@pytest.mark.unit
def test_create_api_key(db_session):
    """Test creating an API key for a user.
    
    Assumptions:
    - Returns plain text key (only shown once)
    - Key is hashed in database
    - Key has name, scopes, and tags
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    key_name = "Test Machine Key"
    scopes = ["read", "write:presets"]
    tags = ["monitoring", "backup"]
    
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name=key_name,
        scopes=scopes,
        tags=tags
    )
    
    assert plain_key is not None
    assert len(plain_key) > 20  # Reasonable key length
    
    # Verify tags were saved
    from loobric_server.database.schema import ApiKey
    from sqlalchemy import select
    
    stmt = select(ApiKey).where(ApiKey.user_id == user.id)
    api_key = db_session.scalar(stmt)
    assert api_key is not None
    assert api_key.tags == tags
    assert isinstance(plain_key, str)


@pytest.mark.unit
def test_api_key_hashed_in_database(db_session):
    """Test that API key is hashed in database, not stored plain text.
    
    Assumptions:
    - Plain key is never stored
    - Hash is different from plain key
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    from loobric_server.database.schema import ApiKey
    from sqlalchemy import select
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name="Test Key",
        scopes=["read"]
    )
    
    # Retrieve from database
    stmt = select(ApiKey).where(ApiKey.user_id == user.id)
    api_key = db_session.scalar(stmt)
    
    assert api_key.key_hash != plain_key
    assert len(api_key.key_hash) > 20


@pytest.mark.unit
def test_validate_api_key_success(db_session):
    """Test validating a correct API key.
    
    Assumptions:
    - Returns user object on success
    - Validates key hash
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, validate_api_key
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name="Test Key",
        scopes=["read"]
    )
    
    # Validate key
    validated_user, scopes, tags = validate_api_key(db_session, plain_key)
    
    assert validated_user is not None
    assert validated_user.id == user.id
    assert isinstance(scopes, list)
    assert isinstance(tags, list)
    assert "read" in scopes


@pytest.mark.unit
def test_validate_api_key_invalid(db_session):
    """Test that invalid API key returns None.
    
    Assumptions:
    - Invalid key returns None
    - Does not raise exception
    """
    from loobric_server.auth.apikey import validate_api_key
    
    result = validate_api_key(db_session, "invalid-key-12345")
    
    assert result is None


@pytest.mark.unit
def test_api_key_with_multiple_scopes(db_session):
    """Test API key with multiple scopes.
    
    Assumptions:
    - Scopes stored as JSON array
    - All scopes returned on validation
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, validate_api_key
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    scopes = ["read", "write:items", "write:presets"]
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name="Multi-scope Key",
        scopes=scopes
    )
    
    validated_user, returned_scopes, tags = validate_api_key(db_session, plain_key)
    
    assert set(returned_scopes) == set(scopes)
    assert isinstance(tags, list)


@pytest.mark.unit
def test_api_key_with_expiration(db_session):
    """Test creating API key with expiration date.
    
    Assumptions:
    - expires_at is optional
    - Stored as datetime
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    from loobric_server.database.schema import ApiKey
    from sqlalchemy import select
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    expires_at = datetime.now(UTC) + timedelta(days=30)
    
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name="Temporary Key",
        scopes=["read"],
        expires_at=expires_at
    )
    
    stmt = select(ApiKey).where(ApiKey.user_id == user.id)
    api_key = db_session.scalar(stmt)
    
    assert api_key.expires_at is not None


@pytest.mark.unit
def test_validate_expired_api_key(db_session):
    """Test that expired API keys are rejected.
    
    Assumptions:
    - Expired keys return None
    - Expiration checked during validation
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, validate_api_key
    from loobric_server.database.schema import ApiKey
    from sqlalchemy import select
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    # Create key with past expiration
    expires_at = datetime.now(UTC) - timedelta(days=1)
    
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name="Expired Key",
        scopes=["read"],
        expires_at=expires_at
    )
    
    # Attempt validation
    result = validate_api_key(db_session, plain_key)
    
    assert result is None


@pytest.mark.unit
def test_list_user_api_keys(db_session):
    """Test listing all API keys for a user.
    
    Assumptions:
    - Returns list of ApiKey objects
    - Does not include plain keys
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, list_user_api_keys
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    # Create multiple keys
    create_api_key(db_session, user.id, "Key 1", ["read"])
    create_api_key(db_session, user.id, "Key 2", ["write:items"])
    create_api_key(db_session, user.id, "Key 3", ["admin:users"])
    
    keys = list_user_api_keys(db_session, user.id)
    
    assert len(keys) == 3
    assert all(key.name for key in keys)
    assert all(key.scopes for key in keys)


@pytest.mark.unit
def test_revoke_api_key(db_session):
    """Test revoking an API key.
    
    Assumptions:
    - Sets is_active to False
    - Key no longer validates
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, revoke_api_key, validate_api_key
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name="To Revoke",
        scopes=["read"]
    )
    
    # Get key ID
    from loobric_server.database.schema import ApiKey
    from sqlalchemy import select
    stmt = select(ApiKey).where(ApiKey.user_id == user.id)
    api_key = db_session.scalar(stmt)
    key_id = api_key.id
    
    # Revoke
    revoke_api_key(db_session, key_id)
    
    # Verify cannot validate
    result = validate_api_key(db_session, plain_key)
    assert result is None


@pytest.mark.unit
def test_delete_api_key(db_session):
    """Test permanently deleting an API key.
    
    Assumptions:
    - Removes from database
    - Cannot be recovered
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, delete_api_key
    from loobric_server.database.schema import ApiKey
    from sqlalchemy import select
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    create_api_key(
        session=db_session,
        user_id=user.id,
        name="To Delete",
        scopes=["read"]
    )
    
    # Get key ID
    stmt = select(ApiKey).where(ApiKey.user_id == user.id)
    api_key = db_session.scalar(stmt)
    key_id = api_key.id
    
    # Delete
    delete_api_key(db_session, key_id)
    
    # Verify deleted
    api_key = db_session.get(ApiKey, key_id)
    assert api_key is None


@pytest.mark.unit
def test_api_key_user_relationship(db_session):
    """Test that API keys are linked to user accounts.
    
    Assumptions:
    - Foreign key to users table
    - Cannot create key for non-existent user
    """
    from loobric_server.auth.apikey import create_api_key
    
    # Attempt to create key for non-existent user
    with pytest.raises(Exception):  # Will be specific exception
        create_api_key(
            session=db_session,
            user_id="nonexistent-user-id",
            name="Invalid Key",
            scopes=["read"]
        )


@pytest.mark.unit
def test_inactive_api_key_not_validated(db_session):
    """Test that inactive API keys are not validated.
    
    Assumptions:
    - is_active flag checked during validation
    - Inactive keys return None
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, validate_api_key
    from loobric_server.database.schema import ApiKey
    from sqlalchemy import select
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    plain_key = create_api_key(
        session=db_session,
        user_id=user.id,
        name="Test Key",
        scopes=["read"]
    )
    
    # Manually deactivate
    stmt = select(ApiKey).where(ApiKey.user_id == user.id)
    api_key = db_session.scalar(stmt)
    api_key.is_active = False
    db_session.commit()
    
    # Attempt validation
    result = validate_api_key(db_session, plain_key)
    assert result is None
