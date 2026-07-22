# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for user registration.

Tests the open-registration model:
- First user registration is open and creates an admin
- Subsequent registrations are also open and create standard "user" accounts

This is the deliberate posture for the public sandbox (api.loobric.com): anyone
may create an account without an invite. The first user still becomes admin; no
one after them does, and open registration grants no elevated rights.

Assumptions:
- First user automatically becomes admin (is_admin=True, role="admin")
- Anyone may register an account; new accounts are non-admin "user" by default
"""
import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_first_user_registration_is_open(client):
    """Test that first user can register without authentication.
    
    Assumptions:
    - Empty database allows open registration
    - No authentication required for first user
    - Returns 201 Created with user details
    """
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "first@example.com",
            "password": "password123"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "first@example.com"
    assert "id" in data
    assert data["is_active"] is True


@pytest.mark.integration
def test_first_user_becomes_admin(client, db_session):
    """Test that first user automatically becomes admin.
    
    Assumptions:
    - First user gets is_admin=True
    - First user gets role="admin"
    - This happens automatically without explicit request
    """
    from loobric_server.database.schema import User
    
    # Register first user
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@example.com",
            "password": "password123"
        }
    )
    assert response.status_code == 201
    
    # Verify user is admin in database
    user = db_session.query(User).filter(User.email == "admin@example.com").first()
    assert user is not None
    assert user.is_admin is True
    assert user.role == "admin"


@pytest.mark.integration
def test_second_user_registration_is_open(client):
    """Test that a second user can register without authentication.

    Open registration (the sandbox posture): once the first user exists,
    anyone may still self-register. The new account is created as a non-admin
    "user".

    Assumptions:
    - Unauthenticated registration after the first user returns 201
    - The new account is a non-admin "user"
    """
    # Create first user (admin)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "first@example.com",
            "password": "password123"
        }
    )

    # Register a second user with no authentication — allowed.
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@example.com",
            "password": "password123"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "second@example.com"
    assert data["role"] == "user"


@pytest.mark.integration
def test_non_admin_can_register_users(client, db_session):
    """Test that a non-admin user can also register new accounts.

    Open registration grants no elevated rights — a logged-in non-admin can
    register another account exactly as an anonymous visitor can, and the
    created account is a non-admin "user".

    Assumptions:
    - A non-admin (authenticated) registration returns 201
    - The created account is a non-admin "user"
    """
    from loobric_server.database.schema import User
    from loobric_server.auth.password import hash_password

    # Create first user (admin)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@example.com",
            "password": "admin123"
        }
    )

    # Manually create a non-admin user in the test database
    non_admin = User(
        email="user@example.com",
        password_hash=hash_password("user123"),
        is_active=True,
        is_admin=False,
        role="user",
        is_verified=True
    )
    db_session.add(non_admin)
    db_session.commit()

    # Login as non-admin and get cookies
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "user123"
        }
    )
    assert login_response.status_code == 200

    # Extract cookies from login response
    cookies = login_response.cookies

    # Register a new account as the non-admin — allowed under open registration.
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "password123"
        },
        cookies=cookies
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["role"] == "user"

    # And it is genuinely non-admin in the database.
    created = db_session.query(User).filter(User.email == "newuser@example.com").first()
    assert created is not None
    assert created.is_admin is False
    assert created.role == "user"


@pytest.mark.integration
def test_admin_can_register_additional_users(client):
    """Test that admin users can register additional users.
    
    Assumptions:
    - Admin users can register new users
    - Authentication via session cookie works
    - Returns 201 Created for successful registration
    """
    # Register and login as admin (first user)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@example.com",
            "password": "admin123"
        }
    )
    
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "admin123"
        }
    )
    assert login_response.status_code == 200
    
    # Extract cookies from login response
    cookies = login_response.cookies
    
    # Register second user as admin (with cookies)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "password123"
        },
        cookies=cookies
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "user@example.com"


@pytest.mark.integration
def test_subsequent_users_are_not_admin(client, db_session):
    """Test that users registered by admin are not automatically admin.
    
    Assumptions:
    - Only first user becomes admin automatically
    - Users registered by admin have is_admin=False by default
    """
    from loobric_server.database.schema import User
    
    # Register first user (becomes admin)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@example.com",
            "password": "admin123"
        }
    )
    
    # Login as admin
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "admin123"
        }
    )
    cookies = login_response.cookies
    
    # Register second user (with cookies)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "password123"
        },
        cookies=cookies
    )
    
    # Verify second user is not admin
    user = db_session.query(User).filter(User.email == "user@example.com").first()
    assert user is not None
    assert user.is_admin is False
    assert user.role == "user"


@pytest.mark.integration
def test_duplicate_email_registration_fails(client):
    """Test that registering with duplicate email fails.
    
    Assumptions:
    - Email addresses must be unique
    - Returns 400 Bad Request for duplicate email
    - Error message indicates email already registered
    """
    # Register first user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "password123"
        }
    )
    
    # Login as admin
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "password123"
        }
    )
    cookies = login_response.cookies
    
    # Try to register with same email (with cookies)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "different_password"
        },
        cookies=cookies
    )
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()
