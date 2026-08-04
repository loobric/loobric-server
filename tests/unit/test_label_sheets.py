# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for PDF label sheets (loobric_server/label_sheets.py)."""
import pytest

from loobric_server.label_codes import normalize_code
from loobric_server.label_sheets import STOCKS, display_code, render_sheet


def _labels(n):
    return [("CODE%04d" % i, "https://shop.example/t/CODE%04d" % i)
            for i in range(n)]


def _page_count(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


class TestRender:
    def test_pdf_magic(self):
        assert render_sheet(_labels(1), "avery-5160").startswith(b"%PDF")

    def test_avery_sheet_is_30_up(self):
        assert _page_count(render_sheet(_labels(30), "avery-5160")) == 1
        assert _page_count(render_sheet(_labels(31), "avery-5160")) == 2

    def test_thermal_is_one_per_page(self):
        assert _page_count(render_sheet(_labels(5), "thermal-57x32")) == 5

    def test_start_at_reduces_first_page_capacity(self):
        # 25 labels from position 10 on a 30-up sheet → 20 fit, 5 spill.
        assert _page_count(
            render_sheet(_labels(25), "avery-5160", start_at=10)) == 2

    def test_unknown_stock_raises(self):
        with pytest.raises(ValueError):
            render_sheet(_labels(1), "avery-9999")

    def test_start_at_bounds(self):
        with pytest.raises(ValueError):
            render_sheet(_labels(1), "avery-5160", start_at=30)
        with pytest.raises(ValueError):
            render_sheet(_labels(1), "thermal-57x32", start_at=1)


class TestDisplayCode:
    def test_grouped_for_readability(self):
        assert display_code("ABCD2345") == "ABCD-2345"

    def test_round_trips_through_normalization(self):
        assert normalize_code(display_code("ABCD2345")) == "ABCD2345"

    def test_short_codes_ungrouped(self):
        assert display_code("ABC23") == "ABC23"


class TestStocks:
    @pytest.mark.parametrize("name", sorted(STOCKS))
    def test_grid_fits_on_page(self, name):
        s = STOCKS[name]
        page_width, page_height = s["page"]
        width_needed = s["margin_left"] + (s["columns"] - 1) * s["pitch_x"] \
            + s["cell_width"]
        height_needed = s["margin_top"] + (s["rows"] - 1) * s["pitch_y"] \
            + s["cell_height"]
        assert width_needed <= page_width + 0.5
        assert height_needed <= page_height + 0.5
