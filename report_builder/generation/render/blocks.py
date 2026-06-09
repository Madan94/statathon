"""R1.5 — per-question block groups for the render layer (R1 exit).

A *question group* is the atomic content unit that both MoSPI archetypes share —
the press-release (prose + figure) and the statistical chapter (prose + long
table). It renders a section heading followed by its ``children`` (paragraphs,
figures, tables) **in order**, threading the active theme and locale so numbers
and bilingual ``{en,hi}`` labels resolve consistently.

This module is the composition layer over ``svg_charts`` / ``tables`` and is the
final piece that lets ``render_html`` be assembled from ``document`` + ``blocks``
+ ``theme`` + ``numbers``.
"""
from __future__ import annotations

from typing import Any

from .numbers import esc, loc
from .svg_charts import render_chart_svg
from .tables import render_table
from .theme import Theme, get_theme


def render_paragraph(block: dict[str, Any], locale: str = "en-IN") -> str:
    content = loc(block.get("content"), locale) if block else ""
    if not content:
        return '<p class="block empty-slot">[empty paragraph]</p>'
    return f'<p class="block">{esc(content)}</p>'


def render_figure(figure: dict[str, Any], charts: dict[str, dict],
                  theme: Theme | str | None = None, *, locale: str = "en-IN") -> str:
    chart = charts.get(figure.get("chartRef")) if figure else None
    body = render_chart_svg(chart, theme, locale=locale)
    caption = loc(figure.get("caption"), locale) if figure else ""
    cap_html = f"<figcaption>{esc(caption)}</figcaption>" if caption else ""
    return f"<figure>{body}{cap_html}</figure>"


def render_child(
    child_id: str,
    blocks: dict[str, dict],
    figures: dict[str, dict],
    charts: dict[str, dict],
    tables: dict[str, dict],
    theme: Theme | str | None = None,
    *,
    locale: str = "en-IN",
    number_system: str = "indian",
) -> str:
    """Dispatch a section child id to the right renderer (prose/figure/table)."""
    if child_id in blocks:
        return render_paragraph(blocks[child_id], locale)
    if child_id in figures:
        return render_figure(figures[child_id], charts, theme, locale=locale)
    if child_id in tables:
        return render_table(tables[child_id], theme, locale=locale,
                            number_system=number_system)
    return f'<div class="empty-slot">[unresolved: {esc(child_id)}]</div>'


def render_question_group(
    section: dict[str, Any],
    report: dict[str, Any],
    theme: Theme | str | None = None,
    *,
    locale: str = "en-IN",
    number_system: str = "indian",
) -> str:
    """Render one section (question group): heading + ordered children.

    This is the per-question unit both archetypes reuse; the document layer
    stacks these between cover/TOC and the appendix.
    """
    get_theme(theme)  # validate/normalise (CSS comes from theme_css upstream)
    blocks = {b.get("blockId"): b for b in (report.get("contentAST") or {}).get("blocks", [])}
    figures = {f.get("figureId"): f for f in (report.get("figureAST") or {}).get("figures", [])}
    charts = {c.get("chartId"): c for c in (report.get("chartAST") or {}).get("charts", [])}
    tables = {t.get("tableId"): t for t in (report.get("tableAST") or {}).get("tables", [])}

    sec_id = section.get("sectionId")
    id_attr = f' id="{esc(sec_id)}"' if sec_id else ""
    parts = [f'<section class="report-section"{id_attr}>']
    title = loc(section.get("title"), locale)
    if title:
        parts.append(f"<h2>{esc(title)}</h2>")
    for child_id in section.get("children") or []:
        parts.append(render_child(child_id, blocks, figures, charts, tables,
                                  theme, locale=locale, number_system=number_system))
    parts.append("</section>")
    return "".join(parts)
