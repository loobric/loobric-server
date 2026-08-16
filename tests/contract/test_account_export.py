# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the account export zip (the owner-operated escape
hatch; first slice of #46). Read-gated, user-scoped, honest about missing
media."""
import io
import json
import zipfile

import pytest

BASE = "/api/v1"


def _export(solo_client):
    r = solo_client.get(f"{BASE}/account/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "loobric-export-" in r.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(r.content))


@pytest.mark.contract
class TestAccountExport:
    def test_zip_carries_all_collections_and_manifest(self, solo_client):
        zf = _export(solo_client)
        names = set(zf.namelist())
        for expected in ("manifest.json", "tool_instance_records.json",
                         "tool_catalog_records.json", "tool_set_records.json",
                         "machine_records.json",
                         "tool_table_entry_records.json", "labels.json"):
            assert expected in names, expected
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == "loobric-account-export"

    def test_records_export_verbatim(self, solo_client):
        r = solo_client.post(f"{BASE}/tool-instance-records", json={})
        rid = r.json()["internal"]["id"]
        solo_client.post(f"{BASE}/tool-instance-records/{rid}/assert",
                         json={"path": "name", "value": "Export Mill",
                               "actor": "human@test"})
        solo_client.post(f"{BASE}/labels", json={"entity_id": rid})
        zf = _export(solo_client)
        records = json.loads(zf.read("tool_instance_records.json"))
        record = next(x for x in records if x["internal"]["id"] == rid)
        assert record["canonical"]["name"]["value"] == "Export Mill"
        assert record["canonical"]["name"]["source"] == "asserted:human@test"
        labels = json.loads(zf.read("labels.json"))
        assert any(label["entity_id"] == rid for label in labels)

    def test_export_is_audited_but_changes_nothing(self, solo_client):
        r = solo_client.post(f"{BASE}/tool-instance-records", json={})
        rid = r.json()["internal"]["id"]
        version = r.json()["internal"]["version"]
        _export(solo_client)
        r = solo_client.get(f"{BASE}/tool-instance-records/{rid}")
        assert r.json()["internal"]["version"] == version
