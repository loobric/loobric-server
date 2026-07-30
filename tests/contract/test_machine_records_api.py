# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Contract tests for the sectioned Machine facade (docs/TOOL_SCHEMA.md §7.5).

Proves the same pattern as the ToolInstanceRecord tracer on the wire: responses
are the three-section shape and validate against loobric_server.contract; a client
writes only its own section; routine sync cannot touch internal/canonical;
canonical moves only through assert. A machine has NO observe door — its identity
is declared, never measured.
"""
import pytest

from loobric_server.contract import Machine, Provenance, UNKNOWN

BASE = "/api/v1/machine-records"


def conforms(doc):
    """The server's own output validates against the published contract."""
    Machine.model_validate(doc)
    return doc


@pytest.mark.contract
def test_create_returns_a_conformant_all_unknown_record(solo_client):
    """A freshly minted machine asserts nothing — its name is honestly unknown,
    never a fabricated default."""
    r = solo_client.post(BASE, json={})
    assert r.status_code == 200, r.text
    doc = conforms(r.json())
    assert doc["internal"]["version"] == 1 and doc["internal"]["id"]
    assert doc["canonical"]["name"]["source"] == UNKNOWN
    assert doc["canonical"]["name"]["value"] is None
    assert doc["clients"] == {}


@pytest.mark.contract
def test_create_can_seed_an_initial_client_section(solo_client):
    r = solo_client.post(BASE, json={"client": "linuxcnc", "client_version": "2.9",
                                     "client_item_id": "millstone.ini",
                                     "data": {"ini": {"axes": "XYZ"}}})
    doc = conforms(r.json())
    sec = doc["clients"]["linuxcnc"]
    assert sec["client_version"] == "2.9" and sec["client_item_id"] == "millstone.ini"
    assert sec["created_at"] and sec["updated_at"]          # server-stamped
    assert "client" not in sec                               # identity is the map key
    assert sec["data"]["ini"]["axes"] == "XYZ"


@pytest.mark.contract
def test_sync_writes_only_the_client_section(solo_client):
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    r = solo_client.put(f"{BASE}/{rid}/clients/linuxcnc",
                        json={"client_version": "2.9", "client_item_id": "millstone.ini",
                              "data": {"any": [1, 2]}})
    assert r.status_code == 200, r.text
    doc = conforms(r.json())
    assert doc["clients"]["linuxcnc"]["data"] == {"any": [1, 2]}
    assert doc["internal"]["version"] == 2                   # bumped


@pytest.mark.contract
@pytest.mark.parametrize("forbidden", ["internal", "canonical", "client"])
def test_sync_cannot_touch_internal_or_canonical(solo_client, forbidden):
    """The load-bearing safety property, enforced at the API: a sync write that
    reaches for internal/canonical (or re-sends the redundant `client` key) is a
    loud 400, not a silent strip."""
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    body = {"client_version": "2.9", "data": {}}
    body[forbidden] = "x" if forbidden == "client" else {"name": "millstone"}
    r = solo_client.put(f"{BASE}/{rid}/clients/linuxcnc", json=body)
    assert r.status_code == 400, r.text


@pytest.mark.contract
def test_assert_sets_spindle_and_coolant_capability_fields(solo_client):
    """Spindle/coolant capability is canonical on the Machine — the answer to
    'what RPM can this machine turn?' lives here, not in tool-list archaeology.
    Dotted paths land as provenance-tagged leaves and survive a GET."""
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    for path, value, unit in (
        ("spindle.max_rpm", 24000, "rpm"),
        ("spindle.min_rpm", 100, "rpm"),
        ("spindle.power", 2.2, "kW"),
        ("spindle.taper", "R8", None),
        ("coolant.flood", True, None),
        ("coolant.mist", False, None),
        ("coolant.through_spindle", False, None),
    ):
        body = {"path": path, "value": value, "actor": "human@inbox"}
        if unit:
            body["unit"] = unit
        r = solo_client.post(f"{BASE}/{rid}/assert", json=body)
        assert r.status_code == 200, r.text
    doc = conforms(solo_client.get(f"{BASE}/{rid}").json())
    spindle = doc["canonical"]["spindle"]
    assert spindle["max_rpm"] == {"value": 24000, "unit": "rpm",
                                  "source": "asserted:human@inbox"}
    assert spindle["taper"]["value"] == "R8"
    coolant = doc["canonical"]["coolant"]
    assert coolant["flood"]["value"] is True
    assert coolant["through_spindle"]["value"] is False


@pytest.mark.contract
def test_assert_rejects_an_unratified_capability_path(solo_client):
    """The capability vocabulary is deliberate: an assert to a spindle field the
    schema doesn't know is a loud 400, not a silently accreted key."""
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/assert",
                         json={"path": "spindle.horsepower", "value": 3,
                               "actor": "human@inbox"})
    assert r.status_code == 400, r.text


@pytest.mark.contract
def test_assert_sets_name_and_controller_type_and_round_trips(solo_client):
    """A machine's identity is asserted (declared), never observed. Name and
    controller_type land with asserted:<actor> provenance and survive a GET."""
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{rid}/assert",
                     json={"path": "name", "value": "millstone", "actor": "human@inbox"})
    solo_client.post(f"{BASE}/{rid}/assert",
                     json={"path": "controller_type", "value": "linuxcnc", "actor": "linuxcnc"})
    doc = conforms(solo_client.get(f"{BASE}/{rid}").json())
    name = doc["canonical"]["name"]
    assert name["value"] == "millstone" and name["source"] == "asserted:human@inbox"
    ctrl = doc["canonical"]["controller_type"]
    assert ctrl["value"] == "linuxcnc" and ctrl["source"] == "asserted:linuxcnc"
