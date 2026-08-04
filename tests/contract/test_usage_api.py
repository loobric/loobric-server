# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for usage over HTTP (TOOL_SCHEMA.md §7.8).

The observe door and the table sync both feed the ledger; the instance's
lifetime total is derived:usage-ledger and no door writes it directly.
"""
import pytest

BASE = "/api/v1"


def _instance(solo_client):
    return solo_client.post(f"{BASE}/tool-instance-records",
                            json={}).json()["internal"]["id"]


def _entry(solo_client, machine_id="m-1"):
    return solo_client.post(f"{BASE}/tool-table-entry-records",
                            json={"machine_id": machine_id}
                            ).json()["internal"]["id"]


def _bind(solo_client, entry_id, instance_id, move=False):
    r = solo_client.post(f"{BASE}/tool-table-entry-records/{entry_id}/bind",
                         json={"instance_id": instance_id, "move": move})
    assert r.status_code == 200, r.text
    return r


def _observe_hours(solo_client, entry_id, value):
    r = solo_client.post(f"{BASE}/tool-table-entry-records/{entry_id}/observe",
                         json={"path": "usage_hours", "value": value,
                               "unit": "h", "client": "haas",
                               "machine": "vf2"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.contract
class TestObserveDoor:
    def test_counter_lands_in_canonical(self, solo_client):
        eid = _entry(solo_client)
        doc = _observe_hours(solo_client, eid, 25.3)
        assert doc["canonical"]["usage_hours"] == {
            "value": 25.3, "unit": "h", "source": "observed:haas@vf2"}

    def test_two_observations_one_contribution(self, solo_client):
        iid, eid = _instance(solo_client), _entry(solo_client)
        _bind(solo_client, eid, iid)
        _observe_hours(solo_client, eid, 10)
        _observe_hours(solo_client, eid, 25.3)
        usage = solo_client.get(
            f"{BASE}/tool-instance-records/{iid}/usage").json()
        assert usage["total"] == pytest.approx(15.3)
        assert usage["unit"] == "h"
        (c,) = usage["contributions"]
        assert c["source"] == "observed:haas@vf2"
        assert c["amount"] == pytest.approx(15.3)
        # …and the derived canonical leaf is on the record itself.
        rec = solo_client.get(f"{BASE}/tool-instance-records/{iid}").json()
        assert rec["canonical"]["usage"]["hours"] == {
            "value": 15.3, "unit": "h", "source": "derived:usage-ledger"}

    def test_reset_then_resume(self, solo_client):
        iid, eid = _instance(solo_client), _entry(solo_client)
        _bind(solo_client, eid, iid)
        for v in (10, 25.3, 5, 8):
            _observe_hours(solo_client, eid, v)
        usage = solo_client.get(
            f"{BASE}/tool-instance-records/{iid}/usage").json()
        assert usage["total"] == pytest.approx(18.3)

    def test_unbound_hours_orphan(self, solo_client):
        iid, eid = _instance(solo_client), _entry(solo_client)
        _bind(solo_client, eid, iid)
        _observe_hours(solo_client, eid, 10)
        r = solo_client.post(
            f"{BASE}/tool-table-entry-records/{eid}/unbind")
        assert r.status_code == 200
        _observe_hours(solo_client, eid, 14)
        # The instance got nothing …
        usage = solo_client.get(
            f"{BASE}/tool-instance-records/{iid}/usage").json()
        assert usage["total"] == 0.0
        # … the entry shows the orphan.
        entry_usage = solo_client.get(
            f"{BASE}/tool-table-entry-records/{eid}/usage").json()
        (row,) = entry_usage["items"]
        assert row["orphaned"] is True
        assert row["amount"] == pytest.approx(4.0)

    def test_wrong_unit_is_400(self, solo_client):
        eid = _entry(solo_client)
        r = solo_client.post(
            f"{BASE}/tool-table-entry-records/{eid}/observe",
            json={"path": "usage_hours", "value": 10, "unit": "min",
                  "client": "haas", "machine": "vf2"})
        assert r.status_code == 400
        assert "convert" in r.json()["detail"]

    def test_total_across_two_machines(self, solo_client):
        iid = _instance(solo_client)
        e1, e2 = _entry(solo_client, "m-1"), _entry(solo_client, "m-2")
        _bind(solo_client, e1, iid)
        _observe_hours(solo_client, e1, 0)
        _observe_hours(solo_client, e1, 25.3)
        _bind(solo_client, e2, iid, move=True)   # tool physically moves
        _observe_hours(solo_client, e2, 0)
        _observe_hours(solo_client, e2, 12.1)
        usage = solo_client.get(
            f"{BASE}/tool-instance-records/{iid}/usage").json()
        assert usage["total"] == pytest.approx(37.4)
        assert set(usage["by_machine"]) == {"m-1", "m-2"}


@pytest.mark.contract
class TestSyncDoor:
    def _sync(self, solo_client, machine_id, hours):
        r = solo_client.post(f"{BASE}/tool-table-entry-records/sync", json={
            "machine_id": machine_id, "client": "haas",
            "machine_name": "vf2",
            "entries": [{"tool_number": 7, "offsets": {},
                         "usage_hours": hours}]})
        assert r.status_code == 200, r.text
        return r.json()["items"][0]

    def test_sync_carries_the_counter(self, solo_client):
        doc = self._sync(solo_client, "m-9", 25.3)
        assert doc["canonical"]["usage_hours"] == {
            "value": 25.3, "unit": "h", "source": "observed:haas@vf2"}

    def test_sync_deltas_contribute(self, solo_client):
        iid = _instance(solo_client)
        first = self._sync(solo_client, "m-9", 10.0)
        _bind(solo_client, first["internal"]["id"], iid)
        self._sync(solo_client, "m-9", 10.0)     # binding-change interval
        self._sync(solo_client, "m-9", 22.0)     # +12, bound-stable
        usage = solo_client.get(
            f"{BASE}/tool-instance-records/{iid}/usage").json()
        assert usage["total"] == pytest.approx(12.0)


@pytest.mark.contract
class TestOrphanSurfacing:
    def test_orphans_appear_in_the_inbox(self, solo_client):
        eid = _entry(solo_client, "m-orphan")
        _observe_hours(solo_client, eid, 10)
        _observe_hours(solo_client, eid, 14)     # unbound: +4 orphaned
        inbox = solo_client.get(f"{BASE}/instance-inbox").json()
        (orphan,) = [o for o in inbox["usage_orphans"]
                     if o["entry_id"] == eid]
        assert orphan["machine_id"] == "m-orphan"
        assert orphan["hours"] == pytest.approx(4.0)
        assert orphan["since"] is not None

    def test_orphans_persist_read_only(self, solo_client):
        """No dismiss, no auto-attribution: orphaned hours stay surfaced
        until a (deferred) human attribution act exists."""
        eid = _entry(solo_client, "m-orphan2")
        _observe_hours(solo_client, eid, 0)
        _observe_hours(solo_client, eid, 2)
        first = solo_client.get(f"{BASE}/instance-inbox").json()
        again = solo_client.get(f"{BASE}/instance-inbox").json()
        assert first["usage_orphans"] == again["usage_orphans"]

    def test_no_orphans_is_empty_list(self, solo_client):
        inbox = solo_client.get(f"{BASE}/instance-inbox").json()
        assert inbox["usage_orphans"] == []


@pytest.mark.contract
class TestNoDoorWritesTheTotal:
    def test_assert_usage_is_400(self, solo_client):
        iid = _instance(solo_client)
        for path in ("usage", "usage.hours"):
            r = solo_client.post(
                f"{BASE}/tool-instance-records/{iid}/assert",
                json={"path": path, "value": 999, "actor": "human@cli"})
            assert r.status_code == 400, path
            assert "derived" in r.json()["detail"]

    def test_observe_usage_is_400(self, solo_client):
        iid = _instance(solo_client)
        r = solo_client.post(
            f"{BASE}/tool-instance-records/{iid}/observe",
            json={"path": "usage.hours", "value": 999, "client": "haas",
                  "machine": "vf2"})
        assert r.status_code == 400
