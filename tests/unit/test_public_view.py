# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the public projection (loobric_server/public_view.py).

The projection is allowlist CONSTRUCTION: these tests feed it records
stuffed with private material and assert the output contains only the named
public fields — plus the provenance-kind reduction rules.
"""
from types import SimpleNamespace

from loobric_server.public_view import public_projection


def _row(canonical):
    return SimpleNamespace(canonical=canonical)


def _full_instance():
    return _row({
        "name": {"value": "my 6mm", "source": "asserted:human@cli"},
        "catalog_type_id": {"value": "cat-uuid", "source": "asserted:freecad"},
        "status": {"value": "in-drawer", "source": "asserted:human@cli"},
        "geometry": {
            "diameter": {"value": 5.98, "unit": "mm",
                         "source": "observed:linuxcnc@vf2"},
            "shape": {"value": "endmill", "source": "asserted:freecad"},
            "length": {"value": None, "source": "unknown"},
            "exotic_key": {"value": 42, "source": "asserted:freecad"},
        },
        "media": [{"ref": "sha256:deadbeef", "role": "photo"}],
        "usage": {"hours": {"value": 37.4, "unit": "h",
                            "source": "derived:usage-ledger"}},
    })


class TestAllowlist:
    def test_public_fields_present(self):
        out = public_projection(_full_instance())
        assert out["name"] == "my 6mm"
        assert out["geometry"]["diameter"] == {
            "value": 5.98, "unit": "mm", "provenance": "observed"}
        assert out["geometry"]["shape"]["value"] == "endmill"
        assert out["usage_hours"] == {
            "value": 37.4, "unit": "h", "provenance": "derived:usage-ledger"}

    def test_private_material_absent(self):
        out = public_projection(_full_instance())
        flat = repr(out)
        for private in ("cat-uuid", "in-drawer", "sha256", "vf2", "linuxcnc",
                        "human@cli", "freecad", "exotic_key"):
            assert private not in flat, private

    def test_unknown_leaves_dropped(self):
        out = public_projection(_full_instance())
        assert "length" not in out["geometry"]

    def test_open_vocabulary_geometry_not_shown(self):
        """Extra geometry keys are legal in canonical but NOT public —
        allowlist, not filter."""
        out = public_projection(_full_instance())
        assert "exotic_key" not in out["geometry"]


class TestProvenanceKinds:
    def test_sources_reduced_to_kind(self):
        out = public_projection(_full_instance())
        kinds = {leaf["provenance"] for leaf in out["geometry"].values()}
        assert kinds <= {"observed", "asserted", "derived"}

    def test_usage_requires_the_ledger_source(self):
        """A usage.hours leaf that is NOT derived:usage-ledger (someone found
        a way to write one) never goes public."""
        row = _full_instance()
        row.canonical["usage"]["hours"]["source"] = "asserted:human@cli"
        assert public_projection(row)["usage_hours"] is None

    def test_malformed_sources_read_as_unknown(self):
        row = _row({"name": {"value": "x", "source": "asserted:a"},
                    "geometry": {"diameter": {"value": 1.0, "source": None}}})
        out = public_projection(row)
        assert out["geometry"]["diameter"]["provenance"] == "unknown"


class TestCatalog:
    def test_catalog_projection(self):
        catalog = _row({
            "name": {"value": "3F-6MM", "source": "asserted:kodiak"},
            "manufacturer": {"value": "Kodiak", "source": "asserted:kodiak"},
            "product_code": {"value": "KDK-3F6", "source": "asserted:kodiak"},
            "geometry": {"diameter": {"value": 6.0, "unit": "mm",
                                      "source": "asserted:kodiak"}},
        })
        out = public_projection(_full_instance(), catalog)
        assert out["catalog"]["manufacturer"] == "Kodiak"
        assert out["catalog"]["geometry"]["diameter"]["provenance"] == "asserted"
        assert "kodiak" not in repr(out["catalog"])  # actor never surfaces

    def test_no_catalog_is_none(self):
        assert public_projection(_full_instance())["catalog"] is None


class TestHostileShapes:
    def test_empty_canonical(self):
        out = public_projection(_row({}))
        assert out == {"name": None, "catalog": None, "geometry": {},
                       "usage_hours": None}

    def test_none_canonical(self):
        assert public_projection(_row(None))["geometry"] == {}

    def test_non_dict_leaves_ignored(self):
        out = public_projection(_row({"name": "bare string",
                                      "geometry": {"diameter": 6.0}}))
        assert out["name"] is None
        assert out["geometry"] == {}
