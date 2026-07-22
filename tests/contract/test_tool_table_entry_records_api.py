# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the sectioned ToolTableEntryRecord facade — the machine
entry, with the install-once invariant (bind / 409 / move)."""
import pytest
from loobric_server.contract import ToolTableEntry, Provenance, UNKNOWN

BASE = "/api/v1/tool-table-entry-records"


def conforms(doc):
    ToolTableEntry.model_validate(doc)
    return doc


@pytest.mark.contract
def test_create_carries_machine_in_internal_and_unknown_canonical(solo_client):
    doc = conforms(solo_client.post(BASE, json={"machine_id": "m-mill"}).json())
    assert doc["internal"]["machine_id"] == "m-mill"
    assert doc["canonical"]["tool_number"]["source"] == UNKNOWN
    assert doc["canonical"]["bound_instance_id"]["source"] == UNKNOWN


@pytest.mark.contract
def test_observe_slot_number_and_offset(solo_client):
    rid = solo_client.post(BASE, json={"machine_id": "m-mill"}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{rid}/observe",
                     json={"path": "tool_number", "value": 5, "client": "linuxcnc", "machine": "millstone"})
    doc = conforms(solo_client.post(f"{BASE}/{rid}/observe",
                   json={"path": "offsets.diameter", "value": 6.35, "unit": "mm",
                         "client": "linuxcnc", "machine": "millstone"}).json())
    assert doc["canonical"]["tool_number"]["value"] == 5
    assert doc["canonical"]["tool_number"]["source"] == "observed:linuxcnc@millstone"
    assert doc["canonical"]["offsets"]["diameter"]["value"] == 6.35


@pytest.mark.contract
def test_bind_then_install_once_409_then_move(solo_client):
    a = solo_client.post(BASE, json={"machine_id": "m-mill"}).json()["internal"]["id"]
    b = solo_client.post(BASE, json={"machine_id": "m-lathe"}).json()["internal"]["id"]  # different machine
    # install instance into entry A
    r = solo_client.post(f"{BASE}/{a}/bind", json={"instance_id": "inst-X", "actor": "human@inbox"})
    assert r.status_code == 200, r.text
    assert conforms(r.json())["canonical"]["bound_instance_id"]["value"] == "inst-X"
    # cannot install the same physical tool in a second entry
    r = solo_client.post(f"{BASE}/{b}/bind", json={"instance_id": "inst-X", "actor": "human@inbox"})
    assert r.status_code == 409, r.text
    # move relocates it: A is vacated, B holds it
    r = solo_client.post(f"{BASE}/{b}/bind", json={"instance_id": "inst-X", "actor": "human@inbox", "move": True})
    assert r.status_code == 200, r.text
    assert solo_client.get(f"{BASE}/{a}").json()["canonical"]["bound_instance_id"]["value"] is None
    assert solo_client.get(f"{BASE}/{b}").json()["canonical"]["bound_instance_id"]["value"] == "inst-X"


@pytest.mark.contract
def test_unbind_clears_the_binding(solo_client):
    a = solo_client.post(BASE, json={"machine_id": "m-mill"}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{a}/bind", json={"instance_id": "inst-Y", "actor": "human@inbox"})
    doc = conforms(solo_client.post(f"{BASE}/{a}/unbind").json())
    assert doc["canonical"]["bound_instance_id"]["value"] is None
    assert doc["canonical"]["bound_instance_id"]["source"] == UNKNOWN


@pytest.mark.contract
def test_sync_lane_discipline(solo_client):
    rid = solo_client.post(BASE, json={"machine_id": "m-mill"}).json()["internal"]["id"]
    ok = solo_client.put(f"{BASE}/{rid}/clients/linuxcnc",
                         json={"client_version": "0.2", "data": {"raw": "T5 ..."}})
    assert ok.status_code == 200
    bad = solo_client.put(f"{BASE}/{rid}/clients/linuxcnc",
                          json={"client_version": "0.2", "canonical": {"x": 1}})
    assert bad.status_code == 400


@pytest.mark.contract
def test_a_machine_cannot_observe_the_binding(solo_client):
    rid = solo_client.post(BASE, json={"machine_id": "m-mill"}).json()["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/observe",
                         json={"path": "bound_instance_id", "value": "inst-Z",
                               "client": "linuxcnc", "machine": "millstone"})
    assert r.status_code == 400   # binding is a human assertion, not a machine observation


# -- snapshot table sync (the linuxcnc-facing push) ---------------------------

def _sync(client, machine, entries, mode="snapshot", force=False):
    return client.post(f"{BASE}/sync", json={
        "machine_id": machine, "client": "linuxcnc", "machine_name": "millstone",
        "client_version": "0.2", "mode": mode, "force": force, "entries": entries})


@pytest.mark.contract
def test_sync_observes_offsets_and_writes_section(solo_client):
    r = _sync(solo_client, "m-s0", [
        {"tool_number": 5, "offsets": {"diameter": 6.35, "diameter_unit": "mm"},
         "data": {"raw": "T5 P5 D6.35 ;endmill"}, "client_item_id": "millstone:T5"}])
    assert r.status_code == 200, r.text
    doc = conforms(r.json()["items"][0])
    assert doc["canonical"]["tool_number"]["source"] == "observed:linuxcnc@millstone"
    assert doc["canonical"]["offsets"]["diameter"]["value"] == 6.35
    assert doc["canonical"]["offsets"]["diameter"]["unit"] == "mm"
    assert doc["clients"]["linuxcnc"]["data"]["raw"] == "T5 P5 D6.35 ;endmill"


@pytest.mark.contract
def test_snapshot_removes_deleted_slot_keeps_binding(solo_client):
    _sync(solo_client, "m-s1", [{"tool_number": n, "offsets": {"diameter": float(n)}}
                                for n in (1, 2, 3)])
    eid = next(e["internal"]["id"] for e in solo_client.get(BASE).json()["items"]
               if e["internal"]["machine_id"] == "m-s1"
               and e["canonical"]["tool_number"]["value"] == 2)
    solo_client.post(f"{BASE}/{eid}/bind", json={"instance_id": "inst-keep", "actor": "human@inbox"})
    # operator deletes T3 -> snapshot of {1,2}
    r = _sync(solo_client, "m-s1", [{"tool_number": n, "offsets": {"diameter": float(n)}}
                                    for n in (1, 2)])
    assert r.json()["removed_tool_numbers"] == [3]
    rows = [e for e in solo_client.get(BASE).json()["items"] if e["internal"]["machine_id"] == "m-s1"]
    assert {e["canonical"]["tool_number"]["value"] for e in rows} == {1, 2}
    s2 = next(e for e in rows if e["canonical"]["tool_number"]["value"] == 2)
    assert s2["canonical"]["bound_instance_id"]["value"] == "inst-keep"   # binding survived


@pytest.mark.contract
def test_snapshot_mass_wipe_guarded_unless_forced(solo_client):
    _sync(solo_client, "m-s2", [{"tool_number": n, "offsets": {}} for n in range(1, 5)])
    assert _sync(solo_client, "m-s2", []).status_code == 409             # empty -> refused
    r = _sync(solo_client, "m-s2", [], force=True)
    assert r.status_code == 200 and sorted(r.json()["removed_tool_numbers"]) == [1, 2, 3, 4]


@pytest.mark.contract
def test_sync_observes_description_and_bind_seeds_the_name(solo_client):
    """The machine reports a table comment ('Probe'); it becomes the entry's
    observed description, and binding the entry with no instance_id mints a new
    instance named from it."""
    r = _sync(solo_client, "m-name", [
        {"tool_number": 1, "description": "Probe",
         "offsets": {"diameter": 2.9972, "diameter_unit": "mm"},
         "data": {"raw": "T1 P0 D+2.997200 ;Probe"}}])
    entry = r.json()["items"][0]
    assert entry["canonical"]["description"]["value"] == "Probe"
    assert entry["canonical"]["description"]["source"] == "observed:linuxcnc@millstone"
    # bind (no instance_id) -> mints a new instance whose NAME is the entry's label
    sid = entry["internal"]["id"]
    out = conforms(solo_client.post(f"{BASE}/{sid}/bind", json={"actor": "human@web"}).json())
    iid = out["canonical"]["bound_instance_id"]["value"]
    inst = solo_client.get(f"/api/v1/tool-instance-records/{iid}").json()
    assert inst["canonical"]["name"]["value"] == "Probe"
    assert inst["canonical"]["name"]["source"] == "asserted:human@web"
    assert inst["canonical"]["geometry"]["diameter"]["value"] == 2.9972


@pytest.mark.contract
def test_bind_mint_uses_caller_supplied_name(solo_client):
    """A entry synced before `description` flowed (no canonical.description): the
    UI parses the label from the raw line and passes it to bind, which names
    the minted instance even though canonical.description is absent."""
    sid = solo_client.post(BASE, json={"machine_id": "m-legacy"}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/observe", json={"path": "tool_number", "value": 1,
                     "client": "linuxcnc", "machine": "millstone"})
    assert "description" not in solo_client.get(f"{BASE}/{sid}").json()["canonical"]
    out = conforms(solo_client.post(f"{BASE}/{sid}/bind",
                   json={"actor": "human@web", "name": "Probe"}).json())
    iid = out["canonical"]["bound_instance_id"]["value"]
    inst = solo_client.get(f"/api/v1/tool-instance-records/{iid}").json()
    assert inst["canonical"]["name"]["value"] == "Probe"
    assert inst["canonical"]["name"]["source"] == "asserted:human@web"
