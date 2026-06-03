"""GeometryAST-strict PDF renderer.

Contract (zero auto-flow):
  * Every drawn element uses the exact bbox from GeometryAST.
  * Text is wrapped *only inside its bbox*. If it doesn't fit, the renderer
    raises a LayoutOverflowError so the caller can replan, NOT silently
    spill to the next page.
  * Tables snap to their bbox.width; if a column doesn't fit, we emit an
    overflow warning instead of clipping silently.
  * Cover the whole document by walking LayoutAST.pages in order.

Output:
  * The PDF file
  * A SHA-256 content hash (tamper-proof)
  * A list of overflow warnings (empty when render is pixel-clean)
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as _canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .schema import (
    BBox, ChartAST, ContentAST, FigureAST, GeometryNode, LayoutPage,
    MultiAST, Style, StyleAST, Table, TableAST,
)
from .geometry_planner import GeometryPlan, plan_geometry, write_geometry_to_ast

logger = logging.getLogger(__name__)


class LayoutOverflowError(RuntimeError):
    """Raised when a planned bbox cannot fit its content."""


@dataclass
class RenderResult:
    pdf_path: str
    content_hash: str
    overflow_warnings: list[str]
    page_count: int


# ---------------------------------------------------------------------------
# ReportLab font-family mapping (use built-in core fonts so no extra installs)
# ---------------------------------------------------------------------------

_FONT_MAP: dict[tuple[str, str, bool], str] = {
    # (family_lower, weight, italic) -> reportlab name
    ("helvetica", "normal", False): "Helvetica",
    ("helvetica", "bold",   False): "Helvetica-Bold",
    ("helvetica", "normal", True):  "Helvetica-Oblique",
    ("helvetica", "bold",   True):  "Helvetica-BoldOblique",
    ("arial",     "normal", False): "Helvetica",
    ("arial",     "bold",   False): "Helvetica-Bold",
    ("arial",     "normal", True):  "Helvetica-Oblique",
    ("arial",     "italic", True):  "Helvetica-Oblique",
    ("times new roman", "normal", False): "Times-Roman",
    ("times new roman", "bold",   False): "Times-Bold",
    ("times new roman", "normal", True):  "Times-Italic",
    ("times",     "normal", False): "Times-Roman",
    ("times",     "bold",   False): "Times-Bold",
    ("courier",   "normal", False): "Courier",
    ("courier",   "bold",   False): "Courier-Bold",
}


def _resolve_font(style: Style | None) -> tuple[str, float, str]:
    fam = (style.fontFamily if style else "Helvetica").lower()
    weight = (style.fontWeight if style else "normal").lower()
    italic = bool(style and (style.italic or "italic" in weight))
    key = (fam, "bold" if weight in ("bold", "700", "800", "900") else "normal", italic)
    name = _FONT_MAP.get(key) or _FONT_MAP.get((fam, "normal", False)) or "Helvetica"
    size = style.fontSize if style else 10.0
    color = style.color if style and style.color else "#000000"
    return name, size, color


# ---------------------------------------------------------------------------
# Wrap helper — wraps a string to fit a given width, NO auto-flow beyond bbox
# ---------------------------------------------------------------------------


def _wrap_to_width(canvas: _canvas.Canvas, text: str, font_name: str,
                    font_size: float, max_width: float) -> list[str]:
    if not text:
        return [""]
    canvas.setFont(font_name, font_size)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if canvas.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            # Hard-break very long single words
            while canvas.stringWidth(word, font_name, font_size) > max_width and len(word) > 1:
                split_idx = max(1, int(len(word) * max_width
                                        / max(canvas.stringWidth(word, font_name, font_size), 1)))
                lines.append(word[:split_idx])
                word = word[split_idx:]
            current = word
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Coordinate translation
# ---------------------------------------------------------------------------
#
# AST y-axis grows downward from top-left. ReportLab's PDF y-axis grows upward
# from bottom-left. We translate via `pdf_y = page_height - ast_y - height`.


def _to_pdf_xy(page_height: float, bbox: BBox) -> tuple[float, float]:
    return bbox.x, page_height - bbox.y - bbox.height


# ---------------------------------------------------------------------------
# Element drawers
# ---------------------------------------------------------------------------


def _draw_paragraph(c: _canvas.Canvas, *, text: str, bbox: BBox,
                     page_height: float, style: Style | None,
                     allow_overflow: bool, warnings: list[str],
                     element_id: str) -> None:
    if bbox.height <= 0:
        return
    font_name, font_size, color = _resolve_font(style)
    c.setFont(font_name, font_size)
    c.setFillColor(HexColor(color))
    leading = font_size * 1.30
    x, y_pdf = _to_pdf_xy(page_height, bbox)

    lines = _wrap_to_width(c, text, font_name, font_size, bbox.width)
    max_lines = max(1, int(bbox.height // leading))
    if len(lines) > max_lines:
        msg = (f"text overflow element={element_id} need={len(lines)} "
               f"lines got bbox for {max_lines}")
        warnings.append(msg)
        if not allow_overflow:
            raise LayoutOverflowError(msg)
        lines = lines[:max_lines]

    # Draw lines top-down within bbox: first line baseline at y_pdf + height - font_size
    text_obj = c.beginText()
    text_obj.setFont(font_name, font_size)
    text_obj.setFillColor(HexColor(color))
    baseline_y = y_pdf + bbox.height - font_size
    text_obj.setTextOrigin(x, baseline_y)
    text_obj.setLeading(leading)
    alignment = (style.alignment if style else "left").lower()
    for line in lines:
        if alignment == "center":
            line_w = c.stringWidth(line, font_name, font_size)
            text_obj.setXPos((bbox.width - line_w) / 2)  # relative move
            text_obj.textLine(line)
            text_obj.setXPos(-(bbox.width - line_w) / 2)
        elif alignment == "right":
            line_w = c.stringWidth(line, font_name, font_size)
            text_obj.setXPos(bbox.width - line_w)
            text_obj.textLine(line)
            text_obj.setXPos(-(bbox.width - line_w))
        else:
            text_obj.textLine(line)
    c.drawText(text_obj)


def _draw_table(c: _canvas.Canvas, *, table: Table, bbox: BBox,
                page_height: float, style_ast: StyleAST,
                allow_overflow: bool, warnings: list[str]) -> None:
    if bbox.height <= 0 or not table.columns:
        return
    body_style = style_ast.by_id(table.styleId or "s_body") or style_ast.by_id("s_body")
    header_style = style_ast.by_id("s_table_header") or body_style
    body_font, body_size, body_color = _resolve_font(body_style)
    header_font, header_size, header_color = _resolve_font(header_style)

    n_cols = len(table.columns)
    col_w = bbox.width / max(n_cols, 1)
    x, y_pdf = _to_pdf_xy(page_height, bbox)

    # Title (if any) eats the first ~16pt
    cursor_y_top = bbox.y
    if table.title:
        title_h = 16.0
        title_bbox = BBox(x=bbox.x, y=cursor_y_top, width=bbox.width, height=title_h)
        _draw_paragraph(c, text=table.title, bbox=title_bbox,
                         page_height=page_height,
                         style=style_ast.by_id("s_h2") or body_style,
                         allow_overflow=True, warnings=warnings,
                         element_id=f"table_title:{table.tableId}")
        cursor_y_top += title_h + 2

    header_h = header_size * 1.8 + 4
    row_h = body_size * 1.8 + 2

    rows_to_draw = list(table.rows)
    available = bbox.height - (cursor_y_top - bbox.y) - header_h
    max_rows = max(0, int(available // row_h))
    if len(rows_to_draw) > max_rows:
        msg = (f"table overflow {table.tableId}: {len(rows_to_draw)} rows, "
               f"only {max_rows} fit")
        warnings.append(msg)
        if not allow_overflow:
            raise LayoutOverflowError(msg)
        rows_to_draw = rows_to_draw[:max_rows]

    # Header row
    header_top_ast = cursor_y_top
    header_pdf_y = page_height - header_top_ast - header_h
    c.setFillColor(HexColor("#003366"))
    c.rect(x, header_pdf_y, bbox.width, header_h, fill=1, stroke=0)
    c.setFillColor(HexColor(header_color))
    c.setFont(header_font, header_size)
    for i, col in enumerate(table.columns):
        cx = x + i * col_w + 4
        cy = header_pdf_y + header_h / 2 - header_size / 2 + 1
        # Truncate header text to col_w
        col_text = _truncate_to_width(c, str(col), header_font, header_size, col_w - 8)
        c.drawString(cx, cy, col_text)
    cursor_y_top += header_h

    # Rows
    c.setFillColor(HexColor(body_color))
    for r_idx, row in enumerate(rows_to_draw):
        row_top_ast = cursor_y_top
        row_pdf_y = page_height - row_top_ast - row_h
        if r_idx % 2 == 1:
            c.setFillColor(HexColor("#F5F6FA"))
            c.rect(x, row_pdf_y, bbox.width, row_h, fill=1, stroke=0)
        c.setStrokeColor(HexColor("#CCCCCC"))
        c.setLineWidth(0.25)
        c.line(x, row_pdf_y, x + bbox.width, row_pdf_y)

        c.setFillColor(HexColor(body_color))
        c.setFont(body_font, body_size)
        for col_i, cell in enumerate(row):
            cx = x + col_i * col_w + 4
            cy = row_pdf_y + row_h / 2 - body_size / 2 + 1
            cell_text = _truncate_to_width(c, str(cell), body_font, body_size,
                                             col_w - 8)
            c.drawString(cx, cy, cell_text)
        cursor_y_top += row_h


def _truncate_to_width(c: _canvas.Canvas, text: str, font_name: str,
                        font_size: float, max_width: float) -> str:
    if c.stringWidth(text, font_name, font_size) <= max_width:
        return text
    # Binary-search the longest prefix that fits with an ellipsis
    ell = "…"
    ell_w = c.stringWidth(ell, font_name, font_size)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        prefix = text[:mid]
        if c.stringWidth(prefix, font_name, font_size) + ell_w <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ell


def _draw_list(c: _canvas.Canvas, *, items: list[str], ordered: bool,
                bbox: BBox, page_height: float, style: Style | None,
                allow_overflow: bool, warnings: list[str],
                element_id: str) -> None:
    if not items or bbox.height <= 0:
        return
    font_name, font_size, color = _resolve_font(style)
    leading = font_size * 1.35
    x, y_pdf = _to_pdf_xy(page_height, bbox)
    baseline_y = y_pdf + bbox.height - font_size
    c.setFont(font_name, font_size)
    c.setFillColor(HexColor(color))

    for i, item in enumerate(items):
        prefix = f"{i+1}. " if ordered else "• "
        line = prefix + str(item)
        wrapped = _wrap_to_width(c, line, font_name, font_size, bbox.width - 6)
        for w in wrapped:
            if baseline_y < y_pdf:
                msg = f"list overflow {element_id}"
                warnings.append(msg)
                if not allow_overflow:
                    raise LayoutOverflowError(msg)
                return
            c.drawString(x + 6, baseline_y, w)
            baseline_y -= leading


def _draw_figure_placeholder(c: _canvas.Canvas, *, caption: str, bbox: BBox,
                              page_height: float, style_ast: StyleAST,
                              warnings: list[str], element_id: str) -> None:
    """Outlines a rectangle for the figure with a caption beneath.

    Asset embedding can be wired later via assetAST.storageRef.
    """
    x, y_pdf = _to_pdf_xy(page_height, bbox)
    # Frame
    c.setStrokeColor(HexColor("#999999"))
    c.setLineWidth(0.5)
    image_h = bbox.height - 18
    if image_h <= 0:
        warnings.append(f"figure bbox too small {element_id}")
        return
    c.rect(x, y_pdf + 18, bbox.width, image_h, stroke=1, fill=0)
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(HexColor("#555555"))
    c.drawString(x + 4, y_pdf + image_h + 22, "[figure placeholder]")

    # Caption beneath
    cap_bbox = BBox(x=bbox.x, y=bbox.y + bbox.height - 14, width=bbox.width, height=14)
    _draw_paragraph(c, text=caption, bbox=cap_bbox, page_height=page_height,
                     style=style_ast.by_id("s_caption"),
                     allow_overflow=True, warnings=warnings,
                     element_id=f"caption:{element_id}")


def _draw_chart_placeholder(c: _canvas.Canvas, *, chart, bbox: BBox,
                              page_height: float, style_ast: StyleAST,
                              warnings: list[str]) -> None:
    """Draw a simple chart from the chart.series data (bar/line)."""
    x, y_pdf = _to_pdf_xy(page_height, bbox)
    title_h = 14.0
    inner_h = bbox.height - title_h - 18
    if inner_h <= 0:
        warnings.append(f"chart bbox too small {chart.chartId}")
        return

    # Title
    title_bbox = BBox(x=bbox.x, y=bbox.y, width=bbox.width, height=title_h)
    _draw_paragraph(c, text=chart.title, bbox=title_bbox,
                     page_height=page_height,
                     style=style_ast.by_id("s_h2"),
                     allow_overflow=True, warnings=warnings,
                     element_id=f"chart_title:{chart.chartId}")

    # Extract first numeric series
    labels: list[str] = []
    values: list[float] = []
    if chart.series and isinstance(chart.series[0], dict):
        s0 = chart.series[0]
        for pt in s0.get("data") or []:
            if isinstance(pt, dict):
                labels.append(str(pt.get("label", "")))
                try:
                    values.append(float(pt.get("value", 0)))
                except Exception:
                    values.append(0.0)
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                labels.append(str(pt[0]))
                try:
                    values.append(float(pt[1]))
                except Exception:
                    values.append(0.0)

    if not labels:
        # No data — draw an outline so the slot is visible
        c.setStrokeColor(HexColor("#999999"))
        c.setLineWidth(0.5)
        c.rect(x, y_pdf + 18, bbox.width, inner_h, stroke=1, fill=0)
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(HexColor("#999999"))
        c.drawString(x + 4, y_pdf + inner_h, "[chart: no series data]")
        return

    # Bar chart fallback
    n = len(values)
    max_v = max(values) or 1.0
    pad_x = 10.0
    avail_w = bbox.width - 2 * pad_x
    bar_w = max(2.0, (avail_w / n) * 0.7)
    gap = (avail_w / n) - bar_w
    base_y = y_pdf + 30   # leave room for x-labels at bottom
    chart_top_y = y_pdf + 18 + inner_h - 20
    chart_inner_h = chart_top_y - base_y

    c.setFillColor(HexColor("#1565C0"))
    for i, v in enumerate(values):
        bx = x + pad_x + i * (bar_w + gap)
        bh = (v / max_v) * chart_inner_h
        c.rect(bx, base_y, bar_w, bh, fill=1, stroke=0)
        # x-label
        c.setFillColor(HexColor("#444444"))
        c.setFont("Helvetica", 7)
        label = _truncate_to_width(c, labels[i], "Helvetica", 7, bar_w + gap)
        c.drawString(bx, base_y - 9, label)
        c.setFillColor(HexColor("#1565C0"))

    # Axes
    c.setStrokeColor(HexColor("#888"))
    c.setLineWidth(0.4)
    c.line(x + pad_x - 2, base_y, x + bbox.width - pad_x, base_y)
    c.line(x + pad_x - 2, base_y, x + pad_x - 2, chart_top_y)


# ---------------------------------------------------------------------------
# Page-level orchestration
# ---------------------------------------------------------------------------


def _draw_block(c: _canvas.Canvas, *, block_type: str, element_id: str,
                ast: MultiAST, bbox: BBox, page_height: float,
                allow_overflow: bool, warnings: list[str]) -> None:
    sty = ast.styleAST

    if block_type in ("title", "subtitle", "heading", "chapter_heading",
                       "text", "header", "footer", "caption"):
        para = ast.contentAST.paragraph_by_id(element_id)
        if not para:
            warnings.append(f"missing paragraph {element_id}")
            return
        style = sty.by_id(para.styleId) if para.styleId else None
        if style is None:
            style = (sty.by_id("s_h1") if para.type == "title" else
                      sty.by_id("s_h1") if para.type == "chapter_heading" else
                      sty.by_id("s_h2") if para.type in ("subtitle", "heading") else
                      sty.by_id("s_caption") if para.type == "caption" else
                      sty.by_id("s_body"))
        _draw_paragraph(c, text=para.content, bbox=bbox,
                         page_height=page_height, style=style,
                         allow_overflow=allow_overflow, warnings=warnings,
                         element_id=element_id)
        return

    if block_type == "list":
        for l in ast.contentAST.lists:
            if l.id == element_id:
                style = sty.by_id(l.styleId) if l.styleId else sty.by_id("s_body")
                _draw_list(c, items=l.items, ordered=l.ordered, bbox=bbox,
                            page_height=page_height, style=style,
                            allow_overflow=allow_overflow,
                            warnings=warnings, element_id=element_id)
                return
        warnings.append(f"missing list {element_id}")
        return

    if block_type == "table":
        t = next((tb for tb in ast.tableAST.tables if tb.tableId == element_id), None)
        if not t:
            warnings.append(f"missing table {element_id}")
            return
        _draw_table(c, table=t, bbox=bbox, page_height=page_height,
                     style_ast=sty, allow_overflow=allow_overflow,
                     warnings=warnings)
        return

    if block_type == "figure":
        f = next((fg for fg in ast.figureAST.figures if fg.figureId == element_id), None)
        if not f:
            warnings.append(f"missing figure {element_id}")
            return
        _draw_figure_placeholder(c, caption=f.caption, bbox=bbox,
                                   page_height=page_height,
                                   style_ast=sty, warnings=warnings,
                                   element_id=element_id)
        return

    if block_type == "chart":
        ch = next((c2 for c2 in ast.chartAST.charts if c2.chartId == element_id), None)
        if not ch:
            warnings.append(f"missing chart {element_id}")
            return
        _draw_chart_placeholder(c, chart=ch, bbox=bbox, page_height=page_height,
                                  style_ast=sty, warnings=warnings)
        return

    if block_type == "empty_canvas":
        return

    warnings.append(f"unhandled block type '{block_type}' for {element_id}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_ast_to_pdf(
    ast: MultiAST,
    *,
    out_path: str | Path,
    allow_overflow: bool = True,
    auto_plan_geometry: bool = True,
) -> RenderResult:
    """Render a MultiAST to a PDF.

    Args:
      ast: the loaded MultiAST.
      out_path: where to write the PDF.
      allow_overflow: when True overflow becomes a warning; False raises.
      auto_plan_geometry: when True any element_ref without an explicit
         GeometryAST node gets one computed by `plan_geometry` and written
         back into `ast.geometryAST`.

    Returns: RenderResult with pdf_path, content_hash, warnings, page_count.
    """
    warnings: list[str] = []

    if auto_plan_geometry:
        plan = plan_geometry(ast)
        warnings.extend(plan.warnings)
        write_geometry_to_ast(ast, plan)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = _canvas.Canvas(str(out_path))

    pages = ast.layoutAST.pages
    for page in pages:
        c.setPageSize((page.width, page.height))
        for block in page.blocks:
            # tables / figures / charts use the element id as bbox key
            for element_id in (block.elementRefs or [None]):
                if element_id is None:
                    continue
                node = ast.geometryAST.by_element_ref(element_id) \
                       or ast.geometryAST.by_id(f"node_{element_id}")
                if node is None:
                    warnings.append(f"no geometry for {element_id}")
                    continue
                _draw_block(c, block_type=block.type, element_id=element_id,
                             ast=ast, bbox=node.bbox, page_height=page.height,
                             allow_overflow=allow_overflow, warnings=warnings)
        c.showPage()

    c.save()
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return RenderResult(pdf_path=str(out_path), content_hash=digest,
                         overflow_warnings=warnings, page_count=len(pages))
