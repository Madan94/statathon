"""S6 gate tests — the renderer turns a report dict into standalone HTML.

Covers: section/outline walk, paragraph + table (with column groups + footnotes) +
figure/chart rendering, inline SVG bar generation, value formatting (percent /
grouping / decimals), HTML escaping, and graceful handling of empty/unresolved
slots. PDF is exercised only as an availability check (WeasyPrint optional).

Fully offline and deterministic — charts are inline SVG, no plotting deps.
"""
from __future__ import annotations

from report_builder.generation.renderer import (
    render_html, render_pdf, _render_chart_svg, _fmt_value,
)


def _report() -> dict:
    return {
        "metadata": {"reportId": "rpt_test_001", "status": "complete",
                     "period": {"current": "2023-24"}},
        "semanticAST": {"sections": [{
            "sectionId": "sec_wpr", "title": "Worker Population Ratio", "order": 1,
            "children": ["p_wpr_intro", "fig_wpr_01", "table_wpr_state"]}]},
        "contentAST": {"blocks": [{
            "blockId": "p_wpr_intro", "kind": "paragraph",
            "content": "Rural WPR (56.3%) exceeded urban (47.1%).",
            "slot": {"status": "filled"}}]},
        "chartAST": {"charts": [{
            "chartId": "chart_wpr_sector", "chartType": "grouped_bar",
            "yAxis": {"unit": "percent"},
            "series": [{"label": "WPR", "points": [
                {"x": "Rural", "y": 56.3, "color": "#1F7A1F", "rowIds": ["r:sector=Rural"]},
                {"x": "Urban", "y": 47.1, "color": "#0B5394", "rowIds": ["r:sector=Urban"]}]}],
            "slot": {"status": "filled"}}]},
        "figureAST": {"figures": [{
            "figureId": "fig_wpr_01", "caption": "WPR by Sector, 2023-24",
            "chartRef": "chart_wpr_sector", "slot": {"status": "filled"}}]},
        "tableAST": {"tables": [{
            "tableId": "table_wpr_state", "title": "WPR by State and Sector",
            "columnGroups": [
                {"groupId": "grp_rural", "label": "Rural", "spanRefs": ["col_rural"]},
                {"groupId": "grp_urban", "label": "Urban", "spanRefs": ["col_urban"]}],
            "columns": [
                {"columnId": "col_state", "header": "State/UT", "role": "dimension"},
                {"columnId": "col_rural", "header": "Rural", "role": "measure",
                 "unit": "percent", "format": "percent.1", "group": "grp_rural"},
                {"columnId": "col_urban", "header": "Urban", "role": "measure",
                 "unit": "percent", "format": "percent.1", "group": "grp_urban"}],
            "rows": [
                {"col_state": "Himachal Pradesh", "col_rural": 65.1, "col_urban": 54.0,
                 "rowIds": ["r:state=HP"]},
                {"col_state": "Sikkim", "col_rural": 63.0, "col_urban": 58.2,
                 "rowIds": ["r:state=SK"]}],
            "footnotes": [{"noteId": "fn_src", "text": "Source: Test PLFS, 2023-24."}],
            "slot": {"status": "filled"}}]},
    }


# ── value formatting ──────────────────────────────────────────────────────────

def test_fmt_percent_and_grouping():
    assert _fmt_value(56.3, "percent") == "56.3%"
    assert _fmt_value(1234.5, None) == "1,234.5"
    assert _fmt_value(65.12, "percent", "percent.1") == "65.1%"
    assert _fmt_value(None) == "—"


# ── document structure ────────────────────────────────────────────────────────

def test_html_has_title_sections_and_meta():
    out = render_html(_report())
    assert out.startswith("<!DOCTYPE html>")
    assert "<title>Worker Population Ratio</title>" in out
    assert "<h2>Worker Population Ratio</h2>" in out
    assert "Reference period: 2023-24" in out
    assert "Report ID: rpt_test_001" in out


def test_paragraph_rendered_escaped():
    rep = _report()
    rep["contentAST"]["blocks"][0]["content"] = "WPR rose <b>sharply</b> & held."
    out = render_html(rep)
    assert "WPR rose &lt;b&gt;sharply&lt;/b&gt; &amp; held." in out
    assert "<b>sharply</b>" not in out          # not injected as raw HTML


def test_table_rendered_with_groups_and_footnotes():
    out = render_html(_report())
    assert "<caption>WPR by State and Sector</caption>" in out
    assert '<th colspan="1">Rural</th>' in out  # column group header
    assert "Himachal Pradesh" in out
    assert "65.1%" in out and "54.0%" in out     # measure cells formatted percent
    assert "Source: Test PLFS, 2023-24." in out  # footnote


def test_figure_and_chart_svg_rendered():
    out = render_html(_report())
    assert "<figure>" in out and "<figcaption>WPR by Sector, 2023-24</figcaption>" in out
    assert "<svg" in out
    assert "Rural" in out and "Urban" in out


def test_chart_svg_has_one_bar_per_point():
    chart = _report()["chartAST"]["charts"][0]
    svg = _render_chart_svg(chart)
    assert svg.count("<rect") == 2               # one bar per point
    assert "#1F7A1F" in svg and "#0B5394" in svg  # point colours used
    assert "56.3%" in svg                        # value label drawn


def test_empty_chart_renders_placeholder_not_crash():
    chart = {"series": []}
    assert "empty-slot" in _render_chart_svg(chart)


def test_unresolved_child_is_flagged():
    rep = _report()
    rep["semanticAST"]["sections"][0]["children"].append("ghost_block")
    out = render_html(rep)
    assert "unresolved: ghost_block" in out


def test_render_pdf_optional_returns_bytes_or_none():
    # WeasyPrint may not be installed; either a PDF byte string or a graceful None.
    result = render_pdf(_report())
    assert result is None or (isinstance(result, (bytes, bytearray)) and result[:4] == b"%PDF")
