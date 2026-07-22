# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for the admin factory-reset wipe (POST /api/v1/admin/wipe).

Unlike /account/reset (the caller's tool data only), this deletes EVERYTHING —
all data, all accounts, all API keys, including the admin who calls it. It is
admin-only and requires an exact confirmation phrase. Tests run with auth
ENABLED (no disable_auth fixture).
"""
import pytest

CONFIRM = "WIPE ALL DATA AND ACCOUNTS"


def _register_and_login_admin(client, email="admin@example.com", pw="password123"):
    """Register the first user (=> admin) and log in (sets the session cookie)."""
    client.post("/api/v1/auth/register", json={"email": email, "password": pw})
    login = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert login.status_code == 200


@pytest.mark.integration
def test_wipe_refused_without_exact_confirmation(client):
    _register_and_login_admin(client)
    assert client.post("/api/v1/admin/wipe", json={}).status_code == 400
    assert client.post("/api/v1/admin/wipe",
                       json={"confirm": "yes"}).status_code == 400
    # Nothing was wiped — the admin still authenticates.
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.integration
def test_wipe_removes_all_data_accounts_and_keys(client, db_session):
    from loobric_server.database.schema import User, ApiKey, MachineRecord

    _register_and_login_admin(client)
    client.post("/api/v1/machine-records", json={})   # a little data
    key = client.post("/api/v1/auth/keys",
                      json={"name": "k", "scopes": ["read"]}).json()["key"]
    assert db_session.query(User).count() >= 1

    resp = client.post("/api/v1/admin/wipe", json={"confirm": CONFIRM})
    assert resp.status_code == 200
    assert resp.json()["wiped"] is True

    # Everything is gone: data, accounts, and keys.
    assert db_session.query(MachineRecord).count() == 0
    assert db_session.query(User).count() == 0
    assert db_session.query(ApiKey).count() == 0

    # The wiped admin's API key no longer authenticates.
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {key}"})
    assert me.status_code == 401


@pytest.mark.integration
def test_wipe_requires_admin(client, db_session):
    from loobric_server.database.schema import User
    from loobric_server.auth.password import hash_password

    _register_and_login_admin(client)   # first user = admin
    nonadmin = User(email="u@example.com", password_hash=hash_password("user123"),
                    is_active=True, is_admin=False, role="user", is_verified=True)
    db_session.add(nonadmin)
    db_session.commit()

    client.cookies.clear()
    client.post("/api/v1/auth/login",
                json={"email": "u@example.com", "password": "user123"})
    resp = client.post("/api/v1/admin/wipe", json={"confirm": CONFIRM})
    assert resp.status_code == 403

    # Nothing wiped — both accounts survive.
    assert db_session.query(User).count() == 2


@pytest.mark.integration
def test_after_wipe_next_registration_becomes_admin(client, db_session):
    from loobric_server.database.schema import User

    _register_and_login_admin(client, email="first@example.com")
    assert client.post("/api/v1/admin/wipe",
                       json={"confirm": CONFIRM}).status_code == 200

    client.cookies.clear()
    resp = client.post("/api/v1/auth/register",
                       json={"email": "new@example.com", "password": "password123"})
    assert resp.status_code == 201
    fresh = db_session.query(User).filter(User.email == "new@example.com").first()
    assert fresh.is_admin is True
    assert fresh.role == "admin"
