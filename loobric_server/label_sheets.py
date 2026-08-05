# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""PDF label sheets (docs/LABELS.md): QR + human-readable code on standard
sticker stock.

Server-generated PDF bytes, deliberately: physical alignment on die-cut
stock is the whole job, and browser print margins/scaling can't be trusted
with it. The QR is drawn by iterating segno's module matrix into vector
rects — no raster, no Pillow, crisp at any print DPI.

Assumptions:
- Two stocks cover the field: `avery-5160`-style 30-up US Letter sheets and
  a 57×32 mm thermal roll (one label per page; roll printers feed pages).
- `start_at` skips already-used positions on a partially-used sheet.
- Codes print grouped `ABCD-EFGH`; normalize_code() strips the hyphen back
  out, so the printed form round-trips through human typing.
"""
from io import BytesIO
from urllib.parse import urlparse

import segno
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas

# Stock registry. Geometry in points; grid positions are filled left-to-right,
# top-to-bottom.
STOCKS = {
    "avery-5160": {
        "page": letter,                       # 612 x 792 pt
        "columns": 3, "rows": 10,
        "cell_width": 2.625 * inch, "cell_height": 1.0 * inch,
        "margin_left": 0.19 * inch, "margin_top": 0.5 * inch,
        "pitch_x": 2.75 * inch, "pitch_y": 1.0 * inch,
    },
    "thermal-57x32": {
        "page": (57 * mm, 32 * mm),
        "columns": 1, "rows": 1,
        "cell_width": 57 * mm, "cell_height": 32 * mm,
        "margin_left": 0, "margin_top": 0,
        "pitch_x": 57 * mm, "pitch_y": 32 * mm,
    },
    # A 4x6" adhesive shipping label (thermal, portrait feed) used as a
    # cut-apart sheet: 12 tool-sized stickers per label, 2 x 6 grid of
    # 2" x 1" cells. Cut lines are drawn between cells.
    "thermal-4x6": {
        "page": (4 * inch, 6 * inch),
        "columns": 2, "rows": 6,
        "cell_width": 1.9 * inch, "cell_height": 0.95 * inch,
        "margin_left": 0.1 * inch, "margin_top": 0.1 * inch,
        "pitch_x": 1.9 * inch, "pitch_y": 0.95 * inch,
        "cut_lines": True,
    },
}

_PAD = 4  # inner cell padding, pt


def display_code(code: str) -> str:
    """`ABCD2345` → `ABCD-2345` (readability; normalization strips it)."""
    half = len(code) // 2
    return "%s-%s" % (code[:half], code[half:]) if len(code) > 5 else code


def _draw_qr(c: canvas.Canvas, url: str, x: float, y: float, size: float):
    """Draw the QR for `url` with its lower-left corner at (x, y), scaled to
    fit a `size`-pt square, as vector rects."""
    qr = segno.make(url, error="m")
    modules = len(qr.matrix)
    scale = size / modules
    c.setFillColorRGB(0, 0, 0)
    for row_index, row in enumerate(qr.matrix):
        for col_index, module in enumerate(row):
            if module:
                c.rect(x + col_index * scale,
                       y + size - (row_index + 1) * scale,
                       scale, scale, stroke=0, fill=1)


def _draw_cell(c: canvas.Canvas, stock: dict, position: int,
               code: str, url: str):
    page_width, page_height = stock["page"]
    col = position % stock["columns"]
    row = position // stock["columns"]
    cell_x = stock["margin_left"] + col * stock["pitch_x"]
    cell_y = page_height - stock["margin_top"] - row * stock["pitch_y"] \
        - stock["cell_height"]

    qr_size = stock["cell_height"] - 2 * _PAD
    _draw_qr(c, url, cell_x + _PAD, cell_y + _PAD, qr_size)

    text_x = cell_x + qr_size + 3 * _PAD
    host = urlparse(url).netloc
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Courier-Bold", 11)
    c.drawString(text_x, cell_y + stock["cell_height"] * 0.55,
                 display_code(code))
    c.setFont("Helvetica", 6)
    c.drawString(text_x, cell_y + stock["cell_height"] * 0.32, host)
    c.drawString(text_x, cell_y + stock["cell_height"] * 0.18, "/t/" + code)


def _draw_cut_lines(c: canvas.Canvas, stock: dict):
    """Faint guides between cells for cut-apart stocks (one big adhesive
    label carrying a grid of stickers)."""
    page_width, page_height = stock["page"]
    top = page_height - stock["margin_top"]
    bottom = top - stock["rows"] * stock["pitch_y"]
    left = stock["margin_left"]
    right = left + stock["columns"] * stock["pitch_x"]
    c.setStrokeColorRGB(0.75, 0.75, 0.75)
    c.setLineWidth(0.3)
    for i in range(1, stock["columns"]):
        x = left + i * stock["pitch_x"]
        c.line(x, bottom, x, top)
    for j in range(1, stock["rows"]):
        y = top - j * stock["pitch_y"]
        c.line(left, y, right, y)


def render_sheet(labels, stock_name: str, start_at: int = 0) -> bytes:
    """Render (code, url) pairs onto sticker stock; returns PDF bytes.

    Args:
        labels: iterable of (code, url) tuples
        stock_name: a STOCKS key
        start_at: 0-based grid position to start at on the first page
    """
    if stock_name not in STOCKS:
        raise ValueError("unknown stock %r (have: %s)"
                         % (stock_name, ", ".join(sorted(STOCKS))))
    stock = STOCKS[stock_name]
    per_page = stock["columns"] * stock["rows"]
    if not 0 <= start_at < per_page:
        raise ValueError("start_at must be 0..%d for %s"
                         % (per_page - 1, stock_name))

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=stock["page"])
    if stock.get("cut_lines"):
        _draw_cut_lines(c, stock)
    position = start_at
    for code, url in labels:
        if position >= per_page:
            c.showPage()
            if stock.get("cut_lines"):
                _draw_cut_lines(c, stock)
            position = 0
        _draw_cell(c, stock, position, code, url)
        position += 1
    c.showPage()
    c.save()
    return buffer.getvalue()
