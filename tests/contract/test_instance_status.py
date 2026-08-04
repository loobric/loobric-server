# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the ratified instance status vocabulary.

`retired` (2026-08-04): assert-only, ratified-not-accreted (unknown values
400), owner-only on the public page, and never an interlock — binding a
retired tool succeeds.
"""
import pytest

BASE = "/api/v1"


def _instance(solo_client):
    return solo_client.post(f"{BASE}/tool-instance-records",
                            json={}).json()["internal"]["id"]


def _assert_status(solo_client, rid, value):
    return solo_client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                            json={"path": "status", "value": value,
                                  "actor": "human@web"})


@pytest.mark.contract
class TestRatifiedVocabulary:
    def test_retire_and_return_to_service(self, solo_client):
        rid = _instance(solo_client)
        r = _assert_status(solo_client, rid, "retired")
        assert r.status_code == 200, r.text
        assert r.json()["canonical"]["status"] == {
            "value": "retired", "source": "asserted:human@web"}
        r = _assert_status(solo_client, rid, None)   # back in service
        assert r.status_code == 200, r.text
        assert r.json()["canonical"]["status"]["value"] is None

    @pytest.mark.parametrize("bad", ["available", "in_use", "in-drawer",
                                     "banana"])
    def test_unratified_values_are_400(self, solo_client, bad):
        rid = _instance(solo_client)
        r = _assert_status(solo_client, rid, bad)
        assert r.status_code == 400
        assert "ratified" in r.json()["detail"]

    def test_status_is_not_observable(self, solo_client):
        """Retirement is a judgment, not a measurement — no machine can
        observe a status value."""
        rid = _instance(solo_client)
        r = solo_client.post(f"{BASE}/tool-instance-records/{rid}/observe",
                             json={"path": "status", "value": "retired",
                                   "client": "haas", "machine": "vf2"})
        assert r.status_code == 400
        assert "asserted" in r.json()["detail"]


@pytest.mark.contract
class TestNeverAnInterlock:
    def test_binding_a_retired_tool_succeeds(self, solo_client):
        rid = _instance(solo_client)
        assert _assert_status(solo_client, rid, "retired").status_code == 200
        eid = solo_client.post(f"{BASE}/tool-table-entry-records",
                               json={"machine_id": "m-1"}
                               ).json()["internal"]["id"]
        r = solo_client.post(
            f"{BASE}/tool-table-entry-records/{eid}/bind",
            json={"instance_id": rid})
        assert r.status_code == 200, r.text

    def test_retiring_keeps_labels_and_usage(self, solo_client):
        rid = _instance(solo_client)
        (lbl,) = solo_client.post(f"{BASE}/labels",
                                  json={"entity_id": rid}).json()["items"]
        assert _assert_status(solo_client, rid, "retired").status_code == 200
        got = solo_client.get(f"{BASE}/labels/{lbl['id']}")
        assert got.status_code == 200
        assert got.json()["entity_id"] == rid
