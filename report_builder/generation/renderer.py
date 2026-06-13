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
from .render.svg_charts import render_chart_svg
from .render.tables import render_table
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
    """Back-compat shim → delegates to the SVG chart kit (default theme)."""
    return render_chart_svg(chart, None)


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
    body = render_chart_svg(chart, None)
    caption = figure.get("caption")
    cap_html = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
    return f"<figure>{body}{cap_html}</figure>"


def _render_table(table: dict[str, Any]) -> str:
    """Back-compat shim → delegates to the MoSPI table renderer (Indian system)."""
    return render_table(table, None, locale="en-IN", number_system="indian")


# ─────────────────────────────────────────────────────────────────────────────
# Document assembly
# ─────────────────────────────────────────────────────────────────────────────


def render_html(
    report: dict[str, Any],
    *,
    title: str | None = None,
    theme: Any = None,
    locale: str = "en-IN",
    number_system: str = "indian",
    include_cover: bool = False,
    include_toc: bool = False,
    include_appendix: bool = False,
    number_elements: bool = False,
) -> str:
    """Render the full report dict to a standalone HTML string.

    Document chrome (cover, TOC, provenance appendix, figure/table numbering) is
    opt-in so the default output is unchanged. ``theme`` selects a theme id /
    :class:`Theme`; ``locale`` controls bilingual label selection and
    ``number_system`` (``indian``|``international``) the digit grouping.
    """
    if number_elements:
        from .render.document import number_figures_tables
        number_figures_tables(report)

    sections = (report.get("semanticAST") or {}).get("sections", [])
    metadata = report.get("metadata") or {}

    from .render.numbers import loc as _loc
    doc_title = title or _loc(_section_title(sections), locale) or "Statistical Report"
    period = (metadata.get("period") or {}).get("current") or ""

    body: list[str] = []
    if include_cover:
        from .render.document import build_cover
        body.append(build_cover(report, theme))
    if include_toc:
        from .render.document import build_toc
        body.append(build_toc(sections))

    from .render.blocks import render_question_group
    for sec in sorted(sections, key=lambda s: s.get("order", 0)):
        body.append(render_question_group(
            sec, report, theme, locale=locale, number_system=number_system,
        ))

    if include_appendix:
        from .render.document import build_provenance_appendix
        body.append(build_provenance_appendix(report))

    meta_bits = [b for b in [period and f"Reference period: {period}",
                             metadata.get("reportId") and f"Report ID: {metadata['reportId']}",
                             metadata.get("status") and f"Status: {metadata['status']}"] if b]
    meta_line = " &nbsp;·&nbsp; ".join(_esc(b) for b in meta_bits)

    # Compose stylesheet: theme CSS + (opt) document chrome + @page boxes.
    css = theme_css(theme)
    if include_cover or include_toc or include_appendix:
        from .render.document import document_css, running_header_footer_css
        css = css + document_css() + running_header_footer_css(report, theme)

    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        f"<title>{_esc(doc_title)}</title><style>{css}</style></head><body>"
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


def render_pdf(
    report: dict[str, Any],
    *,
    title: str | None = None,
    theme: Any = None,
    locale: str = "en-IN",
    number_system: str = "indian",
    engine: str = "weasyprint",
    include_cover: bool = True,
    include_toc: bool = True,
    include_appendix: bool = True,
    number_elements: bool = True,
) -> bytes | None:
    """Render to PDF via the selected engine; returns None when unavailable.

    Document chrome (cover/TOC/appendix/numbering) defaults on for PDF — the
    downloadable report is the formal deliverable. Delegates to
    :mod:`report_builder.generation.render.pdf`.
    """
    from .render.pdf import render_pdf as _render_pdf
    return _render_pdf(
        report, title=title, theme=theme, locale=locale,
        number_system=number_system, engine=engine,
        include_cover=include_cover, include_toc=include_toc,
        include_appendix=include_appendix, number_elements=number_elements,
    )
