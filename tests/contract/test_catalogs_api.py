# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for Catalogs — named collections of catalog records
(grilled 2026-08-16). Membership is organization, never identity: records
may sit in many catalogs, deleting a catalog deletes no records, and the
account-wide natural key is untouched by grouping."""
import io

import pytest

BASE = "/api/v1"


def _record(solo_client, code, mfr="TestCo"):
    r = solo_client.post(f"{BASE}/tool-catalog-records", json={
        "actor": "human@test",
        "name": {"value": "tool " + code},
        "manufacturer": {"value": mfr},
        "product_code": {"value": code}})
    assert r.status_code == 200, r.text
    return r.json()["internal"]["id"]


def _catalog(solo_client, name="My catalog"):
    r = solo_client.post(f"{BASE}/catalogs", json={"name": name,
                                                   "actor": "human@test"})
    assert r.status_code == 201, r.text
    return r.json()["internal"]["id"]


@pytest.mark.contract
class TestCatalogCrud:
    def test_create_list_get(self, solo_client):
        cid = _catalog(solo_client, "Harvey 2026")
        r = solo_client.get(f"{BASE}/catalogs")
        names = [c["canonical"]["name"]["value"] for c in r.json()["items"]]
        assert "Harvey 2026" in names
        r = solo_client.get(f"{BASE}/catalogs/{cid}")
        assert r.json()["canonical"]["members"]["value"] == []
        assert r.json()["canonical"]["name"]["source"] == "asserted:human@test"

    def test_rename(self, solo_client):
        cid = _catalog(solo_client, "old name")
        r = solo_client.post(f"{BASE}/catalogs/{cid}/rename",
                             json={"name": "new name", "actor": "human@test"})
        assert r.json()["canonical"]["name"]["value"] == "new name"

    def test_empty_name_is_400(self, solo_client):
        r = solo_client.post(f"{BASE}/catalogs", json={"name": "  ",
                                                       "actor": "human@test"})
        assert r.status_code == 400

    def test_unknown_catalog_is_404(self, solo_client):
        assert solo_client.get(f"{BASE}/catalogs/nope").status_code == 404


@pytest.mark.contract
class TestMembership:
    def test_replace_members(self, solo_client):
        cid = _catalog(solo_client)
        r1, r2 = _record(solo_client, "M100"), _record(solo_client, "M101")
        r = solo_client.post(f"{BASE}/catalogs/{cid}/members",
                             json={"members": [r1, r2, r1],   # dupe collapses
                                   "actor": "human@test"})
        assert r.json()["canonical"]["members"]["value"] == [r1, r2]

    def test_record_may_sit_in_many_catalogs(self, solo_client):
        rid = _record(solo_client, "M200")
        c1, c2 = _catalog(solo_client, "import"), _catalog(solo_client, "curated")
        for cid in (c1, c2):
            r = solo_client.post(f"{BASE}/catalogs/{cid}/members",
                                 json={"members": [rid], "actor": "human@test"})
            assert rid in r.json()["canonical"]["members"]["value"]

    def test_unknown_member_is_400_naming_ids(self, solo_client):
        cid = _catalog(solo_client)
        r = solo_client.post(f"{BASE}/catalogs/{cid}/members",
                             json={"members": ["ghost"], "actor": "human@test"})
        assert r.status_code == 400
        assert r.json()["detail"]["unknown_record_ids"] == ["ghost"]

    def test_delete_catalog_keeps_records(self, solo_client):
        cid = _catalog(solo_client)
        rid = _record(solo_client, "M300")
        solo_client.post(f"{BASE}/catalogs/{cid}/members",
                         json={"members": [rid], "actor": "human@test"})
        assert solo_client.delete(f"{BASE}/catalogs/{cid}").json()["deleted"] == cid
        assert solo_client.get(
            f"{BASE}/tool-catalog-records/{rid}").status_code == 200

    def test_natural_key_stays_account_wide(self, solo_client):
        # Grouping never relaxes uniqueness: the same (manufacturer,
        # product_code) is still a 409 regardless of catalogs.
        _record(solo_client, "M400", mfr="DupCo")
        r = solo_client.post(f"{BASE}/tool-catalog-records", json={
            "actor": "human@test", "name": {"value": "again"},
            "manufacturer": {"value": "DupCo"},
            "product_code": {"value": "M400"}})
        assert r.status_code == 409


@pytest.mark.contract
class TestImportAutoCatalog:
    def test_import_lands_in_named_catalog(self, solo_client):
        # The real DIN4000-82 fixture (single manufacturer -> catalog is
        # named after it, not the filename).
        from pathlib import Path
        fixture = Path(__file__).parent.parent / "fixtures" / "importers" \
            / "din4000-82.csv"
        data = fixture.read_bytes()
        r = solo_client.post(
            f"{BASE}/tool-catalog-records/import",
            files={"file": ("din4000-82.csv", io.BytesIO(data), "text/csv")})
        assert r.status_code == 200, r.text
        report = r.json()
        assert report["created"], report
        assert "catalog" in report, report
        cat = solo_client.get(
            f"{BASE}/catalogs/{report['catalog']['id']}").json()
        member_ids = cat["canonical"]["members"]["value"]
        assert {c["id"] for c in report["created"]} <= set(member_ids)
        # Re-import is idempotent: same catalog, no member growth.
        r2 = solo_client.post(
            f"{BASE}/tool-catalog-records/import",
            files={"file": ("din4000-82.csv", io.BytesIO(data), "text/csv")})
        assert r2.json()["catalog"]["id"] == report["catalog"]["id"]
        cat2 = solo_client.get(
            f"{BASE}/catalogs/{report['catalog']['id']}").json()
        assert cat2["canonical"]["members"]["value"] == member_ids
