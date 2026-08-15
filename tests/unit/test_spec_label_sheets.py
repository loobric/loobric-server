# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for spec-label rendering (loobric_server/spec_label_sheets.py):
the merged view, the `*` marker, the spec line, and sheet geometry."""
import pytest

from loobric_server.spec_label_sheets import (PLAQUE_STOCKS, SPEC_STOCKS,
                                              export_rows, render_spec_sheet,
                                              resolve_spec, spec_line)


def _field(value, unit=None, source="asserted:test"):
    field = {"value": value, "source": source}
    if unit:
        field["unit"] = unit
    return field


def _instance_canonical(**geometry):
    return {"name": _field("Test Mill"),
            "geometry": {k: _field(v, unit="mm") for k, v in geometry.items()}}


def _catalog_canonical(**geometry):
    return {"name": _field("Catalog Mill"),
            "manufacturer": _field("Kennametal"),
            "geometry": {k: _field(v, unit="mm") for k, v in geometry.items()}}


def _item(**overrides):
    item = resolve_spec(
        _instance_canonical(diameter=6.0, flutes=4, cutting_edge_height=19.0,
                            length=63.0, shank_diameter=6.0),
        _catalog_canonical(diameter=6.0))
    item.update({"record_id": "r-1", "tool_number": 7,
                 "code": "A3F9X7K2", "url": "https://x/t/A3F9X7K2"})
    item.update(overrides)
    return item


def _page_count(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


class TestResolveSpec:
    def test_measured_wins_over_nominal(self):
        item = resolve_spec(_instance_canonical(diameter=5.92),
                            _catalog_canonical(diameter=6.0))
        assert item["geometry"]["diameter"] == 5.92

    def test_differing_measured_is_marked(self):
        item = resolve_spec(_instance_canonical(diameter=5.92),
                            _catalog_canonical(diameter=6.0))
        assert "diameter" in item["marked"]

    def test_equal_values_are_not_marked(self):
        item = resolve_spec(_instance_canonical(diameter=6.0),
                            _catalog_canonical(diameter=6.0))
        assert item["marked"] == []

    def test_nominal_fills_gaps(self):
        item = resolve_spec(_instance_canonical(diameter=5.92),
                            _catalog_canonical(diameter=6.0, flutes=4))
        assert item["geometry"]["flutes"] == 4
        assert "flutes" not in item["marked"]

    def test_no_catalog(self):
        item = resolve_spec(_instance_canonical(diameter=3.0))
        assert item["geometry"]["diameter"] == 3.0
        assert item["manufacturer"] is None
        assert item["marked"] == []

    def test_instance_name_wins(self):
        item = resolve_spec(_instance_canonical(), _catalog_canonical())
        assert item["name"] == "Test Mill"

    def test_catalog_name_fills_unnamed(self):
        item = resolve_spec({"name": _field(None, source="unknown")},
                            _catalog_canonical())
        assert item["name"] == "Catalog Mill"

    def test_unit_comes_from_fields(self):
        assert resolve_spec(_instance_canonical(diameter=6.0))["unit"] == "mm"


class TestSpecLine:
    def test_full_line(self):
        assert spec_line(_item()) == "Ø6 · 4FL · LOC 19 · OAL 63  (mm)"

    def test_marker_rides_the_value(self):
        item = _item()
        item["geometry"]["diameter"] = 5.92
        item["marked"] = ["diameter"]
        assert spec_line(item).startswith("Ø5.92*")

    def test_compact_drops_unit_and_tightens(self):
        line = spec_line(_item(), include_unit=False, compact=True)
        assert line == "Ø6·4FL·LOC 19·OAL 63"

    def test_missing_fields_are_omitted(self):
        item = _item()
        del item["geometry"]["cutting_edge_height"]
        assert "LOC" not in spec_line(item)


class TestRender:
    def test_pdf_magic(self):
        pdf = render_spec_sheet([_item()], "qr-specs", "avery-5160")
        assert pdf.startswith(b"%PDF")

    def test_avery_is_30_up(self):
        items = [_item() for _ in range(31)]
        assert _page_count(
            render_spec_sheet(items, "qr-specs", "avery-5160")) == 2

    def test_plaque_stocks_are_one_per_page(self):
        for stock in PLAQUE_STOCKS:
            pdf = render_spec_sheet([_item(), _item()], "spec-plaque", stock)
            assert _page_count(pdf) == 2

    def test_plaque_needs_no_code(self):
        item = _item(code=None, url=None, tool_number=None)
        assert render_spec_sheet(
            [item], "spec-plaque", "plaque-38x19").startswith(b"%PDF")

    def test_roomy_layout_on_thermal(self):
        assert render_spec_sheet(
            [_item()], "qr-specs", "thermal-57x32").startswith(b"%PDF")

    def test_sparse_geometry_renders(self):
        item = resolve_spec(_instance_canonical(diameter=6.0))
        item.update({"record_id": "r-2", "tool_number": None,
                     "code": "C8P2M4WD", "url": "https://x/t/C8P2M4WD"})
        assert render_spec_sheet(
            [item], "qr-specs", "avery-5160").startswith(b"%PDF")

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError):
            render_spec_sheet([_item()], "fancy", "avery-5160")

    def test_unknown_stock_raises(self):
        with pytest.raises(ValueError):
            render_spec_sheet([_item()], "qr-specs", "plaque-99x99")

    def test_start_at_bounds(self):
        with pytest.raises(ValueError):
            render_spec_sheet([_item()], "spec-plaque", "plaque-38x19",
                              start_at=1)

    def test_thermal_4x6_wide_is_4_up_roomy(self):
        items = [_item() for _ in range(5)]
        assert _page_count(
            render_spec_sheet(items, "qr-specs", "thermal-4x6-wide")) == 2

    def test_all_shape_families_render(self):
        # Every recognized profile family, plus an unknown shape, on the
        # roomy layout (the one that draws the silhouette).
        shapes = ("endmill", "ballend", "bullnose", "chamfer", "vbit",
                  "drill", "spotdrill", "countersink", "engraver", "tap",
                  "dovetail", "probe", "slittingsaw", "mystery")
        for shape in shapes:
            item = resolve_spec(_instance_canonical(
                diameter=6.0, length=63.0, shape=shape))
            item.update({"record_id": "r-s", "tool_number": None,
                         "code": "A3F9X7K2", "url": "https://x/t/A3F9X7K2"})
            pdf = render_spec_sheet([item], "qr-specs", "thermal-57x32")
            assert pdf.startswith(b"%PDF"), shape

    def test_probe_and_saw_without_shank_or_loc_render(self):
        # The shape-appropriate defaults kick in when only DIA + OAL exist.
        for shape in ("probe", "slittingsaw"):
            item = resolve_spec(_instance_canonical(
                diameter=2.0 if shape == "probe" else 63.0,
                length=50.0, shape=shape))
            item.update({"record_id": "r-p", "tool_number": None,
                         "code": None, "url": None})
            assert render_spec_sheet(
                [item], "spec-plaque", "plaque-50x25").startswith(b"%PDF")

    def test_all_spec_stocks_render(self):
        for stock in SPEC_STOCKS:
            template = "spec-plaque" if stock.startswith("plaque") \
                else "qr-specs"
            assert render_spec_sheet(
                [_item()], template, stock).startswith(b"%PDF")


class TestExportRows:
    def test_row_shape(self):
        (row,) = export_rows([_item()])
        assert row["oal"] == 63.0
        assert row["loc"] == 19.0
        assert row["tool_number"] == 7
        assert row["code"] == "A3F9X7K2"
        assert row["spec_line"].startswith("Ø6")

    def test_marked_is_flattened(self):
        item = _item()
        item["marked"] = ["diameter", "length"]
        (row,) = export_rows([item])
        assert row["marked"] == "diameter,length"
