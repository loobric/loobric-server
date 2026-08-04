# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Cross-account isolation of the v2 sectioned-records API — over HTTP.

The security assumption ("each user sees only their own data",
docs/AUTHENTICATION.md) was, until 2026-07-27, confirmed only by a DB-level
natural-key test — never by an HTTP test proving user B cannot read, assert
on, or delete user A's records. This file is that proof, and a canary: every
`_owned()` filter in the routers is load-bearing, and removing one must turn
this file red.

Why this was missable: 14 of 16 contract test files run on `solo_client`,
which bypasses auth entirely — a single-account world in which isolation
bugs are invisible by construction. These tests use the multi-user `client`
fixture with two real registered users.
"""
import pytest

BASE = "/api/v1"
PW = "p" * 12


def _register(client, email):
    r = client.post(f"{BASE}/auth/register", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _login(client, email):
    r = client.post(f"{BASE}/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text


@pytest.fixture
def two_accounts(client):
    """Register A (first user → admin) and B (created BY the admin, since
    registration is closed by default), plus a full-scope key for B.
    Returns (client, a_record_id, b_headers)."""
    _register(client, "alice@test.io")
    _login(client, "alice@test.io")
    rec = client.post(f"{BASE}/tool-catalog-records", json={
        "actor": "alice", "name": {"value": "alices endmill"},
        "manufacturer": {"value": "shop"}, "product_code": {"value": "ISO-A"}})
    assert rec.status_code == 200, rec.text
    a_rid = rec.json()["internal"]["id"]
    # admin (alice) creates bob's account — registration is closed
    _register(client, "bob@test.io")
    _login(client, "bob@test.io")
    k = client.post(f"{BASE}/auth/keys", json={
        "name": "bob-full",
        "scopes": ["read", "sync", "observe", "assert", "bind", "delete"]})
    assert k.status_code == 201, k.text
    b_headers = {"Authorization": "Bearer " + k.json()["key"]}
    return client, a_rid, b_headers


def test_b_session_cannot_see_or_touch_a_records(two_accounts):
    client, a_rid, _ = two_accounts          # client is logged in as bob
    listing = client.get(f"{BASE}/tool-catalog-records").json()["items"]
    assert all(r["internal"]["id"] != a_rid for r in listing)
    assert client.get(f"{BASE}/tool-catalog-records/{a_rid}").status_code == 404
    assert client.post(f"{BASE}/tool-catalog-records/{a_rid}/assert",
                       json={"path": "name", "value": "hijack",
                             "actor": "bob"}).status_code == 404
    assert client.delete(f"{BASE}/tool-catalog-records/{a_rid}").status_code == 404


def test_b_key_cannot_see_or_touch_a_records(two_accounts):
    """Same isolation through the API-key channel — a fully-scoped key still
    only reaches its owner's data (scopes gate doors, ownership gates rows)."""
    client, a_rid, b = two_accounts
    client.cookies.clear()
    listing = client.get(f"{BASE}/tool-catalog-records", headers=b).json()["items"]
    assert all(r["internal"]["id"] != a_rid for r in listing)
    assert client.get(f"{BASE}/tool-catalog-records/{a_rid}",
                      headers=b).status_code == 404
    assert client.delete(f"{BASE}/tool-catalog-records/{a_rid}",
                         headers=b).status_code == 404


def test_isolation_holds_across_every_entity_listing(two_accounts):
    """Bob's listings of every v2 entity are empty — nothing of Alice's leaks
    through any of the five record types."""
    client, _, _ = two_accounts
    for resource in ("tool-instance-records", "tool-catalog-records",
                     "tool-set-records", "machine-records",
                     "tool-table-entry-records", "labels"):
        r = client.get(f"{BASE}/{resource}")
        assert r.status_code == 200, (resource, r.text)
        assert r.json()["items"] == [], resource


@pytest.fixture
def two_accounts_with_label(client):
    """Alice with an instance and a label ON it, plus a blank label; the
    client is left logged in as bob. Returns (client, a_instance_id,
    a_label_id, a_code, a_blank_code)."""
    _register(client, "alice@test.io")
    _login(client, "alice@test.io")
    rid = client.post(f"{BASE}/tool-instance-records",
                      json={}).json()["internal"]["id"]
    lbl = client.post(f"{BASE}/labels",
                      json={"entity_id": rid}).json()["items"][0]
    blank = client.post(f"{BASE}/labels", json={}).json()["items"][0]
    _register(client, "bob@test.io")     # alice is admin; creates bob
    _login(client, "bob@test.io")
    return client, rid, lbl["id"], lbl["code"], blank["code"]


def test_b_cannot_see_or_touch_a_labels(two_accounts_with_label):
    """Only the generating account can see a label or put it on a record —
    cross-account is 404, never 403 (docs/SECURITY_ASSUMPTIONS.md #16)."""
    client, a_rid, a_lid, a_code, a_blank = two_accounts_with_label
    assert client.get(f"{BASE}/labels").json()["items"] == []
    assert client.get(f"{BASE}/labels/{a_lid}").status_code == 404
    assert client.delete(f"{BASE}/labels/{a_lid}").status_code == 404
    # Bob cannot use alice's BLANK code on his own record …
    b_rid = client.post(f"{BASE}/tool-instance-records",
                        json={}).json()["internal"]["id"]
    assert client.post(f"{BASE}/tool-instance-records/{b_rid}/label",
                       json={"code": a_blank}).status_code == 404
    # … nor unlabel alice's record, nor label alice's record with anything.
    assert client.post(f"{BASE}/tool-instance-records/{a_rid}/unlabel",
                       json={"code": a_code}).status_code == 404
    # Usage decomposition is owner-only like the rest of the record.
    assert client.get(
        f"{BASE}/tool-instance-records/{a_rid}/usage").status_code == 404


def test_b_session_gets_public_page_not_owner_view(two_accounts_with_label):
    """Being logged in is not being the owner: bob's scan of alice's labeled
    code renders the PUBLIC page."""
    client, _, _, a_code, _ = two_accounts_with_label
    r = client.get(f"/t/{a_code}")
    assert r.status_code == 200
    assert "your record" not in r.text.lower()
