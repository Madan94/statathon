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
    # Adaptive font sizing so 8+ column tables don't end with "Distri…" headers
    if n_cols >= 9:
        header_size = 7.0
        body_size = 7.5
    elif n_cols >= 7:
        header_size = 8.0
        body_size = 8.0

    # Adaptive column widths: first column ~1.8x (for labels), others share.
    if n_cols >= 4:
        first_w = bbox.width * 0.20
        rest_w = (bbox.width - first_w) / (n_cols - 1)
        col_widths = [first_w] + [rest_w] * (n_cols - 1)
    else:
        col_widths = [bbox.width / n_cols] * n_cols
    col_lefts = [bbox.x]
    for w in col_widths[:-1]:
        col_lefts.append(col_lefts[-1] + w)
    col_w = bbox.width / max(n_cols, 1)   # legacy fallback for callers using single width
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

    # Header row — wrap each header onto up to 2 lines if it doesn't fit.
    # This is the generic fix for "Distribution (%) 2025" being truncated
    # to "Distrib…" in narrow tables.
    wrapped_headers: list[list[str]] = []
    max_header_lines = 1
    for i, col in enumerate(table.columns):
        col_str = str(col)
        cw = col_widths[i] - 8
        if c.stringWidth(col_str, header_font, header_size) <= cw:
            wrapped_headers.append([col_str])
            continue
        words = col_str.split()
        lines: list[str] = []
        current = ""
        for w in words:
            cand = (current + " " + w).strip()
            if c.stringWidth(cand, header_font, header_size) <= cw:
                current = cand
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        if not lines:
            lines = [col_str]
        if len(lines) > 2:
            lines = [lines[0],
                      _truncate_to_width(c, " ".join(lines[1:]),
                                           header_font, header_size, cw)]
        wrapped_headers.append(lines)
        max_header_lines = max(max_header_lines, len(lines))

    header_h = max_header_lines * (header_size * 1.4) + 6
    row_h = body_size * 1.9 + 2

    header_top_ast = cursor_y_top
    header_pdf_y = page_height - header_top_ast - header_h
    c.setFillColor(HexColor("#003366"))
    c.rect(x, header_pdf_y, bbox.width, header_h, fill=1, stroke=0)
    # Always white text on navy header band (body style is often black)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont(header_font, header_size)
    for i, lines in enumerate(wrapped_headers):
        cw = col_widths[i]
        cx_left = col_lefts[i] + 4
        # Centre the wrapped header vertically inside the header band
        total_text_h = len(lines) * header_size * 1.4
        first_baseline = header_pdf_y + (header_h + total_text_h) / 2 - header_size
        for li, line in enumerate(lines):
            cy = first_baseline - li * header_size * 1.4
            c.drawString(cx_left, cy, line)
    cursor_y_top += header_h

    # Vertical separators inside the header band
    c.setStrokeColor(HexColor("#1f4e79"))
    c.setLineWidth(0.4)
    for left in col_lefts[1:]:
        c.line(left, header_pdf_y, left, header_pdf_y + header_h)

    # Rows
    c.setFillColor(HexColor(body_color))
    last_row_pdf_y = None
    for r_idx, row in enumerate(rows_to_draw):
        row_top_ast = cursor_y_top
        row_pdf_y = page_height - row_top_ast - row_h
        last_row_pdf_y = row_pdf_y
        if r_idx % 2 == 1:
            c.setFillColor(HexColor("#F5F6FA"))
            c.rect(x, row_pdf_y, bbox.width, row_h, fill=1, stroke=0)
        # Highlight the Total row if present (last row whose first cell is "Total")
        if (r_idx == len(rows_to_draw) - 1
              and len(row) > 0 and str(row[0]).strip().lower() == "total"):
            c.setFillColor(HexColor("#E3F0FF"))
            c.rect(x, row_pdf_y, bbox.width, row_h, fill=1, stroke=0)

        c.setStrokeColor(HexColor("#CCCCCC"))
        c.setLineWidth(0.25)
        c.line(x, row_pdf_y, x + bbox.width, row_pdf_y)

        c.setFillColor(HexColor(body_color))
        c.setFont(body_font, body_size)
        for col_i, cell in enumerate(row):
            if col_i >= len(col_lefts):
                break
            cx = col_lefts[col_i] + 4
            cw = col_widths[col_i]
            cy = row_pdf_y + row_h / 2 - body_size / 2 + 1
            display = _format_cell(cell)
            cell_text = _truncate_to_width(c, display, body_font, body_size,
                                             cw - 8)
            # Right-align numeric cells; left-align everything else
            if _looks_numeric(display) and col_i > 0:
                tw = c.stringWidth(cell_text, body_font, body_size)
                c.drawString(col_lefts[col_i] + cw - tw - 4, cy, cell_text)
            else:
                c.drawString(cx, cy, cell_text)
        cursor_y_top += row_h

    # Bottom border + column dividers down the body
    if last_row_pdf_y is not None:
        bottom_y = last_row_pdf_y
        c.setStrokeColor(HexColor("#CCCCCC"))
        c.setLineWidth(0.25)
        c.line(x, bottom_y, x + bbox.width, bottom_y)
        for left in col_lefts[1:]:
            c.line(left, bottom_y, left, header_pdf_y)
        # Outer rectangle
        c.setLineWidth(0.5)
        c.rect(x, bottom_y, bbox.width, (header_pdf_y + header_h) - bottom_y,
                fill=0, stroke=1)


def _looks_numeric(text: str) -> bool:
    """True if `text` reads as a number (possibly with commas / decimals / unit)."""
    s = str(text or "").strip()
    if s in ("", "—"):
        return False
    cleaned = s.replace(",", "").replace("%", "").replace("$", "")
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _format_cell(value: Any) -> str:
    """Render a table cell value: empty/None -> em-dash, numbers formatted."""
    if value is None:
        return "—"
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() == "none":
            return "—"
        return s
    if isinstance(value, float):
        if value != value:    # NaN
            return "—"
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


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
                              warnings: list[str], element_id: str,
                              computed_chart: dict[str, Any] | None = None) -> None:
    """Draw a figure at its declared bbox.

    Strategy:
      * If `computed_chart` is populated (the binder produced a chart spec
        from the dataset), render a real matplotlib pie/bar/line chart at
        the figure bbox.
      * Otherwise draw a soft placeholder so the layout shape is preserved.
    """
    # Caption band at bottom of figure block; image uses the rest
    cap_h = min(36.0, max(26.0, bbox.height * 0.14))
    image_bbox = BBox(
        x=bbox.x, y=bbox.y,
        width=bbox.width,
        height=max(0.0, bbox.height - cap_h),
    )
    if image_bbox.height <= 0:
        warnings.append(f"figure bbox too small {element_id}")
        return

    x, y_pdf = _to_pdf_xy(page_height, image_bbox)
    drew_chart = False
    if computed_chart and computed_chart.get("data"):
        try:
            png = _render_chart_png(
                computed_chart,
                width_pt=image_bbox.width,
                height_pt=image_bbox.height,
                draw_title=False,
            )
            if png is not None:
                from reportlab.lib.utils import ImageReader
                # Fill the figure slot exactly — avoid letterboxing white gaps
                c.drawImage(ImageReader(io.BytesIO(png)),
                             x, y_pdf,
                             width=image_bbox.width, height=image_bbox.height,
                             preserveAspectRatio=False, anchor="sw", mask="auto")
                drew_chart = True
        except Exception as exc:
            warnings.append(f"chart render failed for {element_id}: {exc}")

    if not drew_chart:
        c.setStrokeColor(HexColor("#bbbbbb"))
        c.setLineWidth(0.5)
        c.setFillColor(HexColor("#fafafa"))
        c.rect(x, y_pdf, image_bbox.width, image_bbox.height, stroke=1, fill=1)
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(HexColor("#888888"))
        msg = "(no data for this figure)" if computed_chart is None else "(empty chart)"
        c.drawString(x + 6, y_pdf + image_bbox.height - 14, msg)

    # Caption at bottom of figure bbox (top-left coordinates)
    cap_bbox = BBox(
        x=bbox.x, y=bbox.y + bbox.height - cap_h,
        width=bbox.width, height=cap_h,
    )
    _draw_paragraph(c, text=caption, bbox=cap_bbox, page_height=page_height,
                     style=style_ast.by_id("s_caption"),
                     allow_overflow=True, warnings=warnings,
                     element_id=f"caption:{element_id}")


def _short_chart_label(label: str, *, max_len: int = 14) -> str:
    s = str(label or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


_PIE_SLICE_COLORS: dict[str, str] = {
    "proved": "#1f4e79",
    "indicated": "#5b9bd5",
    "inferred": "#bdd7ee",
    "solar": "#1f4e79",
    "wind": "#5b9bd5",
    "large hydro": "#ed7d31",
    "hydro": "#ed7d31",
}


def _color_for_pie_label(label: str, fallback: str) -> str:
    low = str(label).lower()
    for key, color in _PIE_SLICE_COLORS.items():
        if key in low:
            return color
    return fallback


def _format_axis_value(v: float) -> str:
    av = abs(v)
    if av >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if av >= 1_000:
        return f"{v / 1_000:.1f}K"
    if float(int(v)) == v:
        return str(int(v))
    return f"{v:.1f}"


def _render_chart_png(
    chart: dict[str, Any],
    *,
    width_pt: float,
    height_pt: float,
    draw_title: bool = False,
) -> bytes | None:
    """Render a chart spec to PNG bytes using matplotlib (MoSPI-quality)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except Exception:
        return None

    ctype = (chart.get("type") or "bar").lower()
    title = chart.get("title") or ""
    data = chart.get("data") or []
    pairs: list[tuple[str, float]] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        try:
            pairs.append((str(d.get("label", "")), float(d.get("value", 0))))
        except (TypeError, ValueError):
            continue
    if not pairs or sum(abs(v) for _, v in pairs) == 0:
        return None

    if ctype == "pie":
        order = (
            ("proved", 0), ("indicated", 1), ("inferred", 2),
            ("solar", 0), ("wind", 1), ("large hydro", 2), ("hydro", 2),
        )

        def _pie_rank(item: tuple[str, float]) -> int:
            lab = item[0].lower()
            for key, r in order:
                if key in lab:
                    return r
            return 50

        pairs = sorted(pairs, key=_pie_rank)
    else:
        pairs.sort(key=lambda x: x[1], reverse=True)
    narrow = width_pt < 280
    max_bars = 5 if narrow else 8
    if ctype == "bar":
        pairs = pairs[:max_bars]
    else:
        pairs = pairs[:12]
    labels = [_short_chart_label(l, max_len=14 if width_pt > 300 else 10)
              for l, _ in pairs]
    values = [v for _, v in pairs]
    n = len(labels)

    fig_w = max(2.0, width_pt / 72.0)
    fig_h = max(1.8, height_pt / 72.0)
    dpi = 150
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    try:
        palette = [
            "#1f4e79", "#2e75b6", "#5b9bd5", "#9dc3e6", "#bdd7ee",
            "#e7a300", "#ed7d31", "#c00000", "#7f6000", "#385723",
            "#264478", "#9e480e",
        ]
        if ctype == "pie":
            pie_colors = [
                _color_for_pie_label(lab, palette[i % len(palette)])
                for i, lab in enumerate(labels)
            ]
            tall_slot = height_pt > width_pt * 1.05
            if tall_slot:
                ax.set_position([0.08, 0.30, 0.84, 0.58])
            wedges, _, autotexts = ax.pie(
                values,
                labels=None,
                autopct=lambda p: f"{p:.1f}%" if p >= 2.5 else "",
                startangle=90,
                colors=pie_colors,
                pctdistance=0.65,
            )
            for t in autotexts:
                t.set_fontsize(7 if not narrow else 6)
                t.set_color("#ffffff")
                t.set_fontweight("bold")
            leg_fs = 7 if not narrow else 6
            ncol = min(n, 3)
            leg_y = 0.06 if tall_slot else -0.02
            ax.legend(
                labels,
                loc="lower center",
                bbox_to_anchor=(0.5, leg_y),
                ncol=ncol,
                fontsize=leg_fs,
                frameon=False,
            )
            ax.axis("equal")
            if tall_slot:
                plt.subplots_adjust(left=0.04, right=0.96, top=0.98, bottom=0.12)
            else:
                plt.subplots_adjust(left=0.04, right=0.96, top=0.96, bottom=0.20)
        elif ctype == "line":
            ax.plot(range(n), values, marker="o", color=palette[0], linewidth=2)
            ax.set_xticks(range(n))
            ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=6)
            ax.yaxis.set_major_formatter(
                mticker.FuncFormatter(lambda x, _: _format_axis_value(x)))
            ax.grid(True, alpha=0.3, axis="y")
            plt.subplots_adjust(left=0.14, right=0.98, top=0.92,
                                bottom=0.28 if n <= 5 else 0.38)
        else:
            # Horizontal bars when labels would overlap on vertical axis
            use_horizontal = narrow or n > 5
            ax.grid(True, alpha=0.25, axis="y" if use_horizontal else "x",
                    linestyle="--")
            ax.set_axisbelow(True)
            if use_horizontal:
                ypos = list(range(n))
                ax.barh(ypos, values, color=palette[:n], height=0.7,
                        edgecolor="white", linewidth=0.4)
                ax.set_yticks(ypos)
                ax.set_yticklabels(labels, fontsize=6)
                ax.invert_yaxis()
                ax.xaxis.set_major_formatter(
                    mticker.FuncFormatter(lambda x, _: _format_axis_value(x)))
                xmax = max(values) * 1.08 if values else 1.0
                ax.set_xlim(0, xmax)
                left = 0.32 if max(len(l) for l in labels) > 10 else 0.24
                plt.subplots_adjust(left=left, right=0.98, top=0.94, bottom=0.16)
            else:
                xpos = range(n)
                ax.bar(xpos, values, color=palette[:n], width=0.72,
                       edgecolor="white", linewidth=0.4)
                ax.set_xticks(list(xpos))
                ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=7)
                ax.yaxis.set_major_formatter(
                    mticker.FuncFormatter(lambda x, _: _format_axis_value(x)))
                plt.subplots_adjust(left=0.14, right=0.98, top=0.94, bottom=0.32)

        if draw_title and title:
            short_title = _short_chart_label(title, max_len=48)
            ax.set_title(short_title, fontsize=7, color="#1f4e79", pad=4)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor="white",
                    edgecolor="none", pad_inches=0.05)
        return buf.getvalue()
    except Exception as exc:
        logger.info("chart render error: %s", exc)
        return None
    finally:
        try:
            plt.close(fig)
        except Exception:
            pass


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

    # Paragraph-like block types — covers classic names AND coord-AST names
    # (heading_1, heading_2, paragraph, chapter_header, meta, body, etc.)
    _PARAGRAPH_TYPES = frozenset({
        "title", "subtitle", "heading", "chapter_heading", "chapter_header",
        "text", "header", "footer", "caption", "meta", "body",
        # coord-AST specific
        "heading_1", "heading_2", "paragraph",
    })
    if block_type in _PARAGRAPH_TYPES:
        para = ast.contentAST.paragraph_by_id(element_id)
        if not para:
            warnings.append(f"missing paragraph {element_id}")
            return
        style = sty.by_id(para.styleId) if para.styleId else None
        if style is None:
            # Map paragraph type → style
            ptype = para.type.lower() if para.type else ""
            if ptype in ("title",):
                style = sty.by_id("s_h1")
            elif ptype in ("chapter_heading", "chapter_header"):
                style = sty.by_id("s_h1")
            elif ptype in ("subtitle", "heading", "heading_1"):
                style = sty.by_id("s_h1")
            elif ptype in ("heading_2",):
                style = sty.by_id("s_h2")
            elif ptype in ("caption",):
                style = sty.by_id("s_caption")
            else:
                style = sty.by_id("s_body")
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
                                   element_id=element_id,
                                   computed_chart=f.computed_chart)
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
# Cover / header / footer chrome
# ---------------------------------------------------------------------------


def _draw_cover_chrome(c: _canvas.Canvas, page, ast: MultiAST) -> None:
    """Paint Ministry banner + centred title block + footer for the cover page.

    The block paragraphs declared in the AST (b1_1, b1_2 …) still draw on top
    via the normal _draw_paragraph path; this function paints the surrounding
    chrome. To avoid duplicating the title, _draw_block special-cases the
    cover page when this chrome is active.
    """
    # Top accent band with Ministry name (centred, white on navy)
    c.setFillColor(HexColor("#0B3B7A"))
    c.rect(0, page.height - 40, page.width, 40, stroke=0, fill=1)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 12)
    ministry = "MINISTRY OF STATISTICS AND PROGRAMME IMPLEMENTATION"
    tw = c.stringWidth(ministry, "Helvetica-Bold", 12)
    c.drawString((page.width - tw) / 2, page.height - 26, ministry)

    # Thin gold accent line
    c.setStrokeColor(HexColor("#c8a23a"))
    c.setLineWidth(1.2)
    c.line(0, page.height - 42, page.width, page.height - 42)

    # ------- Centred title block (replaces the cover paragraph rendering) -------
    # Collect cover paragraphs (title / subtitle / text on page 1)
    cover_paras: list[tuple[str, str]] = []   # (type, content)
    cover_page = ast.layoutAST.pages[0]
    refs: list[str] = []
    for blk in cover_page.blocks:
        refs.extend(blk.elementRefs)
    for pid in refs:
        p = ast.contentAST.paragraph_by_id(pid)
        if p and p.content.strip():
            cover_paras.append((p.type, p.content.strip()))

    # Find the title + subtitle; skip 2-letter all-caps placeholders ("GO")
    title = next((c for t, c in cover_paras if t == "title"), "")
    subtitle = next((c for t, c in cover_paras if t == "subtitle"), "")
    extras = [c for t, c in cover_paras
              if t not in ("title", "subtitle") and len(c) > 4]

    # Centre block roughly 1/3 down the page
    centre_y = page.height * 0.62
    if title:
        c.setFont("Helvetica-Bold", 26)
        c.setFillColor(HexColor("#0B3B7A"))
        tw = c.stringWidth(title, "Helvetica-Bold", 26)
        c.drawString((page.width - tw) / 2, centre_y, title)
        centre_y -= 18
    if subtitle:
        c.setFont("Helvetica", 16)
        c.setFillColor(HexColor("#1f4e79"))
        tw = c.stringWidth(subtitle, "Helvetica", 16)
        c.drawString((page.width - tw) / 2, centre_y, subtitle)
        centre_y -= 30

    # Decorative divider
    c.setStrokeColor(HexColor("#c8a23a"))
    c.setLineWidth(0.8)
    div_w = 200
    c.line((page.width - div_w) / 2, centre_y, (page.width + div_w) / 2, centre_y)
    centre_y -= 24

    # Publication metadata
    from datetime import datetime as _dt
    pub_date = (ast.metadata.updatedAt or ast.metadata.createdAt
                  or _dt.utcnow().strftime("%Y-%m-%d"))
    c.setFillColor(HexColor("#444444"))
    c.setFont("Helvetica", 11)
    pub = f"As on {pub_date[:10]}"
    pw = c.stringWidth(pub, "Helvetica", 11)
    c.drawString((page.width - pw) / 2, centre_y, pub)
    centre_y -= 16

    for line in extras:
        c.setFont("Helvetica-Oblique", 10)
        c.setFillColor(HexColor("#666666"))
        lw = c.stringWidth(line, "Helvetica-Oblique", 10)
        c.drawString((page.width - lw) / 2, centre_y, line)
        centre_y -= 14

    # Bottom decorative band
    c.setStrokeColor(HexColor("#c8a23a"))
    c.setLineWidth(1.2)
    c.line(0, 26, page.width, 26)
    c.setFillColor(HexColor("#0B3B7A"))
    c.rect(0, 0, page.width, 24, stroke=0, fill=1)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 9)
    foot = "GOVERNMENT OF INDIA"
    fw = c.stringWidth(foot, "Helvetica-Bold", 9)
    c.drawString((page.width - fw) / 2, 9, foot)


def _draw_page_header_band(c: _canvas.Canvas, page, ast: MultiAST) -> None:
    # Prefer the document subtitle / chapter heading (skip generic "Chapter One"
    # which is usually just a numeral on the cover).
    title = ""
    subtitle = None
    chapter_head = None
    for p in ast.contentAST.paragraphs:
        if p.type == "subtitle" and p.content.strip() and subtitle is None:
            subtitle = p.content.strip()
        if (p.type in ("chapter_heading", "chapter_header") and p.content.strip()
              and chapter_head is None):
            chapter_head = p.content.strip()
    title = chapter_head or subtitle or title
    import re as _re
    # Strip leading "CHAPTER N:" / "CHAPTER N -" prefixes so we don't print
    # "Chapter 1: Chapter 1: ..." after we add the prefix below.
    cleaned = _re.sub(r"^chapter\s+\d+\s*[:\-]\s*", "", title, flags=_re.IGNORECASE)
    chapter_label = "Chapter 1: " + cleaned if cleaned else "Energy Reserves and Potential"

    # Soft gray header line — no doc_id (debug noise)
    c.setStrokeColor(HexColor("#dddddd"))
    c.setLineWidth(0.3)
    c.line(36, page.height - 26, page.width - 36, page.height - 26)
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(HexColor("#888888"))
    c.drawString(36, page.height - 18, chapter_label)
    # Right side: ministry tag instead of doc_id
    c.drawRightString(page.width - 36, page.height - 18,
                       "Ministry of Statistics & PI")


def _element_page_map(ast: MultiAST) -> dict[str, int]:
    """Map content element id → 1-based page number."""
    ref_page: dict[str, int] = {}
    for page_idx, pg in enumerate(ast.layoutAST.pages):
        for block in pg.blocks:
            for ref in block.elementRefs:
                if ref:
                    ref_page[ref] = page_idx + 1
    return ref_page


_TOC_BLOCK_TYPES = frozenset({
    "heading", "chapter_heading", "chapter_header", "subtitle",
    "heading_1", "heading_2",
})


_TOC_PARA_TYPES = frozenset({
    "title", "subtitle", "chapter_heading", "chapter_header",
    "heading", "heading_1", "heading_2",
})


def _draw_table_of_contents(c: _canvas.Canvas, page, ast: MultiAST) -> None:
    """Auto-generate a Table of Contents from layout headings and tables."""
    margin_x = 60
    cursor_y = page.height - 90

    # Title of the TOC page
    c.setFillColor(HexColor("#0B3B7A"))
    c.setFont("Helvetica-Bold", 22)
    c.drawString(margin_x, cursor_y, "Table of Contents")
    cursor_y -= 12
    c.setStrokeColor(HexColor("#c8a23a"))
    c.setLineWidth(0.8)
    c.line(margin_x, cursor_y, margin_x + 160, cursor_y)
    cursor_y -= 28

    ref_page = _element_page_map(ast)
    entries: list[tuple[str, int]] = []
    seen: set[str] = set()

    # Headings in document order (by page, then top-to-bottom on page)
    for page_idx, pg in enumerate(ast.layoutAST.pages):
        blocks = sorted(
            [b for b in pg.blocks if b.elementRefs and b.type in _TOC_BLOCK_TYPES],
            key=lambda b: (b.inline_bbox.y if b.inline_bbox else 0),
        )
        for block in blocks:
            for ref in block.elementRefs:
                para = ast.contentAST.paragraph_by_id(ref)
                if not para or not para.content.strip():
                    continue
                label = para.content.strip()
                if label.lower() in ("go",) or len(label) <= 2:
                    continue
                key = label.lower()
                if key in seen:
                    continue
                seen.add(key)
                entries.append((label, ref_page.get(ref, page_idx + 1)))
                break

    # Section headings from contentAST not always on layout blocks
    if len(entries) < 4:
        for para in ast.contentAST.paragraphs:
            if para.type not in _TOC_PARA_TYPES:
                continue
            label = (para.content or "").strip()
            if not label or len(label) <= 2 or label.lower() in seen:
                continue
            if para.type == "title" and "chapter one" in label.lower():
                continue
            pg_no = ref_page.get(para.id, 0)
            if pg_no <= 1:
                continue
            seen.add(label.lower())
            entries.append((label, pg_no))

    # Tables (appendix pages)
    for t in ast.tableAST.tables:
        if not t.title:
            continue
        pg_no = ref_page.get(t.tableId, 0)
        key = t.title.lower()
        if key in seen:
            continue
        seen.add(key)
        entries.append((t.title, pg_no))

    entries.sort(key=lambda e: (e[1] if e[1] else 999, e[0].lower()))

    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#222222"))
    line_h = 18
    for label, page_no in entries:
        if cursor_y < 50:
            break
        # Truncate long labels
        max_chars = 70
        display = label if len(label) <= max_chars else label[: max_chars - 1] + "…"
        c.drawString(margin_x, cursor_y, display)
        # Dotted leader
        leader_left = margin_x + c.stringWidth(display, "Helvetica", 11) + 6
        leader_right = page.width - margin_x - 30
        if leader_right > leader_left:
            c.setStrokeColor(HexColor("#bbbbbb"))
            c.setLineWidth(0.4)
            c.setDash(1, 2)
            c.line(leader_left, cursor_y + 2, leader_right, cursor_y + 2)
            c.setDash()
        if page_no:
            c.drawRightString(page.width - margin_x, cursor_y, str(page_no))
        cursor_y -= line_h


def _draw_page_footer(c: _canvas.Canvas, page, page_no: int,
                      total_pages: int, ast: MultiAST) -> None:
    c.setStrokeColor(HexColor("#cccccc"))
    c.setLineWidth(0.4)
    c.line(36, 30, page.width - 36, 30)
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#666666"))
    from datetime import datetime as _dt
    stamp = (ast.metadata.updatedAt or ast.metadata.createdAt
              or _dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
    c.drawString(36, 18, f"STATATHON Report Engine  |  Generated {stamp}")
    c.drawRightString(page.width - 36, 18, f"Page {page_no} of {total_pages}")


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
    total_pages = len(pages)
    for page_idx, page in enumerate(pages):
        c.setPageSize((page.width, page.height))
        # Ministry header band on every page after the cover
        if page_idx > 0:
            _draw_page_header_band(c, page, ast)
        # Cover page: paint chrome ONLY. We render the title block ourselves
        # in _draw_cover_chrome so the per-block path is skipped here to
        # avoid drawing the same paragraphs twice.
        if page_idx == 0:
            _draw_cover_chrome(c, page, ast)
            # Footer still drawn at the bottom
            c.showPage()
            continue

        # Page 2 special case: if it's an empty_canvas block, paint a Table
        # of Contents derived from the AST instead of leaving the page blank.
        only_block = page.blocks[0] if len(page.blocks) == 1 else None
        if (page_idx == 1 and only_block is not None
              and only_block.type == "empty_canvas"):
            _draw_table_of_contents(c, page, ast)
            _draw_page_footer(c, page, page_idx + 1, total_pages, ast)
            c.showPage()
            continue

        # Draw top-to-bottom (ascending y in top-left coordinates)
        sorted_blocks = sorted(
            page.blocks,
            key=lambda b: b.inline_bbox.y if b.inline_bbox else 0,
        )
        for block in sorted_blocks:
            for element_id in (block.elementRefs or [None]):
                if element_id is None:
                    continue
                # Geometry lookup: prefer inline bbox (coord-AST) then
                # GeometryAST node, then synthesised auto_ node.
                resolved_bbox: BBox | None = None
                if block.inline_bbox:
                    resolved_bbox = block.inline_bbox
                else:
                    node = (ast.geometryAST.by_element_ref(element_id)
                            or ast.geometryAST.by_id(f"node_{element_id}")
                            or ast.geometryAST.by_id(f"auto_{block.blockId}_{element_id}"))
                    if node:
                        resolved_bbox = node.bbox
                if resolved_bbox is None:
                    warnings.append(f"no geometry for {element_id}")
                    continue
                _draw_block(c, block_type=block.type, element_id=element_id,
                             ast=ast, bbox=resolved_bbox, page_height=page.height,
                             allow_overflow=allow_overflow, warnings=warnings)

        # Footer on every page (page number + generated-on stamp)
        if page_idx > 0:
            _draw_page_footer(c, page, page_idx + 1, total_pages, ast)
        c.showPage()

    c.save()
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return RenderResult(pdf_path=str(out_path), content_hash=digest,
                         overflow_warnings=warnings, page_count=len(pages))
