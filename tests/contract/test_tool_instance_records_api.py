# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Contract tests for the sectioned ToolInstanceRecord facade (the Slice-1 tracer).

Proves the whole pattern on the wire: responses are the three-section shape and
validate against loobric_server.contract; a client writes only its own section; routine
sync cannot touch internal/canonical; canonical moves only through observe
(machines, observable fields) and assert (deliberate). See docs/TOOL_SCHEMA.md.
"""
import pytest

from loobric_server.contract import ToolInstanceRecord, Provenance, UNKNOWN

BASE = "/api/v1/tool-instance-records"


def conforms(doc):
    """The server's own output validates against the published contract."""
    ToolInstanceRecord.model_validate(doc)
    return doc


@pytest.mark.contract
def test_create_returns_a_conformant_all_unknown_record(solo_client):
    """A freshly minted instance asserts nothing — every canonical field is
    honestly unknown, never a fabricated default."""
    r = solo_client.post(BASE, json={})
    assert r.status_code == 200, r.text
    doc = conforms(r.json())
    assert doc["internal"]["version"] == 1 and doc["internal"]["id"]
    assert doc["canonical"]["name"]["source"] == UNKNOWN
    assert doc["canonical"]["name"]["value"] is None
    assert doc["canonical"]["catalog_type_id"]["source"] == UNKNOWN
    assert doc["clients"] == {}


@pytest.mark.contract
def test_create_can_seed_an_initial_client_section(solo_client):
    r = solo_client.post(BASE, json={"client": "freecad", "client_version": "0.3.1",
                                     "client_item_id": "Probe.fctb",
                                     "data": {"fctb": {"shape": "probe.fcstd"}}})
    doc = conforms(r.json())
    sec = doc["clients"]["freecad"]
    assert sec["client_version"] == "0.3.1" and sec["client_item_id"] == "Probe.fctb"
    assert sec["created_at"] and sec["updated_at"]          # server-stamped
    assert "client" not in sec                               # identity is the map key
    assert sec["data"]["fctb"]["shape"] == "probe.fcstd"


@pytest.mark.contract
def test_sync_writes_only_the_client_section(solo_client):
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    r = solo_client.put(f"{BASE}/{rid}/clients/freecad",
                        json={"client_version": "0.3.1", "client_item_id": "Probe.fctb",
                              "data": {"any": [1, 2]}})
    assert r.status_code == 200, r.text
    doc = conforms(r.json())
    assert doc["clients"]["freecad"]["data"] == {"any": [1, 2]}
    assert doc["internal"]["version"] == 2                   # bumped


@pytest.mark.contract
@pytest.mark.parametrize("forbidden", ["internal", "canonical", "client"])
def test_sync_cannot_touch_internal_or_canonical(solo_client, forbidden):
    """The load-bearing safety property, enforced at the API: a sync write that
    reaches for internal/canonical (or re-sends the redundant `client` key) is a
    loud 400, not a silent strip."""
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    body = {"client_version": "0.3.1", "data": {}}
    body[forbidden] = "x" if forbidden == "client" else {"shape": "endmill"}
    r = solo_client.put(f"{BASE}/{rid}/clients/freecad", json=body)
    assert r.status_code == 400, r.text


@pytest.mark.contract
def test_assert_sets_a_canonical_field_with_asserted_provenance(solo_client):
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    # the deliberate type correction (the heal-on-import, generalized)
    r = solo_client.post(f"{BASE}/{rid}/assert",
                         json={"path": "geometry.shape", "value": "probe", "actor": "freecad"})
    doc = conforms(r.json())
    shape = doc["canonical"]["geometry"]["shape"]
    assert shape["value"] == "probe" and shape["source"] == "asserted:freecad"


@pytest.mark.contract
def test_observe_sets_a_measured_field_from_a_machine(solo_client):
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/observe",
                         json={"path": "geometry.diameter", "value": 2.9972, "unit": "mm",
                               "client": "linuxcnc", "machine": "millstone"})
    doc = conforms(r.json())
    dia = doc["canonical"]["geometry"]["diameter"]
    assert dia["value"] == 2.9972 and dia["source"] == "observed:linuxcnc@millstone"


@pytest.mark.contract
def test_a_machine_cannot_observe_shape(solo_client):
    """Scope discipline: shape is not measurable — a machine may not observe it;
    it must be asserted. This is the endmill-pollution bug made impossible."""
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/observe",
                         json={"path": "geometry.shape", "value": "endmill",
                               "client": "linuxcnc", "machine": "millstone"})
    assert r.status_code == 400, r.text


@pytest.mark.contract
def test_assert_catalog_link_and_round_trip(solo_client):
    rid = solo_client.post(BASE, json={}).json()["internal"]["id"]
    solo_client.post(f"{BASE}/{rid}/assert",
                     json={"path": "catalog_type_id", "value": "cat-77f1", "actor": "human@inbox"})
    doc = conforms(solo_client.get(f"{BASE}/{rid}").json())
    link = doc["canonical"]["catalog_type_id"]
    assert link["value"] == "cat-77f1" and link["source"] == "asserted:human@inbox"
