# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for the admin account roster (GET /api/v1/admin/users).

Read-only, admin-only listing used to operate a shared/sandbox deployment:
"how many accounts exist, and who are they?" It must never leak password hashes
or key material. Tests run with auth ENABLED (no disable_auth fixture).
"""
import pytest


def _register_and_login_admin(client, email="admin@example.com", pw="password123"):
    """Register the first user (=> admin) and log in (sets the session cookie)."""
    client.post("/api/v1/auth/register", json={"email": email, "password": pw})
    login = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert login.status_code == 200


@pytest.mark.integration
def test_list_users_counts_and_summarizes_accounts(client, db_session):
    from loobric_server.auth.password import hash_password
    from loobric_server.database.schema import User

    _register_and_login_admin(client)   # first user = admin
    db_session.add(User(email="u@example.com", password_hash=hash_password("user123"),
                        is_active=True, is_admin=False, role="user", is_verified=False))
    db_session.commit()

    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 2
    assert len(body["users"]) == 2
    emails = {u["email"] for u in body["users"]}
    assert emails == {"admin@example.com", "u@example.com"}

    admin = next(u for u in body["users"] if u["email"] == "admin@example.com")
    assert admin["is_admin"] is True
    assert admin["role"] == "admin"
    assert admin["api_key_count"] == 0


@pytest.mark.integration
def test_list_users_reports_api_key_count(client):
    _register_and_login_admin(client)
    client.post("/api/v1/auth/keys", json={"name": "k1", "scopes": ["read"]})
    client.post("/api/v1/auth/keys", json={"name": "k2", "scopes": ["read"]})

    admin = next(u for u in client.get("/api/v1/admin/users").json()["users"]
                 if u["email"] == "admin@example.com")
    assert admin["api_key_count"] == 2


@pytest.mark.integration
def test_list_users_never_leaks_secrets(client):
    _register_and_login_admin(client)
    user = client.get("/api/v1/admin/users").json()["users"][0]
    assert "password_hash" not in user
    assert "password" not in user
    assert "key_hash" not in user


@pytest.mark.integration
def test_list_users_requires_admin(client, db_session):
    from loobric_server.auth.password import hash_password
    from loobric_server.database.schema import User

    _register_and_login_admin(client)   # first user = admin
    db_session.add(User(email="u@example.com", password_hash=hash_password("user123"),
                        is_active=True, is_admin=False, role="user", is_verified=True))
    db_session.commit()

    client.cookies.clear()
    client.post("/api/v1/auth/login",
                json={"email": "u@example.com", "password": "user123"})
    assert client.get("/api/v1/admin/users").status_code == 403
