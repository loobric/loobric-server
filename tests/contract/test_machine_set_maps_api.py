# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for setups (machine_set_maps, MAPPING_PLAN.md).

The transitory machine↔set relationship: `use-set` activates, atomically
ending the machine's prior setup (history, never deletion); activation
changes nothing on either side; the reconciliation view derives `ready`,
claims, and notes at read time and stores nothing. Lifecycle rides the
`bind` door; agent keys (read sync assert) can never switch setups.
"""
import pytest

BASE = "/api/v1/machine-set-maps"
SET = "/api/v1/tool-set-records"
ENTRY = "/api/v1/tool-table-entry-records"
INSTANCE = "/api/v1/tool-instance-records"


def _set_with_members(client, members, name=None):
    sid = client.post(SET, json={}).json()["internal"]["id"]
    if name:
        client.post(f"{SET}/{sid}/assert",
                    json={"path": "name", "value": name, "actor": "freecad"})
    if members:
        client.post(f"{SET}/{sid}/members",
                    json={"members": members, "actor": "freecad"})
    return sid


def _entry(client, machine_id, tool_number, bind_to=None, diameter=None):
    eid = client.post(ENTRY, json={"machine_id": machine_id}).json()["internal"]["id"]
    client.post(f"{ENTRY}/{eid}/observe",
                json={"path": "tool_number", "value": tool_number,
                      "client": "linuxcnc", "machine": "millstone"})
    if diameter is not None:
        client.post(f"{ENTRY}/{eid}/observe",
                    json={"path": "offsets.diameter", "value": diameter,
                          "unit": "mm", "client": "linuxcnc", "machine": "millstone"})
    if bind_to:
        r = client.post(f"{ENTRY}/{eid}/bind",
                        json={"instance_id": bind_to, "actor": "human@inbox"})
        assert r.status_code == 200, r.text
    return eid


def _named_instance(client, name):
    iid = client.post(INSTANCE, json={}).json()["internal"]["id"]
    client.post(f"{INSTANCE}/{iid}/assert",
                json={"path": "name", "value": name, "actor": "freecad"})
    return iid


# -- lifecycle -----------------------------------------------------------------

@pytest.mark.contract
def test_use_set_creates_active_setup(solo_client):
    sid = _set_with_members(solo_client, [], name="bracket-job")
    r = solo_client.post(BASE, json={"machine_id": "m-life", "tool_set_id": sid})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "active"
    assert doc["machine_id"] == "m-life"
    assert doc["tool_set_id"] == sid
    assert doc["activated_at"]
    assert doc["ended_at"] is None


@pytest.mark.contract
def test_use_set_unknown_set_404(solo_client):
    r = solo_client.post(BASE, json={"machine_id": "m-x", "tool_set_id": "nope"})
    assert r.status_code == 404


@pytest.mark.contract
def test_switching_sets_ends_prior_and_keeps_history(solo_client):
    """The crib shop: activating the next job's list ends the previous setup.
    Nothing is deleted — the ended row is the machine's setup history."""
    a = _set_with_members(solo_client, [], name="job-a")
    b = _set_with_members(solo_client, [], name="job-b")
    first = solo_client.post(BASE, json={"machine_id": "m-swap", "tool_set_id": a}).json()
    second = solo_client.post(BASE, json={"machine_id": "m-swap", "tool_set_id": b}).json()
    assert second["status"] == "active"

    items = solo_client.get(f"{BASE}?machine_id=m-swap").json()["items"]
    by_id = {i["id"]: i for i in items}
    assert len(items) == 2
    assert by_id[first["id"]]["status"] == "ended"
    assert by_id[first["id"]]["ended_at"]
    assert by_id[second["id"]]["status"] == "active"
    # Exactly one active per machine:
    active = [i for i in items if i["status"] == "active"]
    assert len(active) == 1


@pytest.mark.contract
def test_reactivating_active_set_is_a_noop(solo_client):
    sid = _set_with_members(solo_client, [], name="same")
    first = solo_client.post(BASE, json={"machine_id": "m-noop", "tool_set_id": sid}).json()
    again = solo_client.post(BASE, json={"machine_id": "m-noop", "tool_set_id": sid}).json()
    assert again["id"] == first["id"]
    assert len(solo_client.get(f"{BASE}?machine_id=m-noop").json()["items"]) == 1


@pytest.mark.contract
def test_end_without_replacement_and_idempotent(solo_client):
    sid = _set_with_members(solo_client, [], name="solo-job")
    row = solo_client.post(BASE, json={"machine_id": "m-end", "tool_set_id": sid}).json()
    r = solo_client.post(f"{BASE}/{row['id']}/end")
    assert r.status_code == 200
    assert r.json()["status"] == "ended"
    # Idempotent:
    assert solo_client.post(f"{BASE}/{row['id']}/end").json()["status"] == "ended"
    # And the machine now has no active setup:
    active = solo_client.get(f"{BASE}?machine_id=m-end&status=active").json()["items"]
    assert active == []


# -- activation mutates neither side (invariant 7) -----------------------------

@pytest.mark.contract
def test_use_set_changes_no_entries_bindings_or_members(solo_client):
    inst = _named_instance(solo_client, "6mm endmill")
    eid = _entry(solo_client, "m-inert", 3, bind_to=inst)
    sid = _set_with_members(solo_client,
                            [{"tool_record_id": inst, "number": 3}], name="inert")
    entry_before = solo_client.get(f"{ENTRY}/{eid}").json()

    solo_client.post(BASE, json={"machine_id": "m-inert", "tool_set_id": sid})
    other = _set_with_members(solo_client, [], name="other")
    solo_client.post(BASE, json={"machine_id": "m-inert", "tool_set_id": other})

    entry_after = solo_client.get(f"{ENTRY}/{eid}").json()
    assert entry_after["canonical"] == entry_before["canonical"]   # binding + number intact
    stored = solo_client.get(f"{SET}/{sid}").json()["canonical"]["members"]
    assert stored[0]["number"]["value"] == 3                        # claim intact


# -- the CAM-first proposal bridge on activation -------------------------------

@pytest.mark.contract
def test_activation_bridges_claims_against_existing_unbound_entries(solo_client):
    """Slice 0b via use-set: the entry exists BEFORE the setup. Activation
    opens the elevated-confidence proposal immediately — no waiting for the
    machine's next push."""
    inst = _named_instance(solo_client, "3mm drill")
    _entry(solo_client, "m-bridge", 12)                  # unbound, mounted long ago
    sid = _set_with_members(solo_client,
                            [{"tool_record_id": inst, "number": 12}], name="bridge")

    solo_client.post(BASE, json={"machine_id": "m-bridge", "tool_set_id": sid})

    inbox = solo_client.get("/api/v1/instance-inbox").json()["items"]
    mine = [p for p in inbox if p["proposed_instance"]["id"] == inst]
    assert len(mine) == 1
    assert mine[0]["confidence"] >= 0.95
    assert "bridge" in mine[0]["reason"]


# -- the reconciliation view (MAPPING_PLAN §5.4) -------------------------------

@pytest.mark.contract
def test_reconciliation_with_no_active_setup(solo_client):
    doc = solo_client.get(f"{BASE}/status?machine_id=m-none").json()
    assert doc["active"] is False
    assert doc["ready"] is None
    assert doc["claims"] == [] and doc["notes"] == []


@pytest.mark.contract
def test_reconciliation_worked_example(solo_client):
    """MAPPING_PLAN §12 condensed: 1 satisfied, 1 blocked, 2 requested claims;
    an unlisted probe and an unidentified pocket as notes. Not ready; the
    blocker also honestly appears as a note (it IS mounted and unlisted)."""
    machine = "m-worked"
    em6 = _named_instance(solo_client, "6mm endmill")
    face = _named_instance(solo_client, "50mm face mill")
    drill = _named_instance(solo_client, "3mm drill")
    cham = _named_instance(solo_client, "90deg chamfer")
    slot = _named_instance(solo_client, "20mm slot mill")
    probe = _named_instance(solo_client, "touch probe")

    _entry(solo_client, machine, 3, bind_to=em6)          # stays mounted
    _entry(solo_client, machine, 5, bind_to=slot)         # last job's leftover
    _entry(solo_client, machine, 30, bind_to=probe)       # permanent resident
    _entry(solo_client, machine, 8)                       # unbound mystery

    sid = _set_with_members(solo_client, [
        {"tool_record_id": em6, "number": 3},
        {"tool_record_id": face, "number": 5},
        {"tool_record_id": drill, "number": 12},
        {"tool_record_id": cham, "number": 14},
    ], name="bracket-job")
    solo_client.post(BASE, json={"machine_id": machine, "tool_set_id": sid})

    doc = solo_client.get(f"{BASE}/status?machine_id={machine}").json()
    assert doc["active"] is True
    assert doc["tool_set_name"] == "bracket-job"
    assert doc["ready"] is False

    claims = {c["tool_record_id"]: c for c in doc["claims"]}
    assert claims[em6]["state"] == "satisfied"
    blocked = claims[face]
    assert blocked["state"] == "blocked"
    assert blocked["blocked_by"]["tool_record_id"] == slot
    assert blocked["blocked_by"]["name"] == "20mm slot mill"
    assert claims[drill]["state"] == "requested"
    assert claims[cham]["state"] == "requested"

    notes = {(n["state"], n["number"]["value"]) for n in doc["notes"]}
    assert ("unlisted", 5) in notes                       # the blocker, honestly
    assert ("unlisted", 30) in notes                      # the probe
    assert ("unknown tool", 8) in notes                   # the mystery pocket
    assert doc["attention"] == {"important": 3, "notes": 3}


@pytest.mark.contract
def test_reconciliation_ready_when_all_claims_satisfied(solo_client):
    machine = "m-ready"
    em6 = _named_instance(solo_client, "6mm endmill")
    probe = _named_instance(solo_client, "touch probe")
    _entry(solo_client, machine, 3, bind_to=em6)
    _entry(solo_client, machine, 30, bind_to=probe)       # unlisted forever — a note

    sid = _set_with_members(solo_client,
                            [{"tool_record_id": em6, "number": 3}], name="one-tool")
    solo_client.post(BASE, json={"machine_id": machine, "tool_set_id": sid})

    doc = solo_client.get(f"{BASE}/status?machine_id={machine}").json()
    assert doc["ready"] is True                           # notes never block readiness
    assert doc["attention"] == {"important": 0, "notes": 1}


# -- doors: lifecycle is bind; agent and controller sync keys are locked out ---

def _register_and_login(client, email):
    client.post("/api/v1/auth/register", json={"email": email, "password": "p" * 12})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "p" * 12})
    assert r.status_code == 200, r.text
    return client


def _key(client, scopes, name="k"):
    r = client.post("/api/v1/auth/keys", json={"name": name, "scopes": scopes})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["key"]}


@pytest.mark.contract
def test_agent_and_observe_keys_cannot_switch_setups(client):
    """MAPPING_PLAN §10 Q3: the canonical agent key (read sync assert) and the
    bare controller key (read sync observe) both lack `bind` — neither can
    change which setup a machine runs. The 403 names the missing scope."""
    _register_and_login(client, "maps-doors@test.io")
    sid = client.post(SET, json={}).json()["internal"]["id"]
    agent = _key(client, ["read", "sync", "assert"], "agent")
    controller = _key(client, ["read", "sync", "observe"], "cnc")
    operator = _key(client, ["read", "sync", "observe", "bind"], "panel")
    client.cookies.clear()

    body = {"machine_id": "m-doors", "tool_set_id": sid}
    r = client.post(BASE, json=body, headers=agent)
    assert r.status_code == 403 and "bind" in r.json()["detail"]
    r = client.post(BASE, json=body, headers=controller)
    assert r.status_code == 403 and "bind" in r.json()["detail"]
    # An operator-station key that includes bind CAN switch setups...
    r = client.post(BASE, json=body, headers=operator)
    assert r.status_code == 200, r.text
    row_id = r.json()["id"]
    # ...and its key id is recorded on the row.
    assert r.json()["activated_key"] is not None
    # Reads are read-door: the agent key can still SEE the view.
    r = client.get(f"{BASE}/status?machine_id=m-doors", headers=agent)
    assert r.status_code == 200
    # end is bind too:
    r = client.post(f"{BASE}/{row_id}/end", headers=agent)
    assert r.status_code == 403
    r = client.post(f"{BASE}/{row_id}/end", headers=operator)
    assert r.status_code == 200
