# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Server-driven integration test for the ROUNDTRIP loop (docs/ROUNDTRIP.md
steps 5-10, reworked for setups per MAPPING_PLAN.md).

This drives the *real* API endpoints the clients use (entry `/sync`, `/bind`,
set create/assert/members, `use-set`, set GET, the reconciliation view) and
proves the loop closes:

    machine + active setup in sync at 17            (ready)
      -> programmer claims a new tool at T18        (member `requested`; NOT ready)
      -> operator mounts it + controller sync        (new unbound entry; member
                                                      `pending bind`, elevated
                                                      proposal names its instance)
      -> bind confirms                               (member `satisfied`; ready)
      -> every view converges on 18.

Throughout, the member's claimed number stays ASSERTED — observation rides in
`observed` and never overwrites the claim (the §5.1 durable-claims rule).
"""
import pytest

from loobric_server.contract import ToolSet

SET = "/api/v1/tool-set-records"
ENTRY = "/api/v1/tool-table-entry-records"
INSTANCE = "/api/v1/tool-instance-records"
INBOX = "/api/v1/instance-inbox"
MAPS = "/api/v1/machine-set-maps"

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


def _recon(client):
    return client.get(f"{MAPS}/status?machine_id={MACHINE}").json()


def _seed_17_in_sync(client):
    """ROUNDTRIP steps 1-3 condensed: controller's first sync creates 17 observed
    entries, the operator binds each to its physical tool. Returns the 17 instance
    ids (T1..T17), in pocket order."""
    r = _sync(client, [{"tool_number": n,
                        "offsets": {"diameter": float(n), "diameter_unit": "mm"}}
                       for n in range(1, 18)], mode="snapshot")
    assert r.status_code == 200, r.text
    instances = []
    for n in range(1, 18):
        eid = _entry_id_for_number(client, n)
        iid = f"inst-{n}"
        b = client.post(f"{ENTRY}/{eid}/bind",
                        json={"instance_id": iid, "actor": "human@web"})
        assert b.status_code == 200, b.text
        instances.append(iid)
    return instances


def _create_active_set(client, instances):
    """ROUNDTRIP step 3: create set `millstone` with one member per bound entry
    (claims match the pockets), then `use-set` it onto the machine."""
    sid = client.post(SET, json={}).json()["internal"]["id"]
    client.post(f"{SET}/{sid}/assert",
                json={"path": "name", "value": SET_NAME, "actor": "freecad"})
    client.post(f"{SET}/{sid}/members",
                json={"members": [{"tool_record_id": iid, "number": n + 1}
                                  for n, iid in enumerate(instances)],
                      "actor": "freecad"})
    r = client.post(MAPS, json={"machine_id": MACHINE, "tool_set_id": sid})
    assert r.status_code == 200, r.text
    return sid


@pytest.mark.integration
def test_roundtrip_loop_closes_at_18(solo_client):
    client = solo_client

    # === Setup: machine + active setup, in sync at 17 (ROUNDTRIP steps 1-4) ===
    instances = _seed_17_in_sync(client)
    sid = _create_active_set(client, instances)

    members = _set_doc(client, sid)["canonical"]["members"]
    assert len(members) == 17
    assert all(m["state"] == "satisfied" for m in members)
    assert len(_machine_entries(client)) == 17
    recon = _recon(client)
    assert recon["ready"] is True
    assert recon["attention"] == {"important": 0, "notes": 0}

    # === Step 5: programmer claims a tool the machine doesn't have yet ========
    # FreeCAD creates the toolbit (an instance) and asserts it into the set with
    # claimed number 18. The machine has no entry for it -> `requested`.
    new = client.post(INSTANCE, json={}).json()["internal"]["id"]
    client.post(f"{INSTANCE}/{new}/assert",
                json={"path": "geometry.diameter", "value": 6.0, "unit": "mm",
                      "actor": "freecad"})
    client.post(f"{SET}/{sid}/members", json={
        "members": [{"tool_record_id": iid} for iid in instances]
                   + [{"tool_record_id": new, "number": 18}],
        "actor": "freecad"})

    # --- 18 members / 17 entries is a valid, tracked state --------------------
    members = _set_doc(client, sid)["canonical"]["members"]
    by_state = _by_state(members)
    assert len(members) == 18
    assert len(by_state.get("satisfied", [])) == 17     # numbers merged, not lost
    assert len(by_state.get("requested", [])) == 1
    assert set(by_state) == {"satisfied", "requested"}
    assert len(_machine_entries(client)) == 17

    # The §5.1 rule held through the members re-push: the 17 omitted numbers
    # kept their stored asserted claims (nothing flipped to unknown).
    for m in by_state["satisfied"]:
        assert m["number"]["value"] is not None
        assert m["number"]["source"].startswith("asserted:")

    req = by_state["requested"][0]
    assert req["tool_record_id"] == new
    assert req["number"]["value"] == 18
    assert req["number"]["source"].startswith("asserted:")

    # --- The view: an unmet claim is important; the machine is NOT ready ------
    recon = _recon(client)
    assert recon["ready"] is False
    assert recon["attention"] == {"important": 1, "notes": 0}
    (claim,) = [c for c in recon["claims"] if c["state"] == "requested"]
    assert claim["tool_record_id"] == new

    # === Step 8: operator mounts the tool at pocket 18, controller syncs ======
    # A merge push creates a new UNBOUND entry; the request-aware bridge opens
    # a high-confidence proposal naming the claimed instance.
    r = _sync(client, [{"tool_number": 18,
                        "offsets": {"diameter": 6.0, "diameter_unit": "mm"}}],
              mode="merge")
    assert r.status_code == 200, r.text
    assert len(_machine_entries(client)) == 18

    # --- member reads `pending bind`; claim untouched, observation alongside --
    members = _set_doc(client, sid)["canonical"]["members"]
    member_new = {m["tool_record_id"]: m for m in members}[new]
    assert member_new["state"] == "pending bind"
    assert member_new["number"]["value"] == 18
    assert member_new["number"]["source"].startswith("asserted:")   # the claim
    assert member_new["observed"]["value"] == 18
    assert member_new["observed"]["source"].startswith("observed:")  # the fact
    proposals = _proposals_for(client, new)
    assert len(proposals) == 1, proposals
    assert proposals[0]["reason"] == f"requested via set {SET_NAME}"
    assert proposals[0]["entry"]["tool_number"] == 18
    # Identity unconfirmed is still an unmet claim: NOT ready.
    assert _recon(client)["ready"] is False

    # === Step 9: confirm the binding ==========================================
    eid18 = _entry_id_for_number(client, 18)
    b = client.post(f"{ENTRY}/{eid18}/bind",
                    json={"instance_id": new, "actor": "human@web"})
    assert b.status_code == 200, b.text

    # --- satisfied, both numbers agree, every view converges on 18 ------------
    members = _set_doc(client, sid)["canonical"]["members"]
    assert len(members) == 18
    assert all(m["state"] == "satisfied" for m in members)
    sat_new = {m["tool_record_id"]: m for m in members}[new]
    assert sat_new["number"]["value"] == 18
    assert sat_new["number"]["source"].startswith("asserted:")      # never laundered
    assert sat_new["observed"]["value"] == 18
    assert MACHINE in sat_new["observed"]["source"]
    # The proposal was confirmed on bind, not left dangling.
    assert _proposals_for(client, new) == []
    # Steps 9/10: every view converges on 18; the machine is ready.
    assert len(_machine_entries(client)) == 18
    recon = _recon(client)
    assert recon["ready"] is True
    assert recon["attention"] == {"important": 0, "notes": 0}
