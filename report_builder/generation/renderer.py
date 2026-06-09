"""S6 — Renderer: turn ③ ``report.output.ast.json`` into standalone HTML (+ PDF).

Walks ``semanticAST.sections`` (the document outline) and renders each child by
id against the value-bearing subtrees:

    paragraph blockId  →  contentAST  →  <p>
    figureId           →  figureAST → chartAST  →  inline <svg> bar chart + caption
    tableId            →  tableAST  →  <table> (column groups + footnotes)

Self-contained and fully offline: charts are drawn as inline SVG (no matplotlib),
numbers are formatted per the column/axis ``unit``/``format``, and the whole
document is one HTML string with embedded CSS. PDF is optional — emitted only if
WeasyPrint is importable, otherwise HTML is the deliverable.
"""
from __future__ import annotations

import logging
from typing import Any

from .render.numbers import esc as _esc
from .render.numbers import format_value
from .render.theme import get_theme, theme_css

logger = logging.getLogger(__name__)

# Fallback categorical palette (mirrors the filler) when a point has no colour.
# Sourced from the default theme so palette + CSS stay in sync.
_PALETTE = get_theme(None).palette

# Default document CSS (navy theme). theme_css() is the single source of truth.
_CSS = theme_css(None)


# ─────────────────────────────────────────────────────────────────────────────
# Value formatting
# ─────────────────────────────────────────────────────────────────────────────


def _fmt_value(value: Any, unit: str | None = None, fmt: str | None = None) -> str:
    """Thin wrapper over the render layer's formatter (Indian grouping default)."""
    return format_value(value, unit=unit, fmt=fmt, system="indian")


# ─────────────────────────────────────────────────────────────────────────────
# Inline SVG bar chart (offline, no plotting deps)
# ─────────────────────────────────────────────────────────────────────────────


def _render_chart_svg(chart: dict[str, Any]) -> str:
    series = chart.get("series") or []
    points = series[0].get("points") if series else []
    if not points:
        return '<div class="empty-slot">[chart has no data]</div>'

    unit = (chart.get("yAxis") or {}).get("unit")
    width, height = 640, 280
    pad_l, pad_b, pad_t, pad_r = 48, 40, 16, 16
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    values = [p.get("y") or 0 for p in points]
    vmax = max(values) or 1.0
    vmax *= 1.15  # headroom
    n = len(points)
    gap = 0.35
    band = plot_w / n
    bar_w = band * (1 - gap)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" '
             f'xmlns="http://www.w3.org/2000/svg" class="chart">']
    # y axis baseline
    base_y = pad_t + plot_h
    parts.append(f'<line x1="{pad_l}" y1="{base_y}" x2="{width - pad_r}" y2="{base_y}" '
                 f'stroke="#999" stroke-width="1"/>')
    # gridline + label at vmax/2 and vmax
    for frac in (0.5, 1.0):
        gv = vmax * frac
        gy = base_y - plot_h * frac
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}" y2="{gy:.1f}" '
                     f'stroke="#eee" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{gy + 4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#777">{_fmt_value(round(gv, 1), unit)}</text>')

    for i, p in enumerate(points):
        v = p.get("y") or 0
        color = p.get("color") or _PALETTE[i % len(_PALETTE)]
        bh = (v / vmax) * plot_h if vmax else 0
        bx = pad_l + band * i + (band - bar_w) / 2
        by = base_y - bh
        parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
                     f'fill="{color}" rx="2"/>')
        parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{by - 5:.1f}" text-anchor="middle" '
                     f'font-size="12" fill="#333">{_fmt_value(v, unit)}</text>')
        parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
                     f'font-size="12" fill="#333">{_esc(p.get("x"))}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Block renderers
# ─────────────────────────────────────────────────────────────────────────────


def _render_paragraph(block: dict[str, Any]) -> str:
    content = block.get("content")
    if not content:
        return '<p class="block empty-slot">[empty paragraph]</p>'
    return f'<p class="block">{_esc(content)}</p>'


def _render_figure(figure: dict[str, Any], charts: dict[str, dict]) -> str:
    chart = charts.get(figure.get("chartRef"))
    body = _render_chart_svg(chart) if chart else '<div class="empty-slot">[missing chart]</div>'
    caption = figure.get("caption")
    cap_html = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
    return f"<figure>{body}{cap_html}</figure>"


def _render_table(table: dict[str, Any]) -> str:
    columns = table.get("columns") or []
    groups = table.get("columnGroups") or []
    rows = table.get("rows") or []
    title = table.get("title")

    parts = ["<table>"]
    if title:
        parts.append(f"<caption>{_esc(title)}</caption>")
    parts.append("<thead>")

    # Optional grouped header row (e.g. Rural / Urban spanning groups).
    if groups:
        group_of = {}
        for g in groups:
            for ref in g.get("spanRefs") or []:
                group_of[ref] = g
        parts.append('<tr class="colgroup-head">')
        i = 0
        while i < len(columns):
            col = columns[i]
            g = group_of.get(col.get("columnId"))
            if g:
                span = len(g.get("spanRefs") or [])
                parts.append(f'<th colspan="{span}">{_esc(g.get("label"))}</th>')
                i += span
            else:
                parts.append("<th></th>")
                i += 1
        parts.append("</tr>")

    parts.append("<tr>")
    for col in columns:
        cls = "measure" if col.get("role") == "measure" else ""
        parts.append(f'<th class="{cls}">{_esc(col.get("header"))}</th>')
    parts.append("</tr></thead><tbody>")

    for row in rows:
        parts.append("<tr>")
        for col in columns:
            cid = col.get("columnId")
            is_measure = col.get("role") == "measure"
            cls = "measure" if is_measure else ""
            val = (_fmt_value(row.get(cid), col.get("unit"), col.get("format"))
                   if is_measure else _esc(row.get(cid)))
            parts.append(f'<td class="{cls}">{val}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table>")

    # Footnotes (rendered text already filled by the filler).
    notes = [fn.get("text") for fn in (table.get("footnotes") or []) if fn.get("text")]
    if notes:
        parts.append('<ul class="footnotes">')
        parts.extend(f"<li>{_esc(n)}</li>" for n in notes)
        parts.append("</ul>")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Document assembly
# ─────────────────────────────────────────────────────────────────────────────


def render_html(report: dict[str, Any], *, title: str | None = None) -> str:
    """Render the full report dict to a standalone HTML string."""
    blocks = {b.get("blockId"): b for b in (report.get("contentAST") or {}).get("blocks", [])}
    figures = {f.get("figureId"): f for f in (report.get("figureAST") or {}).get("figures", [])}
    charts = {c.get("chartId"): c for c in (report.get("chartAST") or {}).get("charts", [])}
    tables = {t.get("tableId"): t for t in (report.get("tableAST") or {}).get("tables", [])}
    sections = (report.get("semanticAST") or {}).get("sections", [])
    metadata = report.get("metadata") or {}

    doc_title = title or _section_title(sections) or "Statistical Report"
    period = (metadata.get("period") or {}).get("current") or ""

    body: list[str] = []
    for sec in sorted(sections, key=lambda s: s.get("order", 0)):
        body.append('<section class="report-section">')
        if sec.get("title"):
            body.append(f"<h2>{_esc(sec.get('title'))}</h2>")
        for child_id in sec.get("children") or []:
            body.append(_render_child(child_id, blocks, figures, charts, tables))
        body.append("</section>")

    meta_bits = [b for b in [period and f"Reference period: {period}",
                             metadata.get("reportId") and f"Report ID: {metadata['reportId']}",
                             metadata.get("status") and f"Status: {metadata['status']}"] if b]
    meta_line = " &nbsp;·&nbsp; ".join(_esc(b) for b in meta_bits)

    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        f"<title>{_esc(doc_title)}</title><style>{_CSS}</style></head><body>"
        f'<div class="report"><header class="report-header">'
        f"<h1>{_esc(doc_title)}</h1>"
        f'<div class="report-meta">{meta_line}</div></header>'
        f"{''.join(body)}</div></body></html>"
    )


def _section_title(sections: list[dict[str, Any]]) -> str:
    for s in sections:
        if s.get("title"):
            return s["title"]
    return ""


def _render_child(child_id: str, blocks, figures, charts, tables) -> str:
    if child_id in blocks:
        return _render_paragraph(blocks[child_id])
    if child_id in figures:
        return _render_figure(figures[child_id], charts)
    if child_id in tables:
        return _render_table(tables[child_id])
    logger.info("[S6] semantic child %s has no matching content", child_id)
    return f'<div class="empty-slot">[unresolved: {_esc(child_id)}]</div>'


def render_pdf(report: dict[str, Any], *, title: str | None = None) -> bytes | None:
    """Render to PDF via WeasyPrint if available; returns None when unavailable."""
    try:
        from weasyprint import HTML  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.info("[S6] PDF skipped (WeasyPrint unavailable): %s", exc)
        return None
    html_str = render_html(report, title=title)
    return HTML(string=html_str).write_pdf()
