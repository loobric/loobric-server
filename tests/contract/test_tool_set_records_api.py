# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the sectioned ToolSetRecord facade — the agnostic
collection."""
import pytest
from loobric_server.contract import ToolSet, UNKNOWN

BASE = "/api/v1/tool-set-records"
ENTRY = "/api/v1/tool-table-entry-records"


def conforms(doc):
    ToolSet.model_validate(doc)
    return doc


@pytest.mark.contract
def test_create_and_assert_name_and_link(solo_client):
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    doc = conforms(solo_client.post(f"{BASE}/{rid}/assert",
                   json={"path": "name", "value": "millstone tools", "actor": "freecad"}).json())
    assert doc["canonical"]["name"]["value"] == "millstone tools"
    assert doc["canonical"]["machine_id"]["source"] == UNKNOWN   # general set until linked


@pytest.mark.contract
def test_sync_lane_discipline(solo_client):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    assert solo_client.put(f"{BASE}/{sid}/clients/freecad",
                           json={"client_version": "0.3", "data": {"fctl": {}}}).status_code == 200
    assert solo_client.put(f"{BASE}/{sid}/clients/freecad",
                           json={"client_version": "0.3", "internal": {"id": "x"}}).status_code == 400


# -- member-state reconciliation for a machine-bound set (ROUNDTRIP_FIXES S1) --

def _entry_with_number(solo_client, machine_id, tool_number):
    """Create an entry on a machine and observe its tool_number; return its id."""
    eid = solo_client.post(ENTRY, json={"machine_id": machine_id}).json()["internal"]["id"]
    solo_client.post(f"{ENTRY}/{eid}/observe",
                     json={"path": "tool_number", "value": tool_number,
                           "client": "linuxcnc", "machine": "millstone"})
    return eid


def _bound_set(solo_client, machine_id, members):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/assert",
                     json={"path": "machine_id", "value": machine_id, "actor": "freecad"})
    solo_client.post(f"{BASE}/{sid}/members", json={"members": members, "actor": "freecad"})
    return sid


@pytest.mark.contract
def test_get_machine_bound_set_marks_loaded_and_inherits_observed_number(solo_client):
    eid = _entry_with_number(solo_client, "m-loaded", 5)
    solo_client.post(f"{ENTRY}/{eid}/bind",
                     json={"instance_id": "inst-A", "actor": "human@inbox"})
    sid = _bound_set(solo_client, "m-loaded", [{"tool_record_id": "inst-A"}])

    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["state"] == "loaded"
    assert m["number"]["value"] == 5
    assert m["number"]["source"].startswith("observed:")


@pytest.mark.contract
def test_get_machine_bound_set_marks_requested_and_keeps_asserted_number(solo_client):
    eid = _entry_with_number(solo_client, "m-req", 5)
    solo_client.post(f"{ENTRY}/{eid}/bind",
                     json={"instance_id": "inst-A", "actor": "human@inbox"})
    sid = _bound_set(solo_client, "m-req",
                     [{"tool_record_id": "inst-A"},
                      {"tool_record_id": "inst-NEW", "number": 18}])

    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    by_id = {m["tool_record_id"]: m for m in doc["canonical"]["members"]}
    assert by_id["inst-A"]["state"] == "loaded"
    req = by_id["inst-NEW"]
    assert req["state"] == "requested"
    assert req["number"]["value"] == 18
    assert req["number"]["source"].startswith("asserted:")


@pytest.mark.contract
def test_get_machine_bound_set_marks_pending_bind(solo_client):
    """An unbound entry the binding engine proposes for a member's instance reads
    as 'pending bind': the machine has the entry, the binding isn't confirmed."""
    # An instance with a diameter, so the diameter heuristic proposes it.
    inst = solo_client.post("/api/v1/tool-instance-records", json={}).json()["internal"]["id"]
    solo_client.post(f"/api/v1/tool-instance-records/{inst}/assert",
                     json={"path": "geometry.diameter", "value": 6.35, "unit": "mm",
                           "actor": "freecad"})
    # An unbound entry on the machine with a matching diameter and an observed number.
    eid = _entry_with_number(solo_client, "m-pend", 18)
    solo_client.post(f"{ENTRY}/{eid}/observe",
                     json={"path": "offsets.diameter", "value": 6.35, "unit": "mm",
                           "client": "linuxcnc", "machine": "millstone"})
    # The inbox generates the open proposal naming the instance for this entry.
    solo_client.get("/api/v1/instance-inbox")

    sid = _bound_set(solo_client, "m-pend", [{"tool_record_id": inst, "number": 18}])
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["state"] == "pending bind"
    assert m["number"]["value"] == 18
    assert m["number"]["source"].startswith("observed:")


@pytest.mark.contract
def test_get_non_machine_bound_set_has_no_member_state(solo_client):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A", "number": 3}],
                           "actor": "freecad"})
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m.get("state") is None
    assert m["number"]["value"] == 3


# -- refresh-from-machine is a MERGE, not a replace (ROUNDTRIP_FIXES S2) -------
#
# The machine is authoritative for numbers/offsets, never for membership. A
# member with no machine tool-table entry (a `requested` load) must NEVER be
# deleted by a machine-driven refresh. This is distinct from POST /members
# (set_members), the human "replace membership" operation.

def _loaded_member(solo_client, machine_id, instance_id, tool_number):
    """Create a machine entry observing `tool_number`, bound to `instance_id`."""
    eid = _entry_with_number(solo_client, machine_id, tool_number)
    solo_client.post(f"{ENTRY}/{eid}/bind",
                     json={"instance_id": instance_id, "actor": "human@inbox"})


@pytest.mark.contract
def test_refresh_preserves_requested_member_18_members_17_entries(solo_client):
    """The key acceptance test (ROUNDTRIP_FIXES "Refusal"): a refresh against an
    18-member / 17-entry set leaves 18 members — the one requested member (no
    machine entry) survives; only observed numbers change."""
    machine = "m-refresh"
    members = []
    for n in range(1, 18):                       # 17 loaded members, T1..T17
        iid = f"inst-{n}"
        _loaded_member(solo_client, machine, iid, n)
        members.append({"tool_record_id": iid})
    members.append({"tool_record_id": "inst-18", "number": 18})  # 18th: requested

    sid = _bound_set(solo_client, machine, members)
    assert len(solo_client.get(f"{BASE}/{sid}").json()["canonical"]["members"]) == 18

    report = solo_client.post(f"{BASE}/{sid}/refresh", json={"actor": "human@web"}).json()
    doc = conforms(report["set"])
    by_id = {m["tool_record_id"]: m for m in doc["canonical"]["members"]}
    assert len(by_id) == 18                       # nothing deleted
    req = by_id["inst-18"]
    assert req["state"] == "requested"
    assert req["number"]["value"] == 18           # asserted preference preserved
    assert req["number"]["source"].startswith("asserted:")

    # And it persisted: a fresh GET still has all 18.
    again = solo_client.get(f"{BASE}/{sid}").json()
    assert len(again["canonical"]["members"]) == 18


@pytest.mark.contract
def test_refresh_writes_back_observed_numbers_for_loaded_members(solo_client):
    """Loaded members pick up — and persist — the machine entry's observed
    tool_number with observed provenance."""
    machine = "m-refresh-obs"
    _loaded_member(solo_client, machine, "inst-A", 7)
    # Member added with no asserted number: persisted as unknown until refresh.
    sid = _bound_set(solo_client, machine, [{"tool_record_id": "inst-A"}])

    doc = conforms(solo_client.post(f"{BASE}/{sid}/refresh", json={}).json()["set"])
    (m,) = doc["canonical"]["members"]
    assert m["state"] == "loaded"
    assert m["number"]["value"] == 7
    assert m["number"]["source"].startswith("observed:")
    assert doc["internal"]["version"] > 1         # the merge bumped the version


@pytest.mark.contract
def test_refresh_rejects_non_machine_bound_set(solo_client):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A"}], "actor": "freecad"})
    assert solo_client.post(f"{BASE}/{sid}/refresh", json={}).status_code == 400


@pytest.mark.contract
def test_refresh_surfaces_ambiguities_without_renumbering(solo_client):
    """An observed number colliding with another member's asserted preference is
    surfaced, never silently renumbered."""
    machine = "m-refresh-amb"
    _loaded_member(solo_client, machine, "inst-A", 5)        # loaded -> observed 5
    sid = _bound_set(solo_client, machine,
                     [{"tool_record_id": "inst-A"},
                      {"tool_record_id": "inst-NEW", "number": 5}])  # asserted 5

    body = solo_client.post(f"{BASE}/{sid}/refresh", json={}).json()
    conforms(body["set"])
    kinds = {a["kind"] for a in body["ambiguities"]}
    assert "number_collision" in kinds
    by_id = {m["tool_record_id"]: m for m in body["set"]["canonical"]["members"]}
    assert by_id["inst-NEW"]["number"]["value"] == 5         # preference untouched
    assert by_id["inst-NEW"]["number"]["source"].startswith("asserted:")
