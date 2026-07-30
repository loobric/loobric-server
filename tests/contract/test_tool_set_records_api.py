# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the sectioned ToolSetRecord facade — the agnostic,
purely CAM-owned collection (MAPPING_PLAN.md: the machine relationship is a
setup, never a set field; member numbers are durable claims)."""
import pytest
from loobric_server.contract import ToolSet, UNKNOWN

BASE = "/api/v1/tool-set-records"
ENTRY = "/api/v1/tool-table-entry-records"
MAPS = "/api/v1/machine-set-maps"


def conforms(doc):
    ToolSet.model_validate(doc)
    return doc


@pytest.mark.contract
def test_create_and_assert_name(solo_client):
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    doc = conforms(solo_client.post(f"{BASE}/{rid}/assert",
                   json={"path": "name", "value": "millstone tools", "actor": "freecad"}).json())
    assert doc["canonical"]["name"]["value"] == "millstone tools"
    assert "machine_id" not in doc["canonical"]   # the link is a setup, not a field


@pytest.mark.contract
def test_machine_id_is_no_longer_assertable(solo_client):
    """BREAKING (0.7.0): linking is `use-set` (POST /machine-set-maps), not an
    assert on the set. The old path is a loud 400, never a silent no-op."""
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/assert",
                         json={"path": "machine_id", "value": "m-x", "actor": "freecad"})
    assert r.status_code == 400


@pytest.mark.contract
def test_sync_lane_discipline(solo_client):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    assert solo_client.put(f"{BASE}/{sid}/clients/freecad",
                           json={"client_version": "0.3", "data": {"fctl": {}}}).status_code == 200
    assert solo_client.put(f"{BASE}/{sid}/clients/freecad",
                           json={"client_version": "0.3", "internal": {"id": "x"}}).status_code == 400


# -- member-state reconciliation through the active setup ----------------------

def _entry_with_number(solo_client, machine_id, tool_number):
    """Create an entry on a machine and observe its tool_number; return its id."""
    eid = solo_client.post(ENTRY, json={"machine_id": machine_id}).json()["internal"]["id"]
    solo_client.post(f"{ENTRY}/{eid}/observe",
                     json={"path": "tool_number", "value": tool_number,
                           "client": "linuxcnc", "machine": "millstone"})
    return eid


def _active_set(solo_client, machine_id, members):
    """A set with `members`, made the machine's active setup via use-set."""
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members", json={"members": members, "actor": "freecad"})
    r = solo_client.post(MAPS, json={"machine_id": machine_id, "tool_set_id": sid})
    assert r.status_code == 200, r.text
    return sid


@pytest.mark.contract
def test_satisfied_member_keeps_claim_and_carries_observed(solo_client):
    """The §5.1 laundering fix, end to end: the claim stays asserted; the
    machine's observation rides alongside in `observed`, never over it."""
    eid = _entry_with_number(solo_client, "m-sat", 5)
    solo_client.post(f"{ENTRY}/{eid}/bind",
                     json={"instance_id": "inst-A", "actor": "human@inbox"})
    sid = _active_set(solo_client, "m-sat", [{"tool_record_id": "inst-A", "number": 5}])

    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["state"] == "satisfied"
    assert m["number"]["value"] == 5
    assert m["number"]["source"].startswith("asserted:")     # the claim, untouched
    assert m["observed"]["value"] == 5
    assert m["observed"]["source"].startswith("observed:")   # the fact, alongside


@pytest.mark.contract
def test_mismounted_member_shows_both_numbers(solo_client):
    eid = _entry_with_number(solo_client, "m-mis", 9)
    solo_client.post(f"{ENTRY}/{eid}/bind",
                     json={"instance_id": "inst-A", "actor": "human@inbox"})
    sid = _active_set(solo_client, "m-mis", [{"tool_record_id": "inst-A", "number": 14}])

    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["state"] == "mismounted"
    assert m["number"]["value"] == 14                        # CAM programmed T14
    assert m["observed"]["value"] == 9                       # machine has it at T9


@pytest.mark.contract
def test_blocked_when_claimed_number_held_by_other_tool(solo_client):
    eid = _entry_with_number(solo_client, "m-blk", 5)
    solo_client.post(f"{ENTRY}/{eid}/bind",
                     json={"instance_id": "inst-OTHER", "actor": "human@inbox"})
    sid = _active_set(solo_client, "m-blk", [{"tool_record_id": "inst-A", "number": 5}])

    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["state"] == "blocked"
    assert m["number"]["value"] == 5


@pytest.mark.contract
def test_requested_member_keeps_asserted_claim(solo_client):
    eid = _entry_with_number(solo_client, "m-req", 5)
    solo_client.post(f"{ENTRY}/{eid}/bind",
                     json={"instance_id": "inst-A", "actor": "human@inbox"})
    sid = _active_set(solo_client, "m-req",
                      [{"tool_record_id": "inst-A", "number": 5},
                       {"tool_record_id": "inst-NEW", "number": 18}])

    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    by_id = {m["tool_record_id"]: m for m in doc["canonical"]["members"]}
    assert by_id["inst-A"]["state"] == "satisfied"
    req = by_id["inst-NEW"]
    assert req["state"] == "requested"
    assert req["number"]["value"] == 18
    assert req["number"]["source"].startswith("asserted:")
    assert req["observed"] is None


@pytest.mark.contract
def test_pending_bind_via_proposal(solo_client):
    """An unbound entry the binding engine proposes for a member's instance
    reads as 'pending bind': mounted, identity unconfirmed."""
    inst = solo_client.post("/api/v1/tool-instance-records", json={}).json()["internal"]["id"]
    solo_client.post(f"/api/v1/tool-instance-records/{inst}/assert",
                     json={"path": "geometry.diameter", "value": 6.35, "unit": "mm",
                           "actor": "freecad"})
    eid = _entry_with_number(solo_client, "m-pend", 18)
    solo_client.post(f"{ENTRY}/{eid}/observe",
                     json={"path": "offsets.diameter", "value": 6.35, "unit": "mm",
                           "client": "linuxcnc", "machine": "millstone"})
    solo_client.get("/api/v1/instance-inbox")     # generates the open proposal

    sid = _active_set(solo_client, "m-pend", [{"tool_record_id": inst, "number": 18}])
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["state"] == "pending bind"
    assert m["number"]["value"] == 18
    assert m["number"]["source"].startswith("asserted:")     # claim untouched
    assert m["observed"]["value"] == 18
    assert m["observed"]["source"].startswith("observed:")


@pytest.mark.contract
def test_set_with_no_setup_has_no_member_state(solo_client):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A", "number": 3}],
                           "actor": "freecad"})
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m.get("state") is None
    assert m.get("observed") is None
    assert m["number"]["value"] == 3


# -- members: membership replaces, numbers MERGE (MAPPING_PLAN §5.1) -----------

@pytest.mark.contract
def test_members_push_without_number_preserves_stored_claim(solo_client):
    """The clobber fix: a push that omits a member's number (a client whose
    local file simply didn't carry it) keeps the stored asserted claim."""
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A", "number": 14}],
                           "actor": "freecad"})
    # Second push: same member, number omitted.
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A"}],
                           "actor": "freecad"})
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["number"]["value"] == 14                        # claim survived
    assert m["number"]["source"].startswith("asserted:")


@pytest.mark.contract
def test_members_push_with_number_reasserts(solo_client):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A", "number": 14}],
                           "actor": "freecad"})
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A", "number": 9}],
                           "actor": "human@cli"})
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["number"]["value"] == 9                         # explicit re-assert wins
    assert m["number"]["source"] == "asserted:human@cli"


@pytest.mark.contract
def test_members_new_member_without_number_is_unknown(solo_client):
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-NEW"}],
                           "actor": "freecad"})
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    (m,) = doc["canonical"]["members"]
    assert m["number"]["value"] is None
    assert m["number"]["source"] == UNKNOWN


@pytest.mark.contract
def test_membership_itself_still_replaces(solo_client):
    """CAM owns membership: a push that drops a member drops it (numbers merge,
    membership does not)."""
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A", "number": 1},
                                       {"tool_record_id": "inst-B", "number": 2}],
                           "actor": "freecad"})
    solo_client.post(f"{BASE}/{sid}/members",
                     json={"members": [{"tool_record_id": "inst-A"}],
                           "actor": "freecad"})
    doc = conforms(solo_client.get(f"{BASE}/{sid}").json())
    assert [m["tool_record_id"] for m in doc["canonical"]["members"]] == ["inst-A"]


# -- refresh is gone: reads always derive; nothing persists observations -------

@pytest.mark.contract
def test_refresh_endpoint_removed(solo_client):
    """BREAKING (0.7.0): /refresh persisted observed numbers into stored claims
    — the server-side half of the laundering the durable-claims rule forbids.
    Reads now always derive; there is nothing to refresh."""
    sid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    assert solo_client.post(f"{BASE}/{sid}/refresh", json={}).status_code in (404, 405)
