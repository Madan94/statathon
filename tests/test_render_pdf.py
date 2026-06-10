"""R2 gate — PDF export (WeasyPrint engine + /report.pdf endpoint).

Designed to pass with or without WeasyPrint installed: the engine-dispatch,
availability flag, and API fallback (503) are tested unconditionally; the actual
``%PDF`` byte production is guarded by ``importorskip``.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from report_builder.generation import pdf_available, render_pdf
from report_builder.generation.render import pdf as pdf_mod
from api.report_builder_api import generate_phase_api as G


def _report():
    return {
        "metadata": {"reportId": "rpt_pdf", "status": "draft",
                     "period": {"current": "2023-24"}},
        "semanticAST": {"sections": [
            {"sectionId": "s1", "title": "WPR", "order": 1, "children": ["p1", "t1"]},
        ]},
        "contentAST": {"blocks": [
            {"blockId": "p1", "kind": "paragraph", "content": "WPR was 53.4%."},
        ]},
        "tableAST": {"tables": [
            {"tableId": "t1", "title": "By State",
             "columns": [{"columnId": "c", "header": "State", "role": "dimension"},
                         {"columnId": "v", "header": "WPR", "role": "measure",
                          "unit": "percent", "format": "percent.1"}],
             "rows": [{"c": "HP", "v": 65.1}]},
        ]},
        "provenanceAST": {"evidence": [
            {"questionId": "q1", "componentId": "c1", "analyticsRef": "m", "rowIds": ["r:all"]},
        ]},
    }


# ── engine dispatch / availability ────────────────────────────────────────────

def test_pdf_available_returns_bool():
    assert isinstance(pdf_available("weasyprint"), bool)
    assert isinstance(pdf_available("latex"), bool)
    assert pdf_available("nonsense") is False


def test_supported_engines():
    assert pdf_mod.DEFAULT_ENGINE == "weasyprint"
    assert "weasyprint" in pdf_mod.SUPPORTED_ENGINES
    assert "latex" in pdf_mod.SUPPORTED_ENGINES


def test_render_pdf_unknown_engine_raises():
    with pytest.raises(ValueError):
        render_pdf(_report(), engine="chromium")


def test_render_pdf_returns_none_or_bytes():
    # Graceful: bytes when WeasyPrint present, None when absent — never raises.
    out = render_pdf(_report())
    assert out is None or (isinstance(out, bytes) and out[:4] == b"%PDF")


def test_render_pdf_latex_none_when_tectonic_absent():
    # R6 not yet wired / Tectonic absent → graceful None (no raise).
    out = render_pdf(_report(), engine="latex")
    assert out is None or isinstance(out, bytes)


# ── real PDF bytes (only when WeasyPrint installed) ───────────────────────────

def test_render_pdf_weasyprint_bytes():
    pytest.importorskip("weasyprint")
    out = render_pdf(_report())
    assert isinstance(out, bytes) and out[:4] == b"%PDF"
    assert len(out) > 1000


# ── API endpoint ──────────────────────────────────────────────────────────────

def test_api_pdf_404_when_no_report(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_report_path", lambda t, s: tmp_path / "missing.json")
    with pytest.raises(HTTPException) as ei:
        G.get_report_pdf("tpl", "sig")
    assert ei.value.status_code == 404


def test_api_pdf_503_when_engine_unavailable(tmp_path, monkeypatch):
    rp = tmp_path / "report.output.ast.json"
    rp.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(G, "_report_path", lambda t, s: rp)
    monkeypatch.setattr(G, "pdf_available", lambda engine="weasyprint": False)
    with pytest.raises(HTTPException) as ei:
        G.get_report_pdf("tpl", "sig")
    assert ei.value.status_code == 503


def test_api_pdf_streams_when_available(tmp_path, monkeypatch):
    rp = tmp_path / "report.output.ast.json"
    rp.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(G, "_report_path", lambda t, s: rp)
    monkeypatch.setattr(G, "pdf_available", lambda engine="weasyprint": True)
    monkeypatch.setattr(G, "render_pdf", lambda report, **kw: b"%PDF-1.7 fake")
    resp = G.get_report_pdf("tpl", "sig")
    assert resp.media_type == "application/pdf"
    assert resp.body[:4] == b"%PDF"
    assert "rpt_pdf.pdf" in resp.headers["content-disposition"]


def test_api_pdf_400_on_unknown_engine(tmp_path, monkeypatch):
    rp = tmp_path / "report.output.ast.json"
    rp.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(G, "_report_path", lambda t, s: rp)
    monkeypatch.setattr(G, "pdf_available", lambda engine="weasyprint": True)

    def _raise(report, **kw):
        raise ValueError("unknown PDF engine 'x'")

    monkeypatch.setattr(G, "render_pdf", _raise)
    with pytest.raises(HTTPException) as ei:
        G.get_report_pdf("tpl", "sig", engine="x")
    assert ei.value.status_code == 400
