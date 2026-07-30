# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the sectioned DELETE cascades and the web UI's
create-tool-set-from-machine orchestration (existing doors, no new endpoint)."""
import pytest

INST = "/api/v1/tool-instance-records"
ENTRY = "/api/v1/tool-table-entry-records"
SET = "/api/v1/tool-set-records"
MACH = "/api/v1/machine-records"


def _machine(c, name="millstone"):
    mid = c.post(MACH, json={}).json()["internal"]["id"]
    c.post(f"{MACH}/{mid}/assert", json={"path": "name", "value": name, "actor": "human@web"})
    return mid


def _bound_slot(c, machine, tool_number, instance):
    sid = c.post(ENTRY, json={"machine_id": machine}).json()["internal"]["id"]
    c.post(f"{ENTRY}/{sid}/observe", json={"path": "tool_number", "value": tool_number,
           "client": "linuxcnc", "machine": "millstone"})
    c.post(f"{ENTRY}/{sid}/bind", json={"instance_id": instance, "actor": "human@inbox"})
    return sid


@pytest.mark.contract
def test_delete_instance_unbinds_its_slots(solo_client):
    m = _machine(solo_client)
    iid = solo_client.post(INST, json={}).json()["internal"]["id"]
    sid = _bound_slot(solo_client, m, 5, iid)
    assert solo_client.delete(f"{INST}/{iid}").status_code == 200
    # instance gone; entry survives, now unbound (its data intact)
    assert solo_client.get(f"{INST}/{iid}").status_code == 404
    entry = solo_client.get(f"{ENTRY}/{sid}").json()
    assert entry["canonical"]["bound_instance_id"]["value"] is None
    assert entry["canonical"]["tool_number"]["value"] == 5


@pytest.mark.contract
def test_delete_machine_cascades_slots_keeps_instances(solo_client):
    m = _machine(solo_client)
    iid = solo_client.post(INST, json={}).json()["internal"]["id"]
    _bound_slot(solo_client, m, 1, iid)
    r = solo_client.delete(f"{MACH}/{m}")
    assert r.status_code == 200 and r.json()["entries_removed"] == 1
    assert solo_client.get(f"{MACH}/{m}").status_code == 404
    assert solo_client.get(f"{ENTRY}?machine_id={m}").json()["items"] == []
    assert solo_client.get(f"{INST}/{iid}").status_code == 200       # instance survives


@pytest.mark.contract
def test_delete_entry_and_set(solo_client):
    m = _machine(solo_client)
    sid = solo_client.post(ENTRY, json={"machine_id": m}).json()["internal"]["id"]
    assert solo_client.delete(f"{ENTRY}/{sid}").status_code == 200
    assert solo_client.get(f"{ENTRY}/{sid}").status_code == 404
    setid = solo_client.post(SET, json={}).json()["internal"]["id"]
    assert solo_client.delete(f"{SET}/{setid}").status_code == 200


@pytest.mark.contract
def test_create_set_from_machine_orchestration(solo_client):
    """The exact sequence the web UI runs: create set, assert name, set members
    from the machine's installed instances, then `use-set` to make it the
    machine's active setup."""
    m = _machine(solo_client)
    a = solo_client.post(INST, json={}).json()["internal"]["id"]
    b = solo_client.post(INST, json={}).json()["internal"]["id"]
    _bound_slot(solo_client, m, 5, a)
    _bound_slot(solo_client, m, 7, b)

    sid = solo_client.post(SET, json={}).json()["internal"]["id"]
    solo_client.post(f"{SET}/{sid}/assert", json={"path": "name", "value": "millstone tools", "actor": "human@web"})
    r = solo_client.post(f"{SET}/{sid}/members", json={"actor": "human@web",
                         "members": [{"tool_record_id": a}, {"tool_record_id": b}]})
    assert r.status_code == 200, r.text
    doc = r.json()
    members = {mm["tool_record_id"] for mm in doc["canonical"]["members"]}
    assert members == {a, b}           # both installed instances are now members
    r = solo_client.post("/api/v1/machine-set-maps",
                         json={"machine_id": m, "tool_set_id": sid})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
