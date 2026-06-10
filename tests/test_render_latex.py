"""R6 gate — LaTeX/Tectonic premium PDF engine (optional).

The ``.tex`` structure and content-parity checks run unconditionally; actual PDF
compilation is guarded (skipped when the Tectonic binary is absent), and the
default WeasyPrint path is untouched.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from report_builder.generation import render_pdf
from report_builder.generation.render import latex as L
from api.report_builder_api import generate_phase_api as G


def _report():
    return {
        "metadata": {"reportId": "rpt_tex", "status": "draft",
                     "period": {"current": "2023-24"}},
        "semanticAST": {"sections": [
            {"sectionId": "sec_wpr", "title": "Worker Population Ratio", "order": 1,
             "children": ["p_intro", "fig_1", "tbl_state"]},
            {"sectionId": "sec_more", "title": "Coverage & Notes", "order": 2,
             "children": ["p_more"]},
        ]},
        "contentAST": {"blocks": [
            {"blockId": "p_intro", "kind": "paragraph",
             "content": "WPR stood at 53.4% in 2023-24."},
            {"blockId": "p_more", "kind": "paragraph",
             "content": "Coverage was 100% across all states & UTs."},
        ]},
        "figureAST": {"figures": [
            {"figureId": "fig_1", "caption": "WPR by Sector", "chartRef": "chart_1"},
        ]},
        "chartAST": {"charts": [
            {"chartId": "chart_1", "chartType": "grouped_bar",
             "series": [{"label": "WPR", "points": [
                 {"x": "Rural", "y": 56.3}, {"x": "Urban", "y": 47.1}]}]},
        ]},
        "tableAST": {"tables": [
            {"tableId": "tbl_state", "title": "WPR by State",
             "columns": [
                 {"columnId": "col_state", "header": "State", "role": "dimension",
                  "align": "left"},
                 {"columnId": "col_v", "header": "WPR", "role": "measure",
                  "unit": "percent", "format": "percent.1", "align": "right"}],
             "rows": [{"col_state": "Himachal Pradesh", "col_v": 65.1},
                      {"col_state": "Sikkim", "col_v": 63.0}],
             "footnotes": [{"noteId": "fn_src", "text": "Source: PLFS 2023-24."}]},
        ]},
    }


# ── .tex structure & parity ───────────────────────────────────────────────────

def test_tectonic_available_returns_bool():
    assert isinstance(L.tectonic_available(), bool)


def test_render_latex_has_document_skeleton():
    tex = L.render_latex(_report())
    assert "\\documentclass" in tex
    assert "\\begin{document}" in tex and "\\end{document}" in tex
    assert "\\tableofcontents" in tex          # include_toc default on
    assert "\\begin{titlepage}" in tex          # include_cover default on


def test_render_latex_section_and_table_parity():
    report = _report()
    tex = L.render_latex(report)
    assert tex.count("\\section{") == len(report["semanticAST"]["sections"])  # 2
    assert tex.count("\\begin{longtable}") == len(report["tableAST"]["tables"])  # 1
    assert "\\toprule" in tex and "\\endhead" in tex  # repeating header
    assert "65.1\\%" in tex                            # measure formatted (percent escaped)


def test_render_latex_escapes_specials():
    tex = L.render_latex(_report())
    # "100% across all states & UTs" → % and & escaped.
    assert "100\\%" in tex
    assert "states \\& UTs" in tex


def test_render_latex_cover_off_uses_maketitle():
    tex = L.render_latex(_report(), include_cover=False, include_toc=False)
    assert "\\begin{titlepage}" not in tex
    assert "\\maketitle" in tex


# ── compilation (skipped without Tectonic) ────────────────────────────────────

def test_compile_pdf_tectonic_none_or_bytes():
    out = L.compile_pdf_tectonic(L.render_latex(_report()))
    assert out is None or (isinstance(out, bytes) and out[:4] == b"%PDF")


def test_render_pdf_latex_real_bytes():
    if not L.tectonic_available():
        pytest.skip("Tectonic not installed")
    out = L.render_pdf_latex(_report())
    assert isinstance(out, bytes) and out[:4] == b"%PDF"


def test_render_pdf_engine_latex_graceful():
    # Routed through the engine dispatch — never raises, None or %PDF.
    out = render_pdf(_report(), engine="latex")
    assert out is None or (isinstance(out, bytes) and out[:4] == b"%PDF")


# ── API: latex engine ─────────────────────────────────────────────────────────

def test_api_pdf_latex_503_when_unavailable(tmp_path, monkeypatch):
    rp = tmp_path / "report.output.ast.json"
    rp.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(G, "_report_path", lambda t, s: rp)
    monkeypatch.setattr(G, "pdf_available", lambda engine="weasyprint": False)
    with pytest.raises(HTTPException) as ei:
        G.get_report_pdf("tpl", "sig", engine="latex")
    assert ei.value.status_code == 503


def test_api_pdf_latex_streams_when_available(tmp_path, monkeypatch):
    rp = tmp_path / "report.output.ast.json"
    rp.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(G, "_report_path", lambda t, s: rp)
    monkeypatch.setattr(G, "pdf_available", lambda engine="weasyprint": True)
    monkeypatch.setattr(G, "render_pdf", lambda report, **kw: b"%PDF-1.5 latex")
    resp = G.get_report_pdf("tpl", "sig", engine="latex")
    assert resp.media_type == "application/pdf"
    assert resp.body[:4] == b"%PDF"
