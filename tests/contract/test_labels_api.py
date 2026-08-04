# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the labels API (docs/LABELS.md).

Labels are owner-private rows whose codes resolve publicly at /t/{code}.
The label↔record verbs (label/unlabel) live on the record router; this file
covers the whole lifecycle over HTTP on the solo fixture. Cross-account
behavior is in test_cross_account_isolation.py; the resolver page itself in
test_resolver_page.py.
"""
import pytest

BASE = "/api/v1"


def _make_instance(solo_client, name=None):
    r = solo_client.post(f"{BASE}/tool-instance-records", json={})
    assert r.status_code == 200, r.text
    rid = r.json()["internal"]["id"]
    if name:
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                             json={"path": "name", "value": name,
                                   "actor": "human@test"})
        assert r.status_code == 200, r.text
    return rid


def _make_label(solo_client, **kwargs):
    r = solo_client.post(f"{BASE}/labels", json=kwargs or {})
    assert r.status_code == 200, r.text
    return r.json()["items"]


@pytest.mark.contract
class TestCreate:
    def test_single_blank_label(self, solo_client):
        (item,) = _make_label(solo_client)
        assert len(item["code"]) == 8
        assert item["entity_id"] is None
        assert item["labeled_at"] is None
        assert item["url"].endswith("/t/" + item["code"])

    def test_batch_is_unique(self, solo_client):
        items = _make_label(solo_client, count=30)
        assert len(items) == 30
        assert len({i["code"] for i in items}) == 30

    def test_create_directly_on_record(self, solo_client):
        rid = _make_instance(solo_client)
        (item,) = _make_label(solo_client, entity_id=rid)
        assert item["entity_id"] == rid
        assert item["labeled_at"] is not None

    def test_entity_id_requires_count_one(self, solo_client):
        rid = _make_instance(solo_client)
        r = solo_client.post(f"{BASE}/labels",
                             json={"count": 2, "entity_id": rid})
        assert r.status_code == 400

    def test_unknown_target_is_404(self, solo_client):
        r = solo_client.post(f"{BASE}/labels", json={"entity_id": "nope"})
        assert r.status_code == 404

    def test_unknown_entity_type_is_400(self, solo_client):
        r = solo_client.post(f"{BASE}/labels", json={"entity_type": "drawer"})
        assert r.status_code == 400

    @pytest.mark.parametrize("count", [0, 101])
    def test_count_bounds(self, solo_client, count):
        r = solo_client.post(f"{BASE}/labels", json={"count": count})
        assert r.status_code == 400

    def test_url_uses_public_base_url_when_set(self, solo_client, monkeypatch):
        from loobric_server.config import settings
        monkeypatch.setattr(settings, "public_base_url",
                            "https://shop.example/")
        (item,) = _make_label(solo_client)
        assert item["url"] == "https://shop.example/t/" + item["code"]

    def test_url_derives_from_request_when_unset(self, solo_client):
        (item,) = _make_label(solo_client)
        assert item["url"].startswith("http://testserver/t/")


@pytest.mark.contract
class TestLabelUnlabel:
    def test_label_then_unlabel(self, solo_client):
        rid = _make_instance(solo_client)
        (item,) = _make_label(solo_client)
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/label",
                             json={"code": item["code"]})
        assert r.status_code == 200, r.text
        got = solo_client.get(f"{BASE}/labels/{item['id']}").json()
        assert got["entity_id"] == rid and got["labeled_at"] is not None

        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/unlabel",
                             json={"code": item["code"]})
        assert r.status_code == 200, r.text
        got = solo_client.get(f"{BASE}/labels/{item['id']}").json()
        assert got["entity_id"] is None and got["labeled_at"] is None

    def test_code_is_normalized_on_use(self, solo_client):
        """A hand-typed lowercase, hyphenated code works."""
        rid = _make_instance(solo_client)
        (item,) = _make_label(solo_client)
        c = item["code"]
        sloppy = ("%s-%s" % (c[:4], c[4:])).lower()
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/label",
                             json={"code": sloppy})
        assert r.status_code == 200, r.text

    def test_label_in_use_is_409(self, solo_client):
        rid1, rid2 = _make_instance(solo_client), _make_instance(solo_client)
        (item,) = _make_label(solo_client, entity_id=rid1)
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid2}/label",
                             json={"code": item["code"]})
        assert r.status_code == 409

    def test_many_labels_on_one_record(self, solo_client):
        """Deliberate: an external asset tag and a Loobric label can point at
        the same tool — the entity link is many-to-one."""
        rid = _make_instance(solo_client)
        _make_label(solo_client, entity_id=rid)
        (second,) = _make_label(solo_client)
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/label",
                             json={"code": second["code"]})
        assert r.status_code == 200, r.text
        listing = solo_client.get(f"{BASE}/labels",
                                  params={"entity_id": rid}).json()["items"]
        assert len(listing) == 2

    def test_unlabel_wrong_record_is_409(self, solo_client):
        rid1, rid2 = _make_instance(solo_client), _make_instance(solo_client)
        (item,) = _make_label(solo_client, entity_id=rid1)
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid2}/unlabel",
                             json={"code": item["code"]})
        assert r.status_code == 409

    def test_unknown_code_is_404(self, solo_client):
        rid = _make_instance(solo_client)
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/label",
                             json={"code": "AAAA2345"})
        assert r.status_code == 404

    def test_invalid_code_is_400(self, solo_client):
        rid = _make_instance(solo_client)
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/label",
                             json={"code": "not a code!"})
        assert r.status_code == 400


@pytest.mark.contract
class TestSheet:
    def test_count_mints_and_prints(self, solo_client):
        r = solo_client.post(f"{BASE}/labels/sheet",
                             json={"count": 30, "stock": "avery-5160"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        blanks = solo_client.get(f"{BASE}/labels",
                                 params={"blank": "true"}).json()["items"]
        assert len(blanks) == 30

    def test_reprint_existing_by_id(self, solo_client):
        items = _make_label(solo_client, count=3)
        r = solo_client.post(
            f"{BASE}/labels/sheet",
            json={"label_ids": [i["id"] for i in items],
                  "stock": "thermal-57x32"})
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")
        # Reprinting mints nothing new.
        assert len(solo_client.get(f"{BASE}/labels").json()["items"]) == 3

    def test_exactly_one_selector(self, solo_client):
        assert solo_client.post(f"{BASE}/labels/sheet",
                                json={}).status_code == 400
        assert solo_client.post(
            f"{BASE}/labels/sheet",
            json={"count": 1, "label_ids": ["x"]}).status_code == 400

    def test_unknown_stock_is_400(self, solo_client):
        r = solo_client.post(f"{BASE}/labels/sheet",
                             json={"count": 1, "stock": "avery-9999"})
        assert r.status_code == 400

    def test_foreign_or_unknown_id_is_404(self, solo_client):
        r = solo_client.post(f"{BASE}/labels/sheet",
                             json={"label_ids": ["nope"]})
        assert r.status_code == 404

    def test_start_at_bounds(self, solo_client):
        r = solo_client.post(f"{BASE}/labels/sheet",
                             json={"count": 1, "start_at": 30})
        assert r.status_code == 400


@pytest.mark.contract
class TestListAndDelete:
    def test_blank_filter(self, solo_client):
        rid = _make_instance(solo_client)
        _make_label(solo_client, entity_id=rid)
        _make_label(solo_client, count=2)
        blanks = solo_client.get(f"{BASE}/labels",
                                 params={"blank": "true"}).json()["items"]
        used = solo_client.get(f"{BASE}/labels",
                               params={"blank": "false"}).json()["items"]
        assert len(blanks) == 2 and len(used) == 1

    def test_delete(self, solo_client):
        (item,) = _make_label(solo_client)
        assert solo_client.delete(
            f"{BASE}/labels/{item['id']}").status_code == 200
        assert solo_client.get(
            f"{BASE}/labels/{item['id']}").status_code == 404

    def test_deleting_record_burns_its_labels(self, solo_client):
        """Deleting a record BURNS its labels (never freed for reuse — a
        resurrected code would make the old sticker lie): the label rows are
        gone and the codes resolve to nothing. Deliberate reuse is unlabel,
        before deleting."""
        rid = _make_instance(solo_client)
        (item,) = _make_label(solo_client, entity_id=rid)
        assert solo_client.delete(
            f"{BASE}/tool-instance-records/{rid}").status_code == 200
        assert solo_client.get(
            f"{BASE}/labels/{item['id']}").status_code == 404
        assert solo_client.get(f"{BASE}/labels").json()["items"] == []

    def test_unlabel_then_delete_keeps_the_label(self, solo_client):
        """The deliberate-reuse path: peel the sticker (unlabel) BEFORE
        deleting and the blank label survives."""
        rid = _make_instance(solo_client)
        (item,) = _make_label(solo_client, entity_id=rid)
        assert solo_client.post(
            f"{BASE}/tool-instance-records/{rid}/unlabel",
            json={"code": item["code"]}).status_code == 200
        assert solo_client.delete(
            f"{BASE}/tool-instance-records/{rid}").status_code == 200
        got = solo_client.get(f"{BASE}/labels/{item['id']}")
        assert got.status_code == 200
        assert got.json()["entity_id"] is None
