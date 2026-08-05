# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for manufacturer-file catalog import
(POST /tool-catalog-records/import) — the web-UI equivalent of the CLI's
`loobric import`, backed by the vendored importers package.

Fixtures are the same sample files the CLI's importer tests use.
"""
from pathlib import Path

import pytest

BASE = "/api/v1"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "importers"


def _upload(solo_client, filename, content=None):
    data = content if content is not None else (FIXTURES / filename).read_bytes()
    return solo_client.post(f"{BASE}/tool-catalog-records/import",
                            files={"file": (filename, data,
                                            "application/octet-stream")})


@pytest.mark.contract
class TestImport:
    def test_din4000_csv_creates_catalog_records(self, solo_client):
        r = _upload(solo_client, "din4000-82.csv")
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["format"] == "din4000-csv"
        assert len(rep["created"]) >= 1
        assert rep["failed"] == []

        listing = solo_client.get(
            f"{BASE}/tool-catalog-records").json()["items"]
        assert len(listing) == len(rep["created"])
        rec = listing[0]
        # Identity floor present, provenance server-stamped as an assertion.
        for fld in ("name", "manufacturer", "product_code"):
            leaf = rec["canonical"][fld]
            assert leaf["value"], fld
            assert leaf["source"].startswith("asserted:"), fld
        # Lossless preservation: the raw source payload rides a client section.
        (cname,) = rec["clients"].keys()
        preserved = rec["clients"][cname]["data"]
        assert preserved["format"] == "din4000-csv"
        assert preserved["properties"]

    def test_reimport_is_idempotent(self, solo_client):
        first = _upload(solo_client, "din4000-82.csv").json()
        again = _upload(solo_client, "din4000-82.csv").json()
        assert again["created"] == []
        assert len(again["existing"]) == len(first["created"])
        listing = solo_client.get(
            f"{BASE}/tool-catalog-records").json()["items"]
        assert len(listing) == len(first["created"])   # nothing duplicated

    @pytest.mark.parametrize("fixture", ["iso13399.p21", "din4000-82_2016.xml",
                                         "solidcam.xml", "hypermill.xml"])
    def test_other_formats_parse_and_import(self, solo_client, fixture):
        r = _upload(solo_client, fixture)
        assert r.status_code == 200, (fixture, r.text)
        rep = r.json()
        # Every fixture must produce SOMETHING and fail nothing outright;
        # identity-floor skips are legal (honest sources can be sparse).
        assert rep["created"] or rep["skipped"], fixture
        assert rep["failed"] == [], fixture

    def test_garbage_is_400(self, solo_client):
        r = _upload(solo_client, "noise.bin", content=b"\x00\x01nonsense")
        assert r.status_code == 400

    def test_custom_actor_stamps_provenance(self, solo_client):
        data = (FIXTURES / "din4000-82.csv").read_bytes()
        r = solo_client.post(
            f"{BASE}/tool-catalog-records/import",
            files={"file": ("din4000-82.csv", data, "text/csv")},
            data={"actor": "kennametal-site"})
        assert r.status_code == 200, r.text
        rec = solo_client.get(
            f"{BASE}/tool-catalog-records").json()["items"][0]
        assert rec["canonical"]["name"]["source"] == "asserted:kennametal-site"
