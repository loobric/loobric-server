# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for cutting data presets (docs/PRESETS.md).

Canonical `presets` is a DERIVED union of source-preserved contributions:
the contribution door is the only way in, replace-own is per (origin,
label), the union never reconciles, and an instance's listing includes its
linked catalog's entries scope-marked."""
import pytest

BASE = "/api/v1"


def _instance(solo_client, name="Preset Mill"):
    r = solo_client.post(f"{BASE}/tool-instance-records", json={})
    assert r.status_code == 200, r.text
    rid = r.json()["internal"]["id"]
    solo_client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                     json={"path": "name", "value": name,
                           "actor": "human@test"})
    return rid


def _catalog(solo_client, code="P100"):
    r = solo_client.post(f"{BASE}/tool-catalog-records", json={
        "actor": "human@test",
        "name": {"value": "6mm endmill"},
        "manufacturer": {"value": "TestCo"},
        "product_code": {"value": code},
        "geometry": {"diameter": {"value": 6.0, "unit": "mm"}}})
    assert r.status_code == 200, r.text
    return r.json()["internal"]["id"]


def _preset(**overrides):
    body = {"origin": "user", "label": "6061 profiling",
            "material": {"name": "6061-T6"}, "op_type": "profiling",
            "vc": {"value": 250, "unit": "m/min"},
            "fz": {"value": 0.05, "unit": "mm"},
            "actor": "human@test"}
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


@pytest.mark.contract
class TestContribute:
    def test_contribution_materializes_derived_union(self, solo_client):
        rid = _instance(solo_client)
        r = solo_client.post(
            f"{BASE}/tool-instance-records/{rid}/presets", json=_preset())
        assert r.status_code == 200, r.text
        presets = r.json()["canonical"]["presets"]
        assert presets["source"] == "derived:preset-union"
        (entry,) = presets["value"]
        assert entry["origin"] == "user"
        assert entry["label"] == "6061 profiling"
        assert entry["vc"] == {"value": 250, "unit": "m/min"}
        assert entry["source"] == "asserted:human@test"
        assert entry["preset_schema"] == 1

    def test_replace_own_supersedes_same_origin_label(self, solo_client):
        rid = _instance(solo_client)
        url = f"{BASE}/tool-instance-records/{rid}/presets"
        solo_client.post(url, json=_preset())
        r = solo_client.post(url, json=_preset(vc={"value": 300,
                                                   "unit": "m/min"}))
        (entry,) = r.json()["canonical"]["presets"]["value"]
        assert entry["vc"]["value"] == 300

    def test_different_label_is_a_second_entry(self, solo_client):
        rid = _instance(solo_client)
        url = f"{BASE}/tool-instance-records/{rid}/presets"
        solo_client.post(url, json=_preset())
        r = solo_client.post(url, json=_preset(label="6061 aggressive",
                                               fz={"value": 0.09,
                                                   "unit": "mm"}))
        assert len(r.json()["canonical"]["presets"]["value"]) == 2

    def test_corroboration_from_two_origins_keeps_both(self, solo_client):
        # Identical values from different origins are corroboration —
        # the server never dedups across sources.
        rid = _instance(solo_client)
        url = f"{BASE}/tool-instance-records/{rid}/presets"
        solo_client.post(url, json=_preset(origin="freecad"))
        r = solo_client.post(url, json=_preset(origin="fusion"))
        assert len(r.json()["canonical"]["presets"]["value"]) == 2

    def test_floor_rejects_no_engineering_values(self, solo_client):
        rid = _instance(solo_client)
        r = solo_client.post(
            f"{BASE}/tool-instance-records/{rid}/presets",
            json=_preset(vc=None, fz=None))
        assert r.status_code == 400
        assert "engineering value" in r.json()["detail"]

    def test_unknown_op_type_is_400_ratified(self, solo_client):
        rid = _instance(solo_client)
        r = solo_client.post(
            f"{BASE}/tool-instance-records/{rid}/presets",
            json=_preset(op_type="milling"))
        assert r.status_code == 400
        assert "ratified" in r.json()["detail"]

    def test_unknown_record_is_404(self, solo_client):
        r = solo_client.post(
            f"{BASE}/tool-instance-records/nope/presets", json=_preset())
        assert r.status_code == 404

    def test_assert_door_refuses_presets_path(self, solo_client):
        rid = _instance(solo_client)
        r = solo_client.post(
            f"{BASE}/tool-instance-records/{rid}/assert",
            json={"path": "presets", "value": [], "actor": "human@test"})
        assert r.status_code == 400
        assert "derived" in r.json()["detail"]

    def test_catalog_assert_door_refuses_presets_path(self, solo_client):
        cid = _catalog(solo_client, code="P101")
        r = solo_client.post(
            f"{BASE}/tool-catalog-records/{cid}/assert",
            json={"path": "presets.x", "value": 1, "actor": "human@test"})
        assert r.status_code == 400


@pytest.mark.contract
class TestUnionAndFilters:
    def _linked_pair(self, solo_client, code="P200"):
        cid = _catalog(solo_client, code=code)
        r = solo_client.post(
            f"{BASE}/tool-catalog-records/{cid}/create-instance", json={})
        assert r.status_code == 200, r.text
        return cid, r.json()["internal"]["id"]

    def test_instance_listing_unions_linked_catalog(self, solo_client):
        cid, rid = self._linked_pair(solo_client)
        solo_client.post(f"{BASE}/tool-catalog-records/{cid}/presets",
                         json=_preset(origin="manufacturer",
                                      label="chart row"))
        solo_client.post(f"{BASE}/tool-instance-records/{rid}/presets",
                         json=_preset(origin="user", label="what worked"))
        r = solo_client.get(f"{BASE}/tool-instance-records/{rid}/presets")
        entries = r.json()["presets"]
        assert {(e["origin"], e["scope"]) for e in entries} == {
            ("user", "instance"), ("manufacturer", "catalog")}

    def test_catalog_entries_never_materialize_on_instance(self, solo_client):
        # The union is composed at read time; the instance record itself
        # carries only its own contributions.
        cid, rid = self._linked_pair(solo_client, code="P201")
        solo_client.post(f"{BASE}/tool-catalog-records/{cid}/presets",
                         json=_preset(origin="manufacturer"))
        r = solo_client.get(f"{BASE}/tool-instance-records/{rid}")
        assert "presets" not in r.json()["canonical"]

    def test_filters(self, solo_client):
        rid = _instance(solo_client)
        url = f"{BASE}/tool-instance-records/{rid}/presets"
        solo_client.post(url, json=_preset(origin="freecad",
                                           label="alu",
                                           material={"name": "6061"}))
        solo_client.post(url, json=_preset(origin="user", label="steel",
                                           material={"name": "4140"},
                                           op_type="slotting"))
        r = solo_client.get(url, params={"material": "6061"})
        assert [e["origin"] for e in r.json()["presets"]] == ["freecad"]
        r = solo_client.get(url, params={"op_type": "slotting"})
        assert [e["label"] for e in r.json()["presets"]] == ["steel"]


@pytest.mark.contract
class TestLifecycle:
    def test_delete_entry_rematerializes(self, solo_client):
        rid = _instance(solo_client)
        url = f"{BASE}/tool-instance-records/{rid}/presets"
        r = solo_client.post(url, json=_preset())
        entry_id = r.json()["canonical"]["presets"]["value"][0]["id"]
        r = solo_client.delete(f"{url}/{entry_id}")
        assert r.status_code == 200, r.text
        assert "presets" not in r.json()["canonical"]

    def test_delete_unknown_entry_is_404(self, solo_client):
        rid = _instance(solo_client)
        r = solo_client.delete(
            f"{BASE}/tool-instance-records/{rid}/presets/nope")
        assert r.status_code == 404

    def test_catalog_contribute_and_delete(self, solo_client):
        cid = _catalog(solo_client, code="P300")
        url = f"{BASE}/tool-catalog-records/{cid}/presets"
        r = solo_client.post(url, json=_preset(origin="manufacturer"))
        assert r.status_code == 200, r.text
        presets = r.json()["canonical"]["presets"]
        assert presets["source"] == "derived:preset-union"
        entry_id = presets["value"][0]["id"]
        r = solo_client.delete(f"{url}/{entry_id}")
        assert "presets" not in r.json()["canonical"]

    def test_record_survives_sync_roundtrip(self, solo_client):
        # A client-section write must not disturb the derived union.
        rid = _instance(solo_client)
        solo_client.post(f"{BASE}/tool-instance-records/{rid}/presets",
                         json=_preset())
        r = solo_client.put(
            f"{BASE}/tool-instance-records/{rid}/clients/freecad",
            json={"client_version": "0.5.0",
                  "data": {"fctb": {"presets": [{"name": "native"}]}}})
        assert r.status_code == 200, r.text
        r = solo_client.get(f"{BASE}/tool-instance-records/{rid}")
        assert len(r.json()["canonical"]["presets"]["value"]) == 1
