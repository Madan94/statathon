"""R1.5 gate (R1 EXIT) — golden HTML structure + bilingual labels.

Structural golden snapshot for the gold report shape (counts, not brittle full
strings) and bilingual ``{en,hi}`` label resolution + Devanagari font in CSS.
"""
from __future__ import annotations

import re

from report_builder.generation import render_html
from report_builder.generation.render.blocks import render_question_group
from report_builder.generation.render.numbers import loc


def _gold_shaped_report():
    """A compact report exercising the full gold contract (paragraph + figure +
    grouped_bar chart + grouped table with footnotes), bilingual-ready."""
    return {
        "metadata": {"reportId": "rpt_x", "status": "draft",
                     "period": {"current": "2023-24"}},
        "semanticAST": {"sections": [
            {"sectionId": "sec_wpr", "title": "Worker Population Ratio", "order": 1,
             "children": ["p_intro", "fig_wpr", "tbl_state"]},
        ]},
        "contentAST": {"blocks": [
            {"blockId": "p_intro", "kind": "paragraph",
             "content": "All-India WPR for persons 15+ was 53.4% in 2023-24."},
        ]},
        "figureAST": {"figures": [
            {"figureId": "fig_wpr", "caption": "WPR by Sector, 2023-24",
             "chartRef": "ch_wpr"},
        ]},
        "chartAST": {"charts": [
            {"chartId": "ch_wpr", "chartType": "grouped_bar", "title": "WPR by sector",
             "xAxis": {"label": "Sector"}, "yAxis": {"label": "WPR", "unit": "percent"},
             "series": [
                 {"label": "Rural", "points": [{"x": "Persons", "y": 56.3, "color": "#1F7A1F"}]},
                 {"label": "Urban", "points": [{"x": "Persons", "y": 47.1, "color": "#0B5394"}]},
             ]},
        ]},
        "tableAST": {"tables": [
            {"tableId": "tbl_state", "title": "WPR by State and Sector",
             "columnGroups": [
                 {"groupId": "g_r", "label": "Rural", "spanRefs": ["c_r"]},
                 {"groupId": "g_u", "label": "Urban", "spanRefs": ["c_u"]},
             ],
             "columns": [
                 {"columnId": "c_s", "header": "State/UT", "role": "dimension"},
                 {"columnId": "c_r", "header": "Persons", "role": "measure",
                  "unit": "percent", "format": "percent.1"},
                 {"columnId": "c_u", "header": "Persons", "role": "measure",
                  "unit": "percent", "format": "percent.1"},
             ],
             "rows": [
                 {"c_s": "Himachal Pradesh", "c_r": 65.1, "c_u": 54.0},
                 {"c_s": "Sikkim", "c_r": 63.0, "c_u": 58.2},
             ],
             "footnotes": [{"noteId": "fn_source", "text": "PLFS 2023-24 Unit-Level."}]},
        ]},
    }


def _count(tag: str, s: str) -> int:
    return len(re.findall(rf"<{tag}\b", s))


# ── golden structural snapshot (en-IN) ────────────────────────────────────────

def test_golden_structure_counts():
    html = render_html(_gold_shaped_report())
    assert html.startswith("<!DOCTYPE html>")
    assert _count("section", html) == 1          # one question group
    assert _count("h2", html) == 1
    assert _count("p", html) >= 1                 # paragraph
    assert _count("figure", html) == 1
    assert _count("svg", html) == 1
    assert _count("table", html) == 1
    assert _count("caption", html) == 1
    assert _count("ul", html) == 1               # footnotes list
    # gold values + colors present
    assert "56.3%" in html and "47.1%" in html
    assert "65.1%" in html and "54.0%" in html
    assert "#1F7A1F" in html and "#0B5394" in html
    # column-group header intact
    assert '<th colspan="1">Rural</th>' in html
    assert '<th colspan="1">Urban</th>' in html


# ── per-question group reuse ──────────────────────────────────────────────────

def test_question_group_renders_in_order():
    rep = _gold_shaped_report()
    sec = rep["semanticAST"]["sections"][0]
    html = render_question_group(sec, rep)
    # paragraph before figure before table (document flow order)
    assert html.index("<p ") < html.index("<figure>") < html.index("<table")
    assert 'id="sec_wpr"' in html


# ── bilingual {en,hi} resolution ──────────────────────────────────────────────

def test_loc_picks_language():
    label = {"en": "Sector", "hi": "\u0915\u094d\u0937\u0947\u0924\u094d\u0930"}
    assert loc(label, "en-IN") == "Sector"
    assert loc(label, "hi-IN") == "\u0915\u094d\u0937\u0947\u0924\u094d\u0930"
    assert loc("plain", "hi-IN") == "plain"      # passthrough
    assert loc(None) == ""


def test_bilingual_labels_switch_in_html():
    rep = _gold_shaped_report()
    # make section title + table caption + group label bilingual
    rep["semanticAST"]["sections"][0]["title"] = {
        "en": "Worker Population Ratio", "hi": "\u0936\u094d\u0930\u092e\u093f\u0915 \u0905\u0928\u0941\u092a\u093e\u0924"}
    rep["tableAST"]["tables"][0]["columnGroups"][0]["label"] = {"en": "Rural", "hi": "\u0917\u094d\u0930\u093e\u092e\u0940\u0923"}

    en = render_html(rep, locale="en-IN")
    hi = render_html(rep, locale="hi-IN")
    assert "<h2>Worker Population Ratio</h2>" in en
    assert "\u0936\u094d\u0930\u092e\u093f\u0915 \u0905\u0928\u0941\u092a\u093e\u0924" in hi
    assert '<th colspan="1">Rural</th>' in en
    assert "\u0917\u094d\u0930\u093e\u092e\u0940\u0923" in hi   # Devanagari group label
    # numbers still format the same way regardless of locale
    assert "65.1%" in en and "65.1%" in hi


def test_devanagari_font_in_css():
    html = render_html(_gold_shaped_report(), locale="hi-IN")
    assert "Noto Sans Devanagari" in html


# ── back-compat: plain-string gold still works ────────────────────────────────

def test_plain_string_report_unchanged_default():
    html = render_html(_gold_shaped_report())
    assert "<h2>Worker Population Ratio</h2>" in html
    assert "WPR by Sector, 2023-24" in html      # plain caption passthrough
