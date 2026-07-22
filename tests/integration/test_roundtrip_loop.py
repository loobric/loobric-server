# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Server-driven integration test for the ROUNDTRIP loop (docs/ROUNDTRIP.md
steps 5-10, the acceptance test in docs/Archive/ROUNDTRIP_FIXES.md "Fix 2").

This drives the *real* API endpoints the clients use (entry `/sync`, `/bind`,
set create/assert/members, `/refresh`, set GET) and proves the loop closes:

    machine + bound set in sync at 17
      -> programmer adds a tool          (member reads `requested`, still in sync)
      -> operator mounts it + sync        (new unbound entry; member `pending bind`,
                                           a binding proposal names its instance)
      -> bind confirms                    (member `loaded`, number observed)
      -> every view converges on 18.

It exercises the #37 (reconcile/state) + #38 (refresh-is-a-merge) + #39
(request-aware binding bridge) slices together as one narrative.
"""
import pytest

from loobric_server.contract import ToolSet

SET = "/api/v1/tool-set-records"
ENTRY = "/api/v1/tool-table-entry-records"
INSTANCE = "/api/v1/tool-instance-records"
INBOX = "/api/v1/instance-inbox"

MACHINE = "millstone"        # machine_id and machine_name (observed:linuxcnc@millstone)
SET_NAME = "millstone"


# -- helpers: the moves a real client would make through the real endpoints ----

def _sync(client, entries, mode="merge"):
    """The controller push (loobric-linuxcnc)."""
    return client.post(f"{ENTRY}/sync", json={
        "machine_id": MACHINE, "client": "linuxcnc", "machine_name": MACHINE,
        "client_version": "0.2", "mode": mode, "force": False, "entries": entries})


def _machine_entries(client):
    return [e for e in client.get(ENTRY).json()["items"]
            if e["internal"]["machine_id"] == MACHINE]


def _entry_id_for_number(client, number):
    return next(e["internal"]["id"] for e in _machine_entries(client)
                if e["canonical"]["tool_number"]["value"] == number)


def _set_doc(client, sid):
    """GET the set, validated against the published contract."""
    doc = client.get(f"{SET}/{sid}").json()
    ToolSet.model_validate(doc)
    return doc


def _by_state(members):
    out = {}
    for m in members:
        out.setdefault(m["state"], []).append(m)
    return out


def _proposals_for(client, instance_id):
    return [p for p in client.get(INBOX).json()["items"]
            if p["proposed_instance"]["id"] == instance_id]


def _seed_17_in_sync(client):
    """ROUNDTRIP steps 1-3 condensed: controller's first sync creates 17 observed
    entries, the operator binds each to its physical tool. Returns the 17 instance
    ids (T1..T17), in pocket order."""
    # Step 1: loobric-linuxcnc first sync -> 17 observed entries (snapshot).
    r = _sync(client, [{"tool_number": n,
                        "offsets": {"diameter": float(n), "diameter_unit": "mm"}}
                       for n in range(1, 18)], mode="snapshot")
    assert r.status_code == 200, r.text
    # Step 2: operator binds each pocket to its physical instance.
    instances = []
    for n in range(1, 18):
        eid = _entry_id_for_number(client, n)
        iid = f"inst-{n}"
        b = client.post(f"{ENTRY}/{eid}/bind",
                        json={"instance_id": iid, "actor": "human@web"})
        assert b.status_code == 200, b.text
        instances.append(iid)
    return instances


def _create_bound_set(client, instances):
    """ROUNDTRIP step 3: create set `millstone`, bind it to the machine, give it
    one member per bound entry."""
    sid = client.post(SET, json={}).json()["internal"]["id"]
    client.post(f"{SET}/{sid}/assert",
                json={"path": "name", "value": SET_NAME, "actor": "freecad"})
    client.post(f"{SET}/{sid}/assert",
                json={"path": "machine_id", "value": MACHINE, "actor": "freecad"})
    client.post(f"{SET}/{sid}/members",
                json={"members": [{"tool_record_id": iid} for iid in instances],
                      "actor": "freecad"})
    return sid


@pytest.mark.integration
def test_roundtrip_loop_closes_at_18(solo_client):
    client = solo_client

    # === Setup: machine + bound set, in sync at 17 (ROUNDTRIP steps 1-4) ======
    instances = _seed_17_in_sync(client)
    sid = _create_bound_set(client, instances)

    members = _set_doc(client, sid)["canonical"]["members"]
    assert len(members) == 17
    assert all(m["state"] == "loaded" for m in members)
    assert len(_machine_entries(client)) == 17

    # === Step 5: programmer adds a tool the machine doesn't have yet ==========
    # FreeCAD creates the toolbit (an instance) and asserts it into the set with a
    # preferred pocket (18). The machine has no entry for it -> `requested`.
    new = client.post(INSTANCE, json={}).json()["internal"]["id"]
    client.post(f"{INSTANCE}/{new}/assert",
                json={"path": "geometry.diameter", "value": 6.0, "unit": "mm",
                      "actor": "freecad"})
    client.post(f"{SET}/{sid}/members", json={
        "members": [{"tool_record_id": iid} for iid in instances]
                   + [{"tool_record_id": new, "number": 18}],
        "actor": "freecad"})

    # --- Assertion 1: 18 members / 17 entries reads as in-sync ---------------
    members = _set_doc(client, sid)["canonical"]["members"]
    by_state = _by_state(members)
    assert len(members) == 18
    assert len(by_state.get("loaded", [])) == 17
    assert len(by_state.get("requested", [])) == 1          # exactly one request
    assert set(by_state) == {"loaded", "requested"}         # no conflict/other state
    # The count delta is fully accounted for by the one request:
    assert len(_machine_entries(client)) == 17
    assert len(members) - len(_machine_entries(client)) == len(by_state["requested"])

    # --- Assertion 5 (requested half): preferred number is an asserted pref ---
    req = by_state["requested"][0]
    assert req["tool_record_id"] == new
    assert req["number"]["value"] == 18
    assert req["number"]["source"].startswith("asserted:")

    # === Step 6: refresh-from-machine must NOT drop the request (the refusal) =
    # --- Assertion 4 -----------------------------------------------------------
    body = client.post(f"{SET}/{sid}/refresh", json={"actor": "human@web"}).json()
    ToolSet.model_validate(body["set"])
    assert body["ambiguities"] == []                        # no conflict surfaced
    refreshed = {m["tool_record_id"]: m for m in body["set"]["canonical"]["members"]}
    assert len(refreshed) == 18                             # nothing deleted
    assert refreshed[new]["state"] == "requested"
    assert refreshed[new]["number"]["value"] == 18
    assert refreshed[new]["number"]["source"].startswith("asserted:")
    # And it persisted: a fresh GET still has all 18, still 1 requested.
    after = _by_state(_set_doc(client, sid)["canonical"]["members"])
    assert len(after.get("loaded", [])) == 17
    assert len(after.get("requested", [])) == 1

    # === Step 8: operator mounts the tool at pocket 18, controller syncs ======
    # A merge push creates a new UNBOUND entry; the request-aware bridge (#39)
    # opens a high-confidence proposal naming the requested instance.
    r = _sync(client, [{"tool_number": 18,
                        "offsets": {"diameter": 6.0, "diameter_unit": "mm"}}],
              mode="merge")
    assert r.status_code == 200, r.text
    assert len(_machine_entries(client)) == 18

    # --- Assertion 2: member reads `pending bind`; the proposal exists --------
    members = _set_doc(client, sid)["canonical"]["members"]
    member_new = {m["tool_record_id"]: m for m in members}[new]
    assert member_new["state"] == "pending bind"
    assert member_new["number"]["value"] == 18
    assert member_new["number"]["source"].startswith("observed:")   # from the entry
    proposals = _proposals_for(client, new)
    assert len(proposals) == 1, proposals
    assert proposals[0]["reason"] == f"requested via set {SET_NAME}"
    assert proposals[0]["entry"]["tool_number"] == 18

    # === Step 9: confirm the binding ==========================================
    eid18 = _entry_id_for_number(client, 18)
    b = client.post(f"{ENTRY}/{eid18}/bind",
                    json={"instance_id": new, "actor": "human@web"})
    assert b.status_code == 200, b.text

    # --- Assertion 3 + 5 (loaded half): loaded, observed number, all converge -
    members = _set_doc(client, sid)["canonical"]["members"]
    assert len(members) == 18
    assert all(m["state"] == "loaded" for m in members)     # 18 loaded, in sync
    loaded_new = {m["tool_record_id"]: m for m in members}[new]
    assert loaded_new["number"]["value"] == 18              # number is observed (18)
    assert loaded_new["number"]["source"].startswith("observed:")
    assert MACHINE in loaded_new["number"]["source"]        # observed:<machine>
    # The proposal was confirmed on bind, not left dangling.
    assert _proposals_for(client, new) == []
    # Step 9/10: every view converges on 18.
    assert len(_machine_entries(client)) == 18
    assert len(_set_doc(client, sid)["canonical"]["members"]) == 18
