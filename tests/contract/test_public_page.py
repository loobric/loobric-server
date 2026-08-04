# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""The public spec page's no-leak invariant, proven over HTTP.

docs/SECURITY_ASSUMPTIONS.md #18: the anonymous view never identifies the
owner. The leak canary below builds a record deliberately FULL of
identifying strings — owner email, machine names in observed sources,
client names, UUIDs — and asserts none of them reach the anonymous HTML.
#19: record-supplied strings render escaped (Jinja2 autoescape).

Multi-user fixture on purpose: solo mode has no anonymous cell.
"""
import pytest

BASE = "/api/v1"
PW = "p" * 12
OWNER_EMAIL = "canary-owner@test.io"
MACHINE_NAME = "vf2-canary"
CLIENT_NAME = "linuxcnc"


def _register(client, email):
    r = client.post(f"{BASE}/auth/register", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.text


def _login(client, email):
    r = client.post(f"{BASE}/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text


@pytest.fixture
def canary(client):
    """An owner whose labeled record drips with identifying strings.
    Returns (client, code, ids) — client logged OUT."""
    _register(client, OWNER_EMAIL)
    _login(client, OWNER_EMAIL)

    cat = client.post(f"{BASE}/tool-catalog-records", json={
        "actor": "human@test", "name": {"value": "3F-6MM carbide endmill"},
        "manufacturer": {"value": "Kodiak"},
        "product_code": {"value": "KDK-3F6"},
        "geometry": {"diameter": {"value": 6.0, "unit": "mm"},
                     "flutes": {"value": 3}}})
    assert cat.status_code == 200, cat.text
    cat_id = cat.json()["internal"]["id"]

    inst = client.post(f"{BASE}/tool-catalog-records/{cat_id}/create-instance",
                       json={})
    assert inst.status_code == 200, inst.text
    inst_id = inst.json()["internal"]["id"]
    # A user-authored name plus a MACHINE observation — the observed source
    # carries the machine name, which must never surface publicly.
    r = client.post(f"{BASE}/tool-instance-records/{inst_id}/assert",
                    json={"path": "name", "value": "shop favorite 6mm",
                          "actor": "human@test"})
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/tool-instance-records/{inst_id}/observe",
                    json={"path": "geometry.diameter", "value": 5.98,
                          "unit": "mm", "client": CLIENT_NAME,
                          "machine": MACHINE_NAME})
    assert r.status_code == 200, r.text
    # A client section (opaque blob that could hold anything private).
    r = client.put(f"{BASE}/tool-instance-records/{inst_id}/clients/freecad",
                   json={"client_version": "1.0",
                         "data": {"secret_note": "paid $87, drawer B"}})
    assert r.status_code == 200, r.text

    # Usage accrues through a bound entry — the ledger sources carry the
    # machine name, which the public page must reduce away.
    entry_id = client.post(f"{BASE}/tool-table-entry-records",
                           json={"machine_id": "machine-1"}
                           ).json()["internal"]["id"]
    r = client.post(f"{BASE}/tool-table-entry-records/{entry_id}/bind",
                    json={"instance_id": inst_id})
    assert r.status_code == 200, r.text
    for value in (0, 800.5):
        r = client.post(f"{BASE}/tool-table-entry-records/{entry_id}/observe",
                        json={"path": "usage_hours", "value": value,
                              "unit": "h", "client": CLIENT_NAME,
                              "machine": MACHINE_NAME})
        assert r.status_code == 200, r.text

    # Retired is an owner-only judgment — it must never surface publicly.
    r = client.post(f"{BASE}/tool-instance-records/{inst_id}/assert",
                    json={"path": "status", "value": "retired",
                          "actor": "human@test"})
    assert r.status_code == 200, r.text

    code = client.post(f"{BASE}/labels",
                       json={"entity_id": inst_id}).json()["items"][0]["code"]
    owner_id = client.get(f"{BASE}/auth/me").json()["id"]
    client.cookies.clear()
    return client, code, {"instance": inst_id, "catalog": cat_id,
                          "owner": owner_id}


@pytest.mark.contract
class TestLeakCanary:
    def test_public_page_shows_the_spec(self, canary):
        client, code, _ = canary
        html = client.get(f"/t/{code}").text
        assert "shop favorite 6mm" in html
        assert "Kodiak" in html
        assert "KDK-3F6" in html
        assert "5.98" in html          # measured diameter (inspectable fact)
        assert "6.0" in html           # nominal diameter

    def test_public_page_identifies_nobody(self, canary):
        """The invariant itself: none of the identifying strings the record
        genuinely CONTAINS reach the anonymous HTML."""
        client, code, ids = canary
        html = client.get(f"/t/{code}").text
        for leak in (OWNER_EMAIL, "canary-owner", MACHINE_NAME, CLIENT_NAME,
                     ids["instance"], ids["catalog"], ids["owner"],
                     "secret_note", "drawer B", "observed:", "asserted:",
                     "human@", "@" + MACHINE_NAME, "retired"):
            assert leak not in html, "leaked %r" % leak

    def test_provenance_reduced_to_kind(self, canary):
        client, code, _ = canary
        html = client.get(f"/t/{code}").text
        assert ">observed<" in html    # the kind badge, alone
        assert ">asserted<" in html

    def test_usage_total_is_public_the_ledger_is_not(self, canary):
        """Publish the sum, never the ledger: the hour total is an
        inspectable fact (a better odometer); its per-machine decomposition
        stays owner-only. derived:usage-ledger is the ONE full source
        shown."""
        client, code, _ = canary
        html = client.get(f"/t/{code}").text
        assert "800.5" in html
        assert "derived:usage-ledger" in html
        assert MACHINE_NAME not in html
        assert "machine-1" not in html
        # The decomposition endpoint stays authenticated.
        assert client.get(
            f"{BASE}/tool-instance-records/%s/usage"
            % canary[2]["instance"]).status_code == 401

    def test_unlabeled_records_are_not_publicly_reachable(self, canary):
        """The label IS the public route: the record's API endpoint stays
        401 anonymously, and there is no public UUID route at all."""
        client, _, ids = canary
        r = client.get(f"{BASE}/tool-instance-records/%s" % ids["instance"])
        assert r.status_code == 401
        assert client.get("/t/%s" % ids["instance"]).status_code == 404


@pytest.mark.contract
class TestEscaping:
    def test_hostile_name_renders_escaped(self, client):
        """#19: record-supplied strings cannot inject markup into the public
        page (or any resolver page)."""
        _register(client, "xss@test.io")
        _login(client, "xss@test.io")
        rid = client.post(f"{BASE}/tool-instance-records",
                          json={}).json()["internal"]["id"]
        hostile = "<script>alert(1)</script>"
        r = client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                        json={"path": "name", "value": hostile,
                              "actor": "human@test"})
        assert r.status_code == 200, r.text
        code = client.post(f"{BASE}/labels",
                           json={"entity_id": rid}).json()["items"][0]["code"]
        client.cookies.clear()
        html = client.get(f"/t/{code}").text
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
