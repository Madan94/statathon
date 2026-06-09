"""R1.4 gate — document chrome (cover, TOC, header/footer, numbering, appendix).

Asserts the opt-in chrome appears when requested and that defaults stay clean
(no chrome leaks into the baseline output).
"""
from __future__ import annotations

import copy

from report_builder.generation import render_html
from report_builder.generation.render.document import (
    build_cover, build_toc, build_provenance_appendix, number_figures_tables,
    running_header_footer_css,
)


def _report():
    return {
        "metadata": {
            "title": "Worker Population Ratio",
            "subtitle": "PLFS 2023-24",
            "reportId": "rpt_test_001",
            "status": "draft",
            "period": {"current": "2023-24"},
            "ministry": "Ministry of Statistics and Programme Implementation",
        },
        "semanticAST": {"sections": [
            {"sectionId": "sec_intro", "title": "Introduction", "order": 1,
             "children": ["p1", "fig1", "tbl1"]},
            {"sectionId": "sec_states", "title": "State Analysis", "order": 2,
             "children": ["fig2", "tbl2"]},
        ]},
        "contentAST": {"blocks": [
            {"blockId": "p1", "kind": "paragraph", "content": "Intro text.",
             "provenance": {"questionId": "q1", "componentId": "q1_c1",
                            "analyticsRef": "m_all", "evidenceRef": ["r:all"]}},
        ]},
        "figureAST": {"figures": [
            {"figureId": "fig1", "caption": "WPR by Sector", "chartRef": "c1"},
            {"figureId": "fig2", "caption": "WPR by State", "chartRef": "c2"},
        ]},
        "chartAST": {"charts": [
            {"chartId": "c1", "chartType": "bar", "yAxis": {"unit": "percent"},
             "series": [{"label": "x", "points": [{"x": "Rural", "y": 56.3}]}]},
            {"chartId": "c2", "chartType": "bar", "yAxis": {"unit": "percent"},
             "series": [{"label": "x", "points": [{"x": "HP", "y": 65.1}]}]},
        ]},
        "tableAST": {"tables": [
            {"tableId": "tbl1", "title": "Summary",
             "columns": [{"columnId": "a", "header": "A", "role": "dimension"}],
             "rows": [{"a": "x"}]},
            {"tableId": "tbl2", "title": "By State",
             "columns": [{"columnId": "a", "header": "A", "role": "dimension"}],
             "rows": [{"a": "y"}]},
        ]},
        "provenanceAST": {"evidence": [
            {"questionId": "q1", "componentId": "q1_c1", "analyticsRef": "m_all",
             "rowIds": ["r:all"]},
        ]},
    }


# ── cover ─────────────────────────────────────────────────────────────────────

def test_build_cover_contains_key_fields():
    html = build_cover(_report())
    assert 'class="cover-page"' in html
    assert "Worker Population Ratio" in html
    assert "Reference period: 2023-24" in html
    assert "Report ID: rpt_test_001" in html
    assert "Ministry of Statistics and Programme Implementation" in html
    assert "cover-logo-placeholder" in html      # logo slot present


# ── toc ───────────────────────────────────────────────────────────────────────

def test_build_toc_lists_sections_in_order():
    html = build_toc(_report()["semanticAST"]["sections"])
    assert 'class="toc"' in html
    assert "Introduction" in html and "State Analysis" in html
    assert 'href="#sec_intro"' in html and 'href="#sec_states"' in html
    # numbering 1. then 2.
    assert html.index("1.") < html.index("2.")


# ── header/footer @page ───────────────────────────────────────────────────────

def test_header_footer_css_has_page_counters():
    css = running_header_footer_css(_report())
    assert "@page" in css
    assert 'counter(page)' in css and 'counter(pages)' in css
    assert "Worker Population Ratio" in css


# ── figure/table numbering ────────────────────────────────────────────────────

def test_number_figures_tables_prefixes():
    rep = number_figures_tables(copy.deepcopy(_report()))
    figs = {f["figureId"]: f for f in rep["figureAST"]["figures"]}
    tbls = {t["tableId"]: t for t in rep["tableAST"]["tables"]}
    assert figs["fig1"]["caption"].startswith("Figure 1.1")
    assert figs["fig2"]["caption"].startswith("Figure 2.1")
    assert tbls["tbl1"]["title"].startswith("Table 1.1")
    assert tbls["tbl2"]["title"].startswith("Table 2.1")
    assert figs["fig1"]["figureNumber"] == "Figure 1.1"


def test_numbering_is_not_double_applied():
    rep = number_figures_tables(copy.deepcopy(_report()))
    rep2 = number_figures_tables(rep)
    figs = {f["figureId"]: f for f in rep2["figureAST"]["figures"]}
    assert figs["fig1"]["caption"].count("Figure 1.1") == 1


# ── provenance appendix ───────────────────────────────────────────────────────

def test_provenance_appendix_from_evidence():
    html = build_provenance_appendix(_report())
    assert "Appendix: Provenance" in html
    assert "q1" in html and "q1_c1" in html and "m_all" in html and "r:all" in html


def test_provenance_appendix_empty_when_none():
    rep = _report()
    rep["provenanceAST"] = {}
    rep["contentAST"]["blocks"][0].pop("provenance")
    assert build_provenance_appendix(rep) == ""


# ── integration via render_html (opt-in) ──────────────────────────────────────

def test_render_html_includes_chrome_when_requested():
    html = render_html(
        _report(), include_cover=True, include_toc=True,
        include_appendix=True, number_elements=True,
    )
    assert 'class="cover-page"' in html
    assert 'class="toc"' in html
    assert "Appendix: Provenance" in html
    assert 'id="sec_intro"' in html              # section anchor for TOC
    assert "Figure 1.1" in html                  # numbering applied
    assert "@page" in html                       # running header CSS injected


def test_render_html_default_has_no_chrome():
    html = render_html(_report())
    assert "cover-page" not in html
    assert 'class="toc"' not in html
    assert "Appendix: Provenance" not in html
    assert "@page" not in html
    # baseline still intact (doc title derives from first section)
    assert "<title>Introduction</title>" in html
    assert "<h2>Introduction</h2>" in html
