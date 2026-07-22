# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the request-aware binding bridge (ROUNDTRIP_FIXES Fix 2 /
S3, issue #39).

When `POST /tool-table-entry-records/sync` creates a NEW UNBOUND entry on a
machine that has a bound set with a `requested` member (an asserted preferred
tool_number, no entry yet), the server opens a high-confidence binding proposal
naming that member's instance, with reason "requested via set <name>". This is
the bridge that turns a freshly-mounted tool into a binding — closing the
ROUNDTRIP loop (docs/ROUNDTRIP.md steps 8-9).

When nothing ties the new entry to a request, it falls back to the existing
geometry heuristic, behaving exactly as today.
"""
import pytest

from loobric_server.contract import ToolSet

SET = "/api/v1/tool-set-records"
ENTRY = "/api/v1/tool-table-entry-records"
INSTANCE = "/api/v1/tool-instance-records"
INBOX = "/api/v1/instance-inbox"


def _sync(client, machine, entries, mode="merge", force=False):
    return client.post(f"{ENTRY}/sync", json={
        "machine_id": machine, "client": "linuxcnc", "machine_name": "millstone",
        "client_version": "0.2", "mode": mode, "force": force, "entries": entries})


def _instance(client, diameter=None):
    iid = client.post(INSTANCE, json={}).json()["internal"]["id"]
    if diameter is not None:
        client.post(f"{INSTANCE}/{iid}/assert",
                    json={"path": "geometry.diameter", "value": diameter,
                          "unit": "mm", "actor": "freecad"})
    return iid


def _bound_set(client, machine, members, name="millstone"):
    sid = client.post(SET, json={}).json()["internal"]["id"]
    client.post(f"{SET}/{sid}/assert",
                json={"path": "name", "value": name, "actor": "freecad"})
    client.post(f"{SET}/{sid}/assert",
                json={"path": "machine_id", "value": machine, "actor": "freecad"})
    client.post(f"{SET}/{sid}/members", json={"members": members, "actor": "freecad"})
    return sid


def _members(client, sid):
    """The set's members, validated against the published contract."""
    doc = client.get(f"{SET}/{sid}").json()
    ToolSet.model_validate(doc)
    return doc["canonical"]["members"]


def _proposals_for(client, instance_id):
    return [p for p in client.get(INBOX).json()["items"]
            if p["proposed_instance"]["id"] == instance_id]


@pytest.mark.contract
def test_sync_new_entry_matching_requested_number_proposes_that_instance(solo_client):
    """(a) A /sync that creates a new entry whose observed tool_number equals a
    requested member's asserted preferred number opens a high-confidence proposal
    naming that instance, with reason 'requested via set <name>'."""
    machine = "m-bridge"
    inst = _instance(solo_client, diameter=6.0)
    _bound_set(solo_client, machine, [{"tool_record_id": inst, "number": 18}])

    # The operator mounts the requested tool and assigns it pocket 18; the
    # controller pushes the new entry.
    r = _sync(solo_client, machine, [{"tool_number": 18, "offsets": {"diameter": 6.0}}])
    assert r.status_code == 200, r.text

    mine = _proposals_for(solo_client, inst)
    assert len(mine) == 1, mine
    p = mine[0]
    assert p["confidence"] > 0.5                         # elevated, above PROPOSAL_THRESHOLD
    assert p["reason"] == "requested via set millstone"
    assert p["entry"]["tool_number"] == 18


@pytest.mark.contract
def test_sync_new_entry_without_number_match_falls_back_to_geometry(solo_client):
    """(b) When no requested preferred number ties the new entry, the geometry
    heuristic still carries it (the existing diameter match), not the request
    short-circuit."""
    machine = "m-geo"
    inst = _instance(solo_client, diameter=6.35)
    # A requested member exists but prefers a DIFFERENT pocket (99) than the
    # entry the operator actually created (18) — so only geometry can tie them.
    _bound_set(solo_client, machine, [{"tool_record_id": inst, "number": 99}])

    r = _sync(solo_client, machine, [
        {"tool_number": 18, "offsets": {"diameter": 6.35, "diameter_unit": "mm"}}])
    assert r.status_code == 200, r.text

    mine = _proposals_for(solo_client, inst)
    assert len(mine) == 1, mine
    p = mine[0]
    assert "requested via set" not in p["reason"]        # geometry path, not request
    assert "diameter" in p["reason"]
    assert abs(p["confidence"] - 0.55) < 1e-6             # DIAMETER_WEIGHT


@pytest.mark.contract
def test_bind_confirms_requested_proposal_and_member_becomes_loaded(solo_client):
    """(c) End-to-end: requested -> (mount + sync) pending bind -> (bind) loaded.
    The bridge proposal confirms on bind and the member inherits the observed
    number."""
    machine = "m-loop"
    inst = _instance(solo_client, diameter=6.0)
    sid = _bound_set(solo_client, machine, [{"tool_record_id": inst, "number": 18}])

    # Before the tool is mounted the member is a pending load request.
    (m,) = _members(solo_client, sid)
    assert m["state"] == "requested"

    # Operator mounts it -> controller pushes a new (unbound) entry at pocket 18.
    r = _sync(solo_client, machine, [{"tool_number": 18, "offsets": {"diameter": 6.0}}])
    eid = r.json()["items"][0]["internal"]["id"]

    # The open proposal makes the member read as 'pending bind'.
    (m,) = _members(solo_client, sid)
    assert m["state"] == "pending bind"
    assert m["number"]["value"] == 18

    # Confirm the binding (the operator binds the entry to the requested tool).
    b = solo_client.post(f"{ENTRY}/{eid}/bind",
                         json={"instance_id": inst, "actor": "human@web"})
    assert b.status_code == 200, b.text

    # The member flips to loaded, its number now observed from the machine.
    (m,) = _members(solo_client, sid)
    assert m["state"] == "loaded"
    assert m["number"]["value"] == 18
    assert m["number"]["source"].startswith("observed:")

    # And the proposal is no longer open (it was confirmed on bind).
    assert _proposals_for(solo_client, inst) == []
