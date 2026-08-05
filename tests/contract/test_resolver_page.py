# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the label resolver page (`GET /t/{code}`).

The four cells (blank/labeled × non-owner/owner) and the no-leak rules.
These need real identity, so they run on the multi-user `client` fixture,
not solo (in solo mode every scan IS the owner, by design).
"""
import pytest

BASE = "/api/v1"
PW = "p" * 12


def _register(client, email):
    r = client.post(f"{BASE}/auth/register", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.text


def _login(client, email):
    r = client.post(f"{BASE}/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text


@pytest.fixture
def labeled_world(client):
    """Alice (owner) with a named instance, one label ON it, one blank label.
    Bob is a second account. Returns (client, code, blank_code); the client
    is left logged in as alice."""
    _register(client, "alice@test.io")
    _login(client, "alice@test.io")
    rid = client.post(f"{BASE}/tool-instance-records",
                      json={}).json()["internal"]["id"]
    r = client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                    json={"path": "name", "value": "6mm carbide endmill",
                          "actor": "human@test"})
    assert r.status_code == 200, r.text
    code = client.post(f"{BASE}/labels",
                       json={"entity_id": rid}).json()["items"][0]["code"]
    blank_code = client.post(f"{BASE}/labels",
                             json={}).json()["items"][0]["code"]
    _register(client, "bob@test.io")   # alice is admin; creates bob
    return client, code, blank_code


@pytest.mark.contract
class TestFourCells:
    def test_anonymous_scan_of_labeled_code_is_public_page(self, labeled_world):
        client, code, _ = labeled_world
        client.cookies.clear()
        r = client.get(f"/t/{code}")
        assert r.status_code == 200
        assert "6mm carbide endmill" in r.text
        assert "your record" not in r.text.lower()

    def test_owner_scan_is_owner_view(self, labeled_world):
        client, code, _ = labeled_world
        r = client.get(f"/t/{code}")
        assert r.status_code == 200
        assert "your record" in r.text.lower()
        # Deep link into the Web UI: straight to this tool's card.
        rid = client.get(f"{BASE}/labels", params={"blank": "false"}
                         ).json()["items"][0]["entity_id"]
        assert f"/ui/#tool/{rid}" in r.text

    def test_logged_in_non_owner_gets_exactly_the_public_page(self, labeled_world):
        client, code, _ = labeled_world
        client.cookies.clear()
        anonymous = client.get(f"/t/{code}")
        _login(client, "bob@test.io")
        as_bob = client.get(f"/t/{code}")
        assert as_bob.status_code == 200
        assert as_bob.text == anonymous.text

    def test_owner_public_preview_is_byte_identical(self, labeled_world):
        """?view=public: the owner previews EXACTLY what anyone else's scan
        shows — same body, no preview chrome, nothing extra."""
        client, code, blank_code = labeled_world
        preview = client.get(f"/t/{code}", params={"view": "public"})
        client.cookies.clear()
        anonymous = client.get(f"/t/{code}")
        assert preview.status_code == 200
        assert preview.text == anonymous.text
        # For an anonymous caller the param is a no-op.
        assert client.get(f"/t/{code}",
                          params={"view": "public"}).text == anonymous.text

    def test_owner_public_preview_of_blank_label_is_landing(self, labeled_world):
        client, _, blank_code = labeled_world
        r = client.get(f"/t/{blank_code}", params={"view": "public"})
        assert r.status_code == 404      # what a stranger's scan gets

    def test_owner_scan_of_blank_label(self, labeled_world):
        client, _, blank_code = labeled_world
        r = client.get(f"/t/{blank_code}")
        assert r.status_code == 200
        assert "blank" in r.text.lower()
        assert blank_code in r.text

    def test_anonymous_scan_of_blank_label_is_landing(self, labeled_world):
        client, _, blank_code = labeled_world
        client.cookies.clear()
        r = client.get(f"/t/{blank_code}")
        assert r.status_code == 404

    def test_unknown_and_foreign_blank_are_indistinguishable(self, labeled_world):
        """A foreign blank code's existence must not be probeable: same
        status, same body as a code that was never issued."""
        client, _, blank_code = labeled_world
        client.cookies.clear()
        foreign = client.get(f"/t/{blank_code}")
        # An unknown code of the same shape (0 is in the alphabet, never
        # generated adjacent to this one).
        unknown = client.get("/t/%s" % ("0" * len(blank_code)))
        assert foreign.status_code == unknown.status_code == 404
        assert foreign.text.replace(blank_code, "X" * len(blank_code)) == \
            unknown.text.replace("0" * len(blank_code), "X" * len(blank_code))


@pytest.mark.contract
class TestLookupForgiveness:
    def test_case_hyphen_and_ambiguity_insensitive(self, labeled_world):
        client, code, _ = labeled_world
        client.cookies.clear()
        sloppy = ("%s-%s" % (code[:4], code[4:])).lower()
        sloppy = sloppy.replace("0", "o").replace("1", "i")
        r = client.get(f"/t/{sloppy}")
        assert r.status_code == 200
        assert "6mm carbide endmill" in r.text

    def test_garbage_is_landing_404(self, labeled_world):
        client, _, _ = labeled_world
        client.cookies.clear()
        assert client.get("/t/not%20a%20code!").status_code == 404


@pytest.mark.contract
class TestScanAndLabel:
    def test_owner_labels_existing_record_from_scan(self, labeled_world):
        client, _, blank_code = labeled_world
        rid = client.post(f"{BASE}/tool-instance-records",
                          json={}).json()["internal"]["id"]
        r = client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                        json={"path": "name", "value": "drawer probe",
                              "actor": "human@test"})
        assert r.status_code == 200, r.text
        # The blank page offers the record as a candidate …
        page = client.get(f"/t/{blank_code}")
        assert "drawer probe" in page.text
        # … and the form labels it.
        r = client.post(f"/t/{blank_code}/label", data={"record_id": rid},
                        follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == f"/t/{blank_code}"
        after = client.get(f"/t/{blank_code}")
        assert "drawer probe" in after.text
        assert "your record" in after.text.lower()

    def test_owner_creates_record_from_scan(self, labeled_world):
        client, _, blank_code = labeled_world
        r = client.post(f"/t/{blank_code}/label",
                        data={"new_name": "fresh from the drawer"},
                        follow_redirects=False)
        assert r.status_code == 303
        after = client.get(f"/t/{blank_code}")
        assert "fresh from the drawer" in after.text
        # The record is real and carries the human assertion.
        items = client.get(f"{BASE}/tool-instance-records").json()["items"]
        made = [i for i in items
                if i["canonical"]["name"]["value"] == "fresh from the drawer"]
        assert len(made) == 1
        assert made[0]["canonical"]["name"]["source"] == \
            "asserted:human@label-page"

    def test_anonymous_post_is_landing(self, labeled_world):
        client, _, blank_code = labeled_world
        client.cookies.clear()
        r = client.post(f"/t/{blank_code}/label",
                        data={"new_name": "hijack"}, follow_redirects=False)
        assert r.status_code == 404

    def test_non_owner_post_is_landing(self, labeled_world):
        client, _, blank_code = labeled_world
        client.cookies.clear()
        _login(client, "bob@test.io")
        r = client.post(f"/t/{blank_code}/label",
                        data={"new_name": "hijack"}, follow_redirects=False)
        assert r.status_code == 404
        # And nothing was created or labeled.
        _login(client, "alice@test.io")
        got = client.get(f"{BASE}/labels", params={"blank": "true"}).json()
        assert len(got["items"]) == 1

    def test_empty_form_is_400(self, labeled_world):
        client, _, blank_code = labeled_world
        r = client.post(f"/t/{blank_code}/label", data={},
                        follow_redirects=False)
        assert r.status_code == 400

    def test_double_submit_just_redirects(self, labeled_world):
        client, code, _ = labeled_world
        r = client.post(f"/t/{code}/label", data={"new_name": "again"},
                        follow_redirects=False)
        assert r.status_code == 303


@pytest.mark.contract
class TestHeaders:
    def test_no_store_everywhere(self, labeled_world):
        client, code, blank_code = labeled_world
        for path in (f"/t/{code}", f"/t/{blank_code}", "/t/00000000"):
            r = client.get(path)
            assert r.headers["cache-control"] == "no-store", path

    def test_deleted_label_stops_resolving(self, labeled_world):
        client, code, _ = labeled_world
        label_id = client.get(
            f"{BASE}/labels", params={"blank": "false"}).json()["items"][0]["id"]
        assert client.delete(f"{BASE}/labels/{label_id}").status_code == 200
        assert client.get(f"/t/{code}").status_code == 404
