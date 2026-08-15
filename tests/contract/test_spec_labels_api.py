# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the spec-labels API (docs/SPEC_LABELS.md).

A spec label is a rendering of a record, not a Label: printing rides the
read door, never mints, and everything printed is a snapshot at print
time. The QR element resolves each record's newest label; unlabeled
records under a QR template are a 400 naming the ids."""
import pytest

BASE = "/api/v1"


def _make_instance(solo_client, name="Test Mill", **geometry):
    r = solo_client.post(f"{BASE}/tool-instance-records", json={})
    assert r.status_code == 200, r.text
    rid = r.json()["internal"]["id"]
    if name:
        solo_client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                         json={"path": "name", "value": name,
                               "actor": "human@test"})
    for key, value in geometry.items():
        r = solo_client.post(
            f"{BASE}/tool-instance-records/{rid}/assert",
            json={"path": "geometry.%s" % key, "value": value, "unit": "mm",
                  "actor": "human@test"})
        assert r.status_code == 200, r.text
    return rid


def _label(solo_client, rid):
    r = solo_client.post(f"{BASE}/labels", json={"entity_id": rid})
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def _sheet(solo_client, **payload):
    payload.setdefault("template", "qr-specs")
    payload.setdefault("stock", "avery-5160")
    return solo_client.post(f"{BASE}/spec-labels/sheet", json=payload)


@pytest.mark.contract
class TestSheet:
    def test_pdf_for_labeled_record(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0)
        _label(solo_client, rid)
        r = _sheet(solo_client, record_ids=[rid])
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")

    def test_unlabeled_record_is_400_naming_ids(self, solo_client):
        rid = _make_instance(solo_client)
        r = _sheet(solo_client, record_ids=[rid])
        assert r.status_code == 400
        assert r.json()["detail"]["unlabeled_record_ids"] == [rid]

    def test_plaque_template_needs_no_label(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0, length=63.0)
        r = _sheet(solo_client, record_ids=[rid], template="spec-plaque",
                   stock="plaque-38x19")
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")

    def test_printing_never_mints(self, solo_client):
        """Read-only: a failed QR print leaves no labels behind."""
        rid = _make_instance(solo_client)
        assert _sheet(solo_client, record_ids=[rid]).status_code == 400
        r = solo_client.get(f"{BASE}/labels")
        assert r.json()["items"] == []

    def test_unknown_record_is_404(self, solo_client):
        r = _sheet(solo_client, record_ids=["no-such-record"])
        assert r.status_code == 404

    @pytest.mark.parametrize("field,value", [
        ("template", "fancy"), ("stock", "avery-9999"), ("format", "xml")])
    def test_bad_enum_is_400(self, solo_client, field, value):
        rid = _make_instance(solo_client)
        r = _sheet(solo_client, record_ids=[rid], **{field: value})
        assert r.status_code == 400

    def test_start_at_bounds(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0, length=63.0)
        r = _sheet(solo_client, record_ids=[rid], template="spec-plaque",
                   stock="plaque-38x19", start_at=1)
        assert r.status_code == 400

    def test_empty_record_ids_is_400(self, solo_client):
        assert _sheet(solo_client, record_ids=[]).status_code == 400


@pytest.mark.contract
class TestResolution:
    def test_export_carries_merged_specs(self, solo_client):
        rid = _make_instance(solo_client, diameter=5.92, flutes=4,
                             cutting_edge_height=19.0, length=63.0)
        _label(solo_client, rid)
        r = _sheet(solo_client, record_ids=[rid], format="json")
        assert r.status_code == 200, r.text
        (row,) = r.json()["items"]
        assert row["diameter"] == 5.92
        assert row["flutes"] == 4
        assert row["loc"] == 19.0
        assert row["oal"] == 63.0
        assert row["name"] == "Test Mill"
        assert row["unit"] == "mm"

    def test_tool_number_from_bound_entry_only(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0)
        _label(solo_client, rid)
        eid = solo_client.post(f"{BASE}/tool-table-entry-records",
                               json={"machine_id": "m-1"}
                               ).json()["internal"]["id"]
        solo_client.post(
            f"{BASE}/tool-table-entry-records/{eid}/observe",
            json={"path": "tool_number", "value": 7, "client": "linuxcnc",
                  "machine": "millstone"})
        assert solo_client.post(
            f"{BASE}/tool-table-entry-records/{eid}/bind",
            json={"instance_id": rid}).status_code == 200
        r = _sheet(solo_client, record_ids=[rid], format="json")
        (row,) = r.json()["items"]
        assert row["tool_number"] == 7

    def test_unbound_tool_number_is_none(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0)
        _label(solo_client, rid)
        r = _sheet(solo_client, record_ids=[rid], format="json")
        (row,) = r.json()["items"]
        assert row["tool_number"] is None

    def test_newest_label_wins_and_override_beats_it(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0)
        first = _label(solo_client, rid)
        second = _label(solo_client, rid)
        r = _sheet(solo_client, record_ids=[rid], format="json")
        (row,) = r.json()["items"]
        assert row["code"] == second["code"]
        r = _sheet(solo_client, record_ids=[rid], format="json",
                   labels={rid: first["id"]})
        (row,) = r.json()["items"]
        assert row["code"] == first["code"]

    def test_override_must_point_at_the_record(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0)
        other = _make_instance(solo_client, name="Other")
        _label(solo_client, rid)
        wrong = _label(solo_client, other)
        r = _sheet(solo_client, record_ids=[rid], format="json",
                   labels={rid: wrong["id"]})
        assert r.status_code == 404

    def test_csv_export(self, solo_client):
        rid = _make_instance(solo_client, diameter=6.0)
        _label(solo_client, rid)
        r = _sheet(solo_client, record_ids=[rid], format="csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        header, row = r.text.strip().splitlines()[:2]
        assert "oal" in header and "spec_line" in header

    def test_marked_reground_value(self, solo_client):
        """Measured differing from catalog nominal is marked (`*`)."""
        r = solo_client.post(f"{BASE}/tool-catalog-records", json={
            "actor": "human@test",
            "name": {"value": "6mm 4FL Endmill"},
            "manufacturer": {"value": "Kennametal"},
            "product_code": {"value": "B201"},
            "geometry": {"diameter": {"value": 6.0, "unit": "mm"}}})
        assert r.status_code == 200, r.text
        cat = r.json()["internal"]["id"]
        rid = _make_instance(solo_client, diameter=5.92)
        solo_client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                         json={"path": "catalog_type_id", "value": cat,
                               "actor": "human@test"})
        _label(solo_client, rid)
        r = _sheet(solo_client, record_ids=[rid], format="json")
        (row,) = r.json()["items"]
        assert row["diameter"] == 5.92
        assert "diameter" in row["marked"]
        assert "Ø5.92*" in row["spec_line"]
