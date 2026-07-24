# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for user registration.

Tests the registration model (hardened 2026-07-24, MCP_PLAN.md §5):
- First user registration is ALWAYS open and creates an admin
- After the first user, registration is CLOSED by default: only an
  authenticated admin may create accounts
- LOOBRIC_OPEN_REGISTRATION=1 restores open self-registration (the deliberate
  posture for the public sandbox at api.loobric.com, where open registration
  is the tester funnel); new accounts are non-admin "user" either way

Assumptions:
- First user automatically becomes admin (is_admin=True, role="admin")
- Default (flag unset): unauthenticated or non-admin registration after the
  first user is rejected (401 without credentials, 403 for non-admin)
- LOOBRIC_OPEN_REGISTRATION=1: anyone may register; grants no elevated rights
- The flag is read at request time, so tests toggle it via monkeypatch
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def closed_registration(monkeypatch):
    """Ensure the default posture: LOOBRIC_OPEN_REGISTRATION unset."""
    monkeypatch.delenv("LOOBRIC_OPEN_REGISTRATION", raising=False)


@pytest.fixture
def open_registration(monkeypatch):
    """The sandbox posture: LOOBRIC_OPEN_REGISTRATION=1."""
    monkeypatch.setenv("LOOBRIC_OPEN_REGISTRATION", "1")


def _register(client, email, password="password123", cookies=None):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
        cookies=cookies,
    )


def _login(client, email, password):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.cookies


@pytest.mark.integration
def test_first_user_registration_is_open(client, closed_registration):
    """First user can register without authentication, even when closed.

    Assumptions:
    - Empty database allows open registration regardless of the flag
    - Returns 201 Created with user details
    """
    response = _register(client, "first@example.com")
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "first@example.com"
    assert "id" in data
    assert data["is_active"] is True


@pytest.mark.integration
def test_first_user_becomes_admin(client, db_session, closed_registration):
    """First user automatically becomes admin.

    Assumptions:
    - First user gets is_admin=True and role="admin" automatically
    """
    from loobric_server.database.schema import User

    response = _register(client, "admin@example.com")
    assert response.status_code == 201

    user = db_session.query(User).filter(User.email == "admin@example.com").first()
    assert user is not None
    assert user.is_admin is True
    assert user.role == "admin"


@pytest.mark.integration
def test_unauthenticated_second_registration_is_rejected_by_default(
        client, closed_registration):
    """Default posture: anonymous registration after the first user fails.

    Assumptions:
    - LOOBRIC_OPEN_REGISTRATION unset means closed
    - No credentials -> 401 (authentication required)
    """
    _register(client, "first@example.com")

    response = _register(client, "second@example.com")
    assert response.status_code == 401


@pytest.mark.integration
def test_non_admin_cannot_register_users_by_default(client, db_session,
                                                    closed_registration):
    """Default posture: an authenticated non-admin cannot create accounts.

    Assumptions:
    - Closed registration is admin-only: authenticated non-admin -> 403
    """
    from loobric_server.database.schema import User
    from loobric_server.auth.password import hash_password

    _register(client, "admin@example.com", "admin123")

    non_admin = User(
        email="user@example.com",
        password_hash=hash_password("user123"),
        is_active=True,
        is_admin=False,
        role="user",
        is_verified=True,
    )
    db_session.add(non_admin)
    db_session.commit()

    cookies = _login(client, "user@example.com", "user123")
    response = _register(client, "newuser@example.com", cookies=cookies)
    assert response.status_code == 403


@pytest.mark.integration
def test_admin_can_register_users_when_closed(client, db_session,
                                              closed_registration):
    """Default posture: an authenticated admin may create accounts.

    Assumptions:
    - Admin session auth satisfies the closed-registration gate
    - The created account is a non-admin "user"
    """
    from loobric_server.database.schema import User

    _register(client, "admin@example.com", "admin123")
    cookies = _login(client, "admin@example.com", "admin123")

    response = _register(client, "user@example.com", cookies=cookies)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "user@example.com"
    assert data["role"] == "user"

    created = db_session.query(User).filter(User.email == "user@example.com").first()
    assert created is not None
    assert created.is_admin is False


@pytest.mark.integration
def test_second_user_registration_open_with_flag(client, open_registration):
    """Sandbox posture: LOOBRIC_OPEN_REGISTRATION=1 allows anonymous signup.

    Assumptions:
    - Unauthenticated registration after the first user returns 201
    - The new account is a non-admin "user"
    """
    _register(client, "first@example.com")

    response = _register(client, "second@example.com")
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "second@example.com"
    assert data["role"] == "user"


@pytest.mark.integration
def test_open_registration_grants_no_elevated_rights(client, db_session,
                                                     open_registration):
    """Sandbox posture: a non-admin can register accounts; all stay non-admin.

    Assumptions:
    - With the flag set, a logged-in non-admin registers exactly as an
      anonymous visitor can; the created account is a non-admin "user"
    """
    from loobric_server.database.schema import User
    from loobric_server.auth.password import hash_password

    _register(client, "admin@example.com", "admin123")

    non_admin = User(
        email="user@example.com",
        password_hash=hash_password("user123"),
        is_active=True,
        is_admin=False,
        role="user",
        is_verified=True,
    )
    db_session.add(non_admin)
    db_session.commit()

    cookies = _login(client, "user@example.com", "user123")
    response = _register(client, "newuser@example.com", cookies=cookies)
    assert response.status_code == 201
    assert response.json()["role"] == "user"

    created = db_session.query(User).filter(User.email == "newuser@example.com").first()
    assert created is not None
    assert created.is_admin is False


@pytest.mark.integration
def test_subsequent_users_are_not_admin(client, db_session, closed_registration):
    """Users registered by an admin are not automatically admin.

    Assumptions:
    - Only the first user becomes admin automatically
    """
    from loobric_server.database.schema import User

    _register(client, "admin@example.com", "admin123")
    cookies = _login(client, "admin@example.com", "admin123")
    _register(client, "user@example.com", cookies=cookies)

    user = db_session.query(User).filter(User.email == "user@example.com").first()
    assert user is not None
    assert user.is_admin is False
    assert user.role == "user"


@pytest.mark.integration
def test_duplicate_email_registration_fails(client, closed_registration):
    """Registering a duplicate email fails with 400.

    Assumptions:
    - Email addresses must be unique
    - The admin gate is passed (admin session) so the duplicate check is hit
    """
    _register(client, "user@example.com")
    cookies = _login(client, "user@example.com", "password123")

    response = _register(client, "user@example.com", "different_password",
                         cookies=cookies)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()
