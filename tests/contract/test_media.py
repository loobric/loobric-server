# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Canonical media contract tests (docs/TOOL_SCHEMA.md §Media).

A tool record carries media (3D models, drawings, images) as a provenance-tagged
canonical reference; the bytes live in a content-addressed blob store and are
served out-of-band. These tests prove: the reference is canonical (not client
data), the server stamps provenance, the bytes round-trip, and the descriptor is
contract-validated.
"""
import pytest

from loobric_server.contract import CatalogCanonical, MediaRef, ToolCatalogRecord

CATALOG = "/api/v1/tool-catalog-records"
# A tiny stand-in for a STEP solid — the server stores bytes opaquely; it never
# parses them, so the content is irrelevant to the contract.
FAKE_STEP = b"ISO-10303-21;\nHEADER;\n/* not a real model */\nENDSEC;\nEND-ISO-10303-21;\n"


@pytest.fixture(autouse=True)
def _tmp_media(monkeypatch, tmp_path):
    """Redirect the blob store to a temp dir so tests never touch real storage."""
    from loobric_server.config import settings
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "blobs"))


def _seed_catalog(client) -> str:
    r = client.post(CATALOG, json={
        "actor": "manufacturer:kennametal",
        "name": {"value": "HARVI I TE 1/4 endmill"},
        "manufacturer": {"value": "Kennametal"},
        "product_code": {"value": "6676918"},
    })
    assert r.status_code == 200, r.text
    return r.json()["internal"]["id"]


def _upload(client, rid, *, role="model_3d", actor="catalog-import",
            filename="6676918.stp", content_type="model/step", data=FAKE_STEP):
    return client.post(f"{CATALOG}/{rid}/media",
                       files={"file": (filename, data, content_type)},
                       data={"role": role, "actor": actor})


# -- contract (pure, no server) ----------------------------------------------

def test_mediaref_validates_good_and_rejects_bad_role():
    MediaRef.model_validate(
        {"role": "model_3d", "ref": "sha256:ab", "content_type": "model/step"})
    with pytest.raises(Exception):
        MediaRef.model_validate(
            {"role": "bogus", "ref": "sha256:ab", "content_type": "model/step"})


def test_catalog_canonical_accepts_media_field():
    CatalogCanonical.model_validate({
        "name": {"value": "x", "source": "asserted:a"},
        "media": {"value": [
            {"role": "model_3d", "ref": "sha256:ab", "content_type": "model/step",
             "filename": "x.stp", "size": 10}],
            "source": "asserted:catalog-import"},
    })


def test_media_value_must_be_a_list():
    with pytest.raises(Exception):
        CatalogCanonical.model_validate({
            "name": {"value": "x", "source": "asserted:a"},
            "media": {"value": "not-a-list", "source": "asserted:a"},
        })


# -- endpoints ----------------------------------------------------------------

def test_upload_attaches_provenance_tagged_reference(solo_client):
    rid = _seed_catalog(solo_client)
    r = _upload(solo_client, rid)
    assert r.status_code == 200, r.text
    doc = r.json()
    ToolCatalogRecord.model_validate(doc)               # server emits conformant data
    media = doc["canonical"]["media"]
    assert media["source"] == "asserted:catalog-import"  # server-stamped, not client
    assert len(media["value"]) == 1
    entry = media["value"][0]
    assert entry["role"] == "model_3d"
    assert entry["ref"].startswith("sha256:")
    assert entry["content_type"] == "model/step"
    assert entry["size"] == len(FAKE_STEP)


def test_uploaded_bytes_round_trip(solo_client):
    rid = _seed_catalog(solo_client)
    ref = _upload(solo_client, rid).json()["canonical"]["media"]["value"][0]["ref"]
    g = solo_client.get(f"{CATALOG}/{rid}/media/{ref}")
    assert g.status_code == 200
    assert g.content == FAKE_STEP


def test_invalid_role_is_rejected(solo_client):
    rid = _seed_catalog(solo_client)
    assert _upload(solo_client, rid, role="not-a-role").status_code == 400


def test_identical_bytes_same_role_dedupe(solo_client):
    rid = _seed_catalog(solo_client)
    _upload(solo_client, rid)
    doc = _upload(solo_client, rid).json()                    # same bytes + role again
    assert len(doc["canonical"]["media"]["value"]) == 1


def test_multiple_roles_coexist(solo_client):
    rid = _seed_catalog(solo_client)
    _upload(solo_client, rid, role="model_3d")
    doc = _upload(solo_client, rid, role="model_3d_basic", data=b"basic model").json()
    roles = {m["role"] for m in doc["canonical"]["media"]["value"]}
    assert roles == {"model_3d", "model_3d_basic"}


def test_delete_drops_reference(solo_client):
    rid = _seed_catalog(solo_client)
    ref = _upload(solo_client, rid).json()["canonical"]["media"]["value"][0]["ref"]
    d = solo_client.delete(f"{CATALOG}/{rid}/media/{ref}")
    assert d.status_code == 200
    assert d.json()["canonical"]["media"]["value"] == []
    assert solo_client.get(f"{CATALOG}/{rid}/media/{ref}").status_code == 404


def test_get_unknown_ref_is_404(solo_client):
    rid = _seed_catalog(solo_client)
    assert solo_client.get(f"{CATALOG}/{rid}/media/sha256:deadbeef").status_code == 404


def test_media_is_canonical_not_client_data(solo_client):
    """A routine client sync writes only its own section — it cannot create
    canonical media (lane discipline). Media stays absent until uploaded."""
    rid = _seed_catalog(solo_client)
    r = solo_client.put(f"{CATALOG}/{rid}/clients/freecad",
                        json={"client_version": "1.0", "data": {"note": "hi"}})
    assert r.status_code == 200
    assert "media" not in r.json()["canonical"]
