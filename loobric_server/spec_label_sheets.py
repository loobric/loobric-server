# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Spec-label rendering (docs/SPEC_LABELS.md): a printed RENDERING of a
record — specs in ink around the (optional) late-bound QR.

This module is presentation only. It consumes fully-resolved spec items
(built by api/spec_labels.py from the merged instance+catalog view) and
draws them; it never touches the database. Layout follows the validated
spike (Loobric/research/label-spike): compact cells for ~1" sticker
stock, a roomy cell for 57x32mm, and a QR-less plaque painter.

Assumptions:
- Everything here is a SNAPSHOT at print time; staleness is the ratified
  trade (reprint after regrind/rebind), so nothing tries to be clever.
- The `*` marker (measured differs from nominal) rides the formatted
  value, ratified vocabulary (UBIQUITOUS_LANGUAGE.md).
- The silhouette is DERIVED from geometry — never stored media; it draws
  nothing unless DIA and OAL are known, and a plain profile for shapes it
  doesn't recognize.
- Plaque stock sizes are provisional registry data (pending real blank
  dimensions from the users who asked); changing them is not an event.
"""
from io import BytesIO

from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas

from loobric_server.label_sheets import (STOCKS, _draw_cut_lines, _draw_qr,
                                         display_code)

# Canned plaque stocks (docs/SPEC_LABELS.md): one plaque per page, like the
# thermal roll. Provisional sizes — registry data, not schema.
PLAQUE_STOCKS = {
    "plaque-38x19": {
        "page": (38 * mm, 19 * mm), "columns": 1, "rows": 1,
        "cell_width": 38 * mm, "cell_height": 19 * mm,
        "margin_left": 0, "margin_top": 0,
        "pitch_x": 38 * mm, "pitch_y": 19 * mm,
    },
    "plaque-50x25": {
        "page": (50 * mm, 25 * mm), "columns": 1, "rows": 1,
        "cell_width": 50 * mm, "cell_height": 25 * mm,
        "margin_left": 0, "margin_top": 0,
        "pitch_x": 50 * mm, "pitch_y": 25 * mm,
    },
    "plaque-25x25": {
        "page": (25 * mm, 25 * mm), "columns": 1, "rows": 1,
        "cell_width": 25 * mm, "cell_height": 25 * mm,
        "margin_left": 0, "margin_top": 0,
        "pitch_x": 25 * mm, "pitch_y": 25 * mm,
    },
}

SPEC_STOCKS = {**STOCKS, **PLAQUE_STOCKS}

TEMPLATES = ("qr-specs", "spec-plaque")

# A cell at least this tall gets the roomy qr-specs layout (57x32-style
# table + silhouette); shorter cells get the compact one-line layout.
_ROOMY_MIN_HEIGHT = 80  # pt (~28mm; avery/4x6 cells are ~72/68pt)

_PAD = 4  # pt


# ---------------------------------------------------------------------------
# The merged view (docs/SPEC_LABELS.md): instance measured wins over catalog
# nominal; keys where both exist and disagree are MARKED.
# ---------------------------------------------------------------------------

GEOMETRY_KEYS = ("diameter", "flutes", "cutting_edge_height", "length",
                 "shank_diameter", "shape")


def _leaf_value(canonical, path):
    node = canonical or {}
    for part in path.split("."):
        node = node.get(part) or {}
    value = node.get("value") if isinstance(node, dict) else None
    unit = node.get("unit") if isinstance(node, dict) else None
    return value, unit


def _differs(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) > 1e-9
    return a != b


def resolve_spec(instance_canonical, catalog_canonical=None) -> dict:
    """The merged, printable view of one record: measured over nominal,
    with `marked` naming the keys where a present measured value differs
    from a present nominal one."""
    geometry = {}
    marked = []
    unit = None
    for key in GEOMETRY_KEYS:
        measured, m_unit = _leaf_value(instance_canonical, "geometry." + key)
        nominal, n_unit = _leaf_value(catalog_canonical, "geometry." + key)
        value = measured if measured is not None else nominal
        if value is not None:
            geometry[key] = value
        if measured is not None and nominal is not None \
                and _differs(measured, nominal):
            marked.append(key)
        unit = unit or m_unit or n_unit
    name, _ = _leaf_value(instance_canonical, "name")
    if name is None:
        name, _ = _leaf_value(catalog_canonical, "name")
    manufacturer, _ = _leaf_value(catalog_canonical, "manufacturer")
    return {
        "name": name,
        "manufacturer": manufacturer,
        "unit": unit,
        "geometry": geometry,
        "marked": marked,
    }


# ---------------------------------------------------------------------------
# Formatting (ratified: decimal as stored; `*` = measured differs)
# ---------------------------------------------------------------------------

def _fmt(value, unit):
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    text = ("%.4f" if unit == "in" else "%.2f") % value
    return text.rstrip("0").rstrip(".")


def _value(item, key):
    text = _fmt(item["geometry"].get(key), item.get("unit"))
    return text + "*" if key in item.get("marked", ()) else text


def spec_line(item, include_unit=True, compact=False) -> str:
    """`Ø5.92* · 4FL · LOC 19 · OAL 63  (mm)` — the one-line spec string.
    compact=True tightens separators for the smallest stock."""
    geometry = item["geometry"]
    parts = ["Ø%s" % _value(item, "diameter")]
    if geometry.get("flutes") is not None:
        parts.append("%sFL" % _value(item, "flutes"))
    if geometry.get("cutting_edge_height") is not None:
        parts.append("LOC %s" % _value(item, "cutting_edge_height"))
    if geometry.get("length") is not None:
        parts.append("OAL %s" % _value(item, "length"))
    sep = "·" if compact else " · "
    unit = item.get("unit")
    suffix = "  (%s)" % unit if include_unit and unit else ""
    return sep.join(parts) + suffix


# ---------------------------------------------------------------------------
# Derived silhouette: side profile, shank left, cutting edge right.
# ---------------------------------------------------------------------------

def _draw_silhouette(c, item, x, y, box_w, box_h):
    geometry = item["geometry"]
    oal = geometry.get("length")
    dia = geometry.get("diameter")
    if not oal or not dia:
        return
    loc = geometry.get("cutting_edge_height") or oal * 0.3
    shank_d = geometry.get("shank_diameter") or dia
    scale = min(box_w / oal, box_h / max(dia, shank_d))
    cy = y + box_h / 2.0
    x0 = x + (box_w - oal * scale) / 2.0
    shank_len, shank_h = (oal - loc) * scale, shank_d * scale
    flute_len, flute_h = loc * scale, dia * scale

    c.saveState()
    c.setLineWidth(0.4)
    c.setStrokeColorRGB(0.15, 0.15, 0.15)
    c.setFillColorRGB(0.85, 0.85, 0.85)
    c.rect(x0, cy - shank_h / 2, shank_len, shank_h, stroke=1, fill=1)

    fx = x0 + shank_len
    c.setFillColorRGB(0.55, 0.55, 0.55)
    shape = item["geometry"].get("shape")
    if shape == "ballend" and flute_len > flute_h / 2:
        r = flute_h / 2.0
        p = c.beginPath()
        p.moveTo(fx, cy - r)
        p.lineTo(fx + flute_len - r, cy - r)
        p.arcTo(fx + flute_len - 2 * r, cy - r, fx + flute_len, cy + r,
                startAng=270, extent=180)
        p.lineTo(fx, cy + r)
        p.close()
        c.drawPath(p, stroke=1, fill=1)
    elif shape in ("chamfer", "vbit", "drill", "spotdrill") \
            and flute_len > flute_h / 2:
        p = c.beginPath()
        p.moveTo(fx, cy - flute_h / 2)
        p.lineTo(fx + flute_len - flute_h / 2, cy - flute_h / 2)
        p.lineTo(fx + flute_len, cy)
        p.lineTo(fx + flute_len - flute_h / 2, cy + flute_h / 2)
        p.lineTo(fx, cy + flute_h / 2)
        p.close()
        c.drawPath(p, stroke=1, fill=1)
    else:  # square endmill and anything unrecognized: plain profile
        c.rect(fx, cy - flute_h / 2, flute_len, flute_h, stroke=1, fill=1)

    c.setStrokeColorRGB(0.95, 0.95, 0.95)
    c.setLineWidth(0.5)
    flutes = geometry.get("flutes")
    n = int(flutes) if isinstance(flutes, (int, float)) and flutes else 2
    body = flute_len * (0.85 if shape == "ballend" else 1.0)
    for i in range(1, n + 1):
        lx = fx + body * i / (n + 1)
        c.line(lx, cy - flute_h / 2 + 0.6, lx + flute_h * 0.5,
               cy + flute_h / 2 - 0.6)
    c.restoreState()


# ---------------------------------------------------------------------------
# Cell painters
# ---------------------------------------------------------------------------

def _truncate(c, text, font, size, max_w):
    while c.stringWidth(text, font, size) > max_w and len(text) > 4:
        text = text[:-2] + "…"
    return text


def _cell_origin(stock, position):
    page_height = stock["page"][1]
    col = position % stock["columns"]
    row = position // stock["columns"]
    x = stock["margin_left"] + col * stock["pitch_x"]
    y = page_height - stock["margin_top"] - row * stock["pitch_y"] \
        - stock["cell_height"]
    return x, y


def _paint_qr_specs_compact(c, stock, position, item):
    x, y = _cell_origin(stock, position)
    w, h = stock["cell_width"], stock["cell_height"]
    qr = h - 2 * _PAD
    _draw_qr(c, item["url"], x + _PAD, y + _PAD, qr)
    tx = x + qr + 2.5 * _PAD
    tw = w - qr - 3.5 * _PAD
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawString(tx, y + h - 12, _truncate(
        c, item.get("name") or "(unnamed)", "Helvetica-Bold", 6.5, tw))
    c.setFont("Helvetica", 6)
    c.drawString(tx, y + h - 22,
                 _truncate(c, spec_line(item), "Helvetica", 6, tw))
    c.setFont("Courier", 5.5)
    c.drawString(tx, y + 6, display_code(item["code"]))
    if item.get("tool_number") is not None:
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(x + w - _PAD, y + 6, "T%s" % item["tool_number"])


def _paint_qr_specs_roomy(c, stock, position, item):
    x, y = _cell_origin(stock, position)
    w, h = stock["cell_width"], stock["cell_height"]
    qr = min(16 * mm, h - 12 * mm)
    _draw_qr(c, item["url"], x + w - qr - 2 * mm, y + h - qr - 2 * mm, qr)
    tx = x + 2.5 * mm
    tw = w - qr - 5 * mm
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(tx, y + h - 5 * mm, _truncate(
        c, item.get("name") or "(unnamed)", "Helvetica-Bold", 8, tw))
    if item.get("manufacturer"):
        c.setFont("Helvetica", 6)
        c.drawString(tx, y + h - 8 * mm,
                     _truncate(c, item["manufacturer"], "Helvetica", 6, tw))
    ry = y + h - 12.5 * mm
    for abbrev, key in (("DIA", "diameter"), ("FL", "flutes"),
                        ("LOC", "cutting_edge_height"), ("OAL", "length")):
        c.setFont("Helvetica", 6.5)
        c.drawString(tx, ry, abbrev)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(tx + 8 * mm, ry, _value(item, key))
        ry -= 3.2 * mm
    if item.get("unit"):
        c.setFont("Helvetica", 5.5)
        c.drawString(tx, ry, "(%s)" % item["unit"])
    if item.get("tool_number") is not None:
        c.setFont("Helvetica-Bold", 16)
        c.drawRightString(x + w - 2.5 * mm, y + 2.5 * mm,
                          "T%s" % item["tool_number"])
    c.setFont("Courier", 5.5)
    c.drawString(tx, y + 2 * mm, display_code(item["code"]))
    _draw_silhouette(c, item, tx + 16 * mm, y + 4.5 * mm, 22 * mm, 9 * mm)


def _paint_plaque(c, stock, position, item):
    x, y = _cell_origin(stock, position)
    w, h = stock["cell_width"], stock["cell_height"]
    c.setFillColorRGB(0, 0, 0)
    if item.get("tool_number") is not None:
        c.setFont("Helvetica-Bold", 15)
        c.drawString(x + 1.5 * mm, y + h - 6.5 * mm,
                     "T%s" % item["tool_number"])
        tx = x + 11 * mm
    else:
        tx = x + 1.5 * mm
    c.setFont("Helvetica-Bold", 6)
    c.drawString(tx, y + h - 4 * mm, _truncate(
        c, item.get("name") or "(unnamed)", "Helvetica-Bold", 6,
        x + w - tx - 1.5 * mm))
    # Ratified fit finding: the smallest plaque only fits the full spec
    # line compacted with the unit suffix dropped.
    c.setFont("Helvetica", 5.5)
    c.drawString(tx, y + h - 6.8 * mm, _truncate(
        c, spec_line(item, include_unit=False, compact=True),
        "Helvetica", 5.5, x + w - tx - 1.5 * mm))
    _draw_silhouette(c, item, x + 1.5 * mm, y + 1.5 * mm,
                     w - 3 * mm, h - 11 * mm)


def _painter(template: str, stock: dict):
    if template == "spec-plaque":
        return _paint_plaque
    if stock["cell_height"] >= _ROOMY_MIN_HEIGHT:
        return _paint_qr_specs_roomy
    return _paint_qr_specs_compact


# ---------------------------------------------------------------------------
# Sheet rendering & export rows
# ---------------------------------------------------------------------------

def render_spec_sheet(items, template: str, stock_name: str,
                      start_at: int = 0) -> bytes:
    """Render resolved spec items (dicts from resolve_spec, plus
    tool_number and — for QR templates — code/url) onto stock."""
    if template not in TEMPLATES:
        raise ValueError("unknown template %r (have: %s)"
                         % (template, ", ".join(TEMPLATES)))
    if stock_name not in SPEC_STOCKS:
        raise ValueError("unknown stock %r (have: %s)"
                         % (stock_name, ", ".join(sorted(SPEC_STOCKS))))
    stock = SPEC_STOCKS[stock_name]
    per_page = stock["columns"] * stock["rows"]
    if not 0 <= start_at < per_page:
        raise ValueError("start_at must be 0..%d for %s"
                         % (per_page - 1, stock_name))
    paint = _painter(template, stock)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=stock["page"])
    if stock.get("cut_lines"):
        _draw_cut_lines(c, stock)
    position = start_at
    for item in items:
        if position >= per_page:
            c.showPage()
            if stock.get("cut_lines"):
                _draw_cut_lines(c, stock)
            position = 0
        paint(c, stock, position, item)
        position += 1
    c.showPage()
    c.save()
    return buffer.getvalue()


EXPORT_COLUMNS = ("record_id", "name", "manufacturer", "code", "url",
                  "tool_number", "unit", "diameter", "flutes", "loc", "oal",
                  "shank_diameter", "shape", "marked", "spec_line")


def export_rows(items) -> list[dict]:
    """Flat rows for the bring-your-own-layout escape hatch (json/csv):
    everything the canned templates would print, resolved and merged."""
    rows = []
    for item in items:
        geometry = item["geometry"]
        rows.append({
            "record_id": item.get("record_id"),
            "name": item.get("name"),
            "manufacturer": item.get("manufacturer"),
            "code": item.get("code"),
            "url": item.get("url"),
            "tool_number": item.get("tool_number"),
            "unit": item.get("unit"),
            "diameter": geometry.get("diameter"),
            "flutes": geometry.get("flutes"),
            "loc": geometry.get("cutting_edge_height"),
            "oal": geometry.get("length"),
            "shank_diameter": geometry.get("shank_diameter"),
            "shape": geometry.get("shape"),
            "marked": ",".join(item.get("marked", [])),
            "spec_line": spec_line(item),
        })
    return rows
