# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Contract tests for door-aligned API key scopes (SCOPES_PLAN.md, grilled
2026-07-27).

The seven scopes are the doors: read, sync, observe, assert, bind, delete,
admin. Sessions and solo mode are unscoped (a session IS the human). Keys:

- a key's writes are gated by the doors it holds; the 403 names the missing
  scope
- LEGACY keys (any stored scope list that isn't a non-empty subset of the
  door names) degrade to READ-ONLY — a deliberate founder-chosen break
- creating a key requires explicit, valid door scopes (400 otherwise)
- key management (create/revoke) is session-or-solo territory — a key must
  never be able to create a stronger key
- every audit row records which credential wrote it (api_key_id + channel)

Test discipline: the server resolves session auth before Bearer auth, and the
test client keeps cookies — so every test creates its keys over the session
FIRST, then clears the cookie jar before exercising key-authenticated calls.
"""
import pytest

BASE = "/api/v1"


def _register_and_login(client, email="scopes@test.io"):
    r = client.post(f"{BASE}/auth/register",
                    json={"email": email, "password": "p" * 12})
    assert r.status_code in (200, 201), r.text
    r = client.post(f"{BASE}/auth/login",
                    json={"email": email, "password": "p" * 12})
    assert r.status_code == 200, r.text
    return client


def _key(client, scopes, name="k"):
    """Create a key via the (session-authed) client; return Bearer headers."""
    r = client.post(f"{BASE}/auth/keys", json={"name": name, "scopes": scopes})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["key"]}


def _catalog_body(pc="SCOPE-1"):
    return {"actor": "probe", "name": {"value": "scoped endmill"},
            "manufacturer": {"value": "shop"}, "product_code": {"value": pc}}


@pytest.fixture
def session_client(client):
    return _register_and_login(client)


# -- enforcement: the doors a key holds are the doors it can use --------------

def test_read_only_key_reads_but_cannot_write(session_client):
    h = _key(session_client, ["read"], "ro")
    session_client.cookies.clear()
    assert session_client.get(f"{BASE}/tool-catalog-records",
                              headers=h).status_code == 200
    r = session_client.post(f"{BASE}/tool-catalog-records",
                            headers=h, json=_catalog_body())
    assert r.status_code == 403
    assert "assert" in r.json()["detail"]        # names the missing scope


def test_agent_key_asserts_but_cannot_observe_or_delete(session_client):
    """The canonical AI key: read sync assert. Creates and asserts fine;
    observe and delete are 403 at the credential boundary — true even for a
    raw client that bypasses the MCP surface."""
    h = _key(session_client, ["read", "sync", "assert"], "agent")
    session_client.cookies.clear()
    made = session_client.post(f"{BASE}/tool-catalog-records",
                               headers=h, json=_catalog_body("SCOPE-2"))
    assert made.status_code == 200, made.text
    rid = made.json()["internal"]["id"]

    inst = session_client.post(
        f"{BASE}/tool-catalog-records/{rid}/create-instance",
        headers=h, json={})
    assert inst.status_code == 200, inst.text
    iid = inst.json()["internal"]["id"]

    obs = session_client.post(f"{BASE}/tool-instance-records/{iid}/observe",
                              headers=h,
                              json={"path": "geometry.diameter", "value": 6.35,
                                    "unit": "mm", "client": "linuxcnc",
                                    "machine": "m1"})
    assert obs.status_code == 403 and "observe" in obs.json()["detail"]

    dele = session_client.delete(f"{BASE}/tool-catalog-records/{rid}",
                                 headers=h)
    assert dele.status_code == 403 and "delete" in dele.json()["detail"]


def test_agent_key_cannot_write_tool_table_entries(session_client):
    """Entries are the machine's side of the contract (observe door): an
    assert key cannot fabricate machine state."""
    h = _key(session_client, ["read", "sync", "assert"], "agent2")
    session_client.cookies.clear()
    r = session_client.post(f"{BASE}/tool-table-entry-records", headers=h,
                            json={"machine_id": "m-1", "tool_number": 5,
                                  "client": "linuxcnc"})
    assert r.status_code == 403 and "observe" in r.json()["detail"]


def test_qa_on_create_instance_requires_observe(session_client):
    """The composite rule: create-instance is assert-door, but a `qa` payload
    writes observed:manufacturer@… — so qa additionally requires observe."""
    full = _key(session_client, ["read", "sync", "assert", "observe"], "mfr")
    agent = _key(session_client, ["read", "sync", "assert"], "agent3")
    session_client.cookies.clear()
    rid = session_client.post(f"{BASE}/tool-catalog-records", headers=full,
                              json=_catalog_body("SCOPE-QA")
                              ).json()["internal"]["id"]
    qa_body = {"qa": {"diameter": {"value": 6.34, "unit": "mm"}},
               "cert": "mfr@SN1"}
    denied = session_client.post(
        f"{BASE}/tool-catalog-records/{rid}/create-instance",
        headers=agent, json=qa_body)
    assert denied.status_code == 403 and "observe" in denied.json()["detail"]
    allowed = session_client.post(
        f"{BASE}/tool-catalog-records/{rid}/create-instance",
        headers=full, json=qa_body)
    assert allowed.status_code == 200, allowed.text


def test_agent_key_cannot_bind_or_touch_inbox(session_client):
    """The bind door is human-only doctrine made credential: bind/unbind and
    Inbox confirm/reject need the `bind` scope the agent preset lacks."""
    h = _key(session_client, ["read", "sync", "assert"], "agent4")
    session_client.cookies.clear()
    for path in ("/tool-table-entry-records/x/bind",
                 "/tool-table-entry-records/x/unbind",
                 "/instance-inbox/x/confirm",
                 "/instance-inbox/x/reject"):
        r = session_client.post(f"{BASE}{path}", headers=h, json={})
        # 403 (scope) must win before 404 (no such record) — the door check
        # runs in the dependency, before the handler ever looks anything up.
        assert r.status_code == 403, (path, r.status_code, r.text)
        assert "bind" in r.json()["detail"]


def test_read_only_key_cannot_sync(session_client):
    h = _key(session_client, ["read"], "ro2")
    session_client.cookies.clear()
    r = session_client.put(
        f"{BASE}/tool-catalog-records/x/clients/freecad",
        headers=h, json={"data": {}})
    assert r.status_code == 403 and "sync" in r.json()["detail"]


def test_full_preset_key_cannot_reach_admin_surface(session_client):
    """The `full` preset deliberately excludes admin: even an admin USER's
    full key cannot wipe, reset, or read the roster — admin power must be
    granted to the credential explicitly."""
    h = _key(session_client,
             ["read", "sync", "observe", "assert", "bind", "delete"], "fullk")
    session_client.cookies.clear()
    for method, path in (("POST", "/account/reset"),
                         ("POST", "/admin/wipe"),
                         ("GET", "/backup/export")):
        r = session_client.request(method, f"{BASE}{path}",
                                   headers=h, json={})
        assert r.status_code == 403, (path, r.status_code, r.text)
        assert "admin" in r.json()["detail"]


def test_label_verbs_ride_the_bind_door(session_client):
    """Creating labels is assert territory (the agent preset can pre-print a
    sheet), but PUTTING one on a record adjudicates a physical↔digital
    identity — bind door, like entry↔instance binding."""
    h = _key(session_client, ["read", "sync", "assert"], "labeler")
    ro = _key(session_client, ["read"], "ro-label")
    session_client.cookies.clear()

    r = session_client.post(f"{BASE}/labels", json={}, headers=ro)
    assert r.status_code == 403 and "assert" in r.json()["detail"]

    made = session_client.post(f"{BASE}/labels", json={}, headers=h)
    assert made.status_code == 200, made.text
    code = made.json()["items"][0]["code"]

    r = session_client.post(f"{BASE}/tool-instance-records/x/label",
                            headers=h, json={"code": code})
    # 403 (scope) must win before 404 (no such record).
    assert r.status_code == 403 and "bind" in r.json()["detail"]
    r = session_client.post(f"{BASE}/tool-instance-records/x/unlabel",
                            headers=h, json={"code": code})
    assert r.status_code == 403 and "bind" in r.json()["detail"]


# -- legacy keys break to read-only (founder decision, SCOPES_PLAN §5) --------

def test_legacy_scoped_key_degrades_to_read_only(session_client, db_session):
    """A pre-0.6.0 key (scopes like ["read","write"]) reads fine but its
    writes 403 with the distinct legacy message."""
    from loobric_server.auth.apikey import create_api_key
    from loobric_server.database.schema import User
    user = db_session.query(User).filter_by(email="scopes@test.io").one()
    plain = create_api_key(session=db_session, user_id=user.id,
                           name="legacy", scopes=["read", "write"])
    session_client.cookies.clear()
    h = {"Authorization": "Bearer " + plain}
    assert session_client.get(f"{BASE}/tool-catalog-records",
                              headers=h).status_code == 200
    r = session_client.post(f"{BASE}/tool-catalog-records",
                            headers=h, json=_catalog_body("SCOPE-L"))
    assert r.status_code == 403
    assert "predates" in r.json()["detail"]      # the legacy-specific message


# -- key creation: explicit, valid scopes required ----------------------------

@pytest.mark.parametrize("scopes", [None, [], ["write"], ["read", "banana"]])
def test_key_creation_requires_valid_door_scopes(session_client, scopes):
    body = {"name": "bad"}
    if scopes is not None:
        body["scopes"] = scopes
    r = session_client.post(f"{BASE}/auth/keys", json=body)
    assert r.status_code in (400, 422), r.text


def test_key_cannot_create_keys(session_client):
    """No privilege escalation: a key creating itself a stronger key would
    make scoping meaningless. Key management is session (or solo) territory."""
    h = _key(session_client, ["read", "sync", "assert"], "escalator")
    session_client.cookies.clear()
    r = session_client.post(f"{BASE}/auth/keys", headers=h,
                            json={"name": "stronger",
                                  "scopes": ["read", "delete"]})
    assert r.status_code == 403


# -- audit attribution: which credential wrote it -----------------------------

def test_audit_rows_record_credential_and_channel(session_client, db_session):
    from loobric_server.database.schema import AuditLog
    # session write first (cookie intact) …
    rid2 = session_client.post(f"{BASE}/tool-catalog-records",
                               json=_catalog_body("SCOPE-B")
                               ).json()["internal"]["id"]
    h = _key(session_client, ["read", "sync", "assert"], "audited")
    session_client.cookies.clear()
    # … then the key write with no session in play
    rid = session_client.post(f"{BASE}/tool-catalog-records", headers=h,
                              json=_catalog_body("SCOPE-A")
                              ).json()["internal"]["id"]

    row2 = db_session.query(AuditLog).filter_by(
        entity_type="tool_catalog_record", entity_id=rid2,
        operation="CREATE").one()
    assert row2.channel == "session"
    assert row2.api_key_id is None

    row = db_session.query(AuditLog).filter_by(
        entity_type="tool_catalog_record", entity_id=rid,
        operation="CREATE").one()
    assert row.channel == "api-key"
    assert row.api_key_id is not None


# -- sessions and solo stay unscoped ------------------------------------------

def test_session_can_use_every_door(session_client):
    rid = session_client.post(f"{BASE}/tool-catalog-records",
                              json=_catalog_body("SCOPE-S")
                              ).json()["internal"]["id"]
    assert session_client.delete(
        f"{BASE}/tool-catalog-records/{rid}").status_code == 200


def test_solo_mode_passes_everything(solo_client):
    r = solo_client.post(f"{BASE}/tool-catalog-records",
                         json=_catalog_body("SCOPE-SOLO"))
    assert r.status_code == 200
    rid = r.json()["internal"]["id"]
    assert solo_client.delete(
        f"{BASE}/tool-catalog-records/{rid}").status_code == 200


# -- key introspection: GET /auth/key (issue #44) ------------------------------

def test_introspect_full_scope_key(session_client):
    """A write-capable key learns its effective doors and audit identity."""
    r0 = session_client.post(f"{BASE}/auth/keys", json={
        "name": "shop-full", "scopes": ["read", "sync", "assert"]})
    assert r0.status_code == 201, r0.text
    key_id, plain = r0.json()["id"], r0.json()["key"]
    session_client.cookies.clear()
    r = session_client.get(f"{BASE}/auth/key",
                           headers={"Authorization": "Bearer " + plain})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channel"] == "api-key"
    assert body["api_key_id"] == key_id          # exactly as audit rows record it
    assert body["name"] == "shop-full"
    assert body["scopes"] == ["assert", "read", "sync"]   # effective, sorted
    assert body["read_only"] is False
    assert body["legacy"] is False


def test_introspect_deliberate_read_only_key(session_client):
    """A chosen ["read"] key is read-only but NOT legacy — the two are
    distinct facts and the response keeps them apart."""
    h = _key(session_client, ["read"], "ro-probe")
    session_client.cookies.clear()
    body = session_client.get(f"{BASE}/auth/key", headers=h).json()
    assert body["scopes"] == ["read"]
    assert body["read_only"] is True
    assert body["legacy"] is False


def test_introspect_legacy_key_reports_degradation(session_client, db_session):
    """A pre-0.6.0 key must be able to LEARN it is read-only without
    provoking a 403 — the whole point of the endpoint."""
    from loobric_server.auth.apikey import create_api_key
    from loobric_server.database.schema import User
    user = db_session.query(User).filter_by(email="scopes@test.io").one()
    plain = create_api_key(session=db_session, user_id=user.id,
                           name="old-timer", scopes=["read", "write"])
    session_client.cookies.clear()
    r = session_client.get(f"{BASE}/auth/key",
                           headers={"Authorization": "Bearer " + plain})
    assert r.status_code == 200, r.text          # no scope needed beyond validity
    body = r.json()
    assert body["scopes"] == ["read"]            # effective, not stored
    assert body["read_only"] is True
    assert body["legacy"] is True
    assert body["name"] == "old-timer"


def test_introspect_revoked_key_is_401(session_client):
    r0 = session_client.post(f"{BASE}/auth/keys", json={
        "name": "doomed", "scopes": ["read"]})
    key_id, plain = r0.json()["id"], r0.json()["key"]
    assert session_client.delete(
        f"{BASE}/auth/keys/{key_id}").status_code == 204
    session_client.cookies.clear()
    r = session_client.get(f"{BASE}/auth/key",
                           headers={"Authorization": "Bearer " + plain})
    assert r.status_code == 401


def test_introspect_session_is_unscoped(session_client):
    """Sessions are the human: no scopes field at all (unscoped ≠ empty),
    never read-only, no key identity."""
    body = session_client.get(f"{BASE}/auth/key").json()
    assert body["channel"] == "session"
    assert "scopes" not in body
    assert "api_key_id" not in body
    assert body["read_only"] is False
    assert body["legacy"] is False


def test_introspect_solo_is_unscoped(solo_client):
    body = solo_client.get(f"{BASE}/auth/key").json()
    assert body["channel"] == "solo"
    assert "scopes" not in body
    assert body["read_only"] is False


# -- machine self-registration: the observe-or-assert amendment (2026-07-30) --

def test_controller_key_can_self_register_its_machine(session_client):
    """The controller preset (read sync observe) must survive FIRST CONTACT:
    loobric-linuxcnc's first run creates the MachineRecord and asserts its
    name/controller_type before it can push a single entry. Registration
    rides observe OR assert (machine-records only)."""
    h = _key(session_client, ["read", "sync", "observe"], "cnc")
    session_client.cookies.clear()

    r = session_client.post(f"{BASE}/machine-records", json={}, headers=h)
    assert r.status_code == 200, r.text
    mid = r.json()["internal"]["id"]
    r = session_client.post(f"{BASE}/machine-records/{mid}/assert",
                            json={"path": "name", "value": "mill01",
                                  "actor": "linuxcnc"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["canonical"]["name"]["source"] == "asserted:linuxcnc"
    # ...and the same key pushes the table (observe door), completing first run.
    r = session_client.post(f"{BASE}/tool-table-entry-records/sync", json={
        "machine_id": mid, "client": "linuxcnc", "machine_name": "mill01",
        "entries": [{"tool_number": 1, "offsets": {}}]}, headers=h)
    assert r.status_code == 200, r.text


def test_observe_key_still_cannot_assert_tool_data(session_client):
    """The or-mapping is machine-records-only: an observe key remains unable
    to assert canonical facts on tool records — the blast radius of a
    shop-floor key does not widen past the machine's own identity."""
    iid = session_client.post(f"{BASE}/tool-instance-records",
                              json={}).json()["internal"]["id"]
    sid = session_client.post(f"{BASE}/tool-set-records",
                              json={}).json()["internal"]["id"]
    h = _key(session_client, ["read", "sync", "observe"], "cnc2")
    session_client.cookies.clear()

    r = session_client.post(f"{BASE}/tool-instance-records/{iid}/assert",
                            json={"path": "name", "value": "x",
                                  "actor": "linuxcnc"}, headers=h)
    assert r.status_code == 403 and "assert" in r.json()["detail"]
    r = session_client.post(f"{BASE}/tool-set-records/{sid}/assert",
                            json={"path": "name", "value": "x",
                                  "actor": "linuxcnc"}, headers=h)
    assert r.status_code == 403 and "assert" in r.json()["detail"]
