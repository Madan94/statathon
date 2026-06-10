"""R4 gate — customization (template profile + report overrides + re-render).

Covers the pure transforms (deep-merge precedence, section reorder/filter,
chart-type swap, table format, render-flag mapping, input immutability) and the
API surface (profile round-trip, sparse override deep-merge, customized render).
No network / native deps: endpoint functions are called directly with the stash
paths monkeypatched, mirroring ``test_render_pdf``.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from report_builder.generation import (
    apply_profile,
    deep_merge,
    effective_profile,
    render_flags,
    ReportOverrides,
    TemplateProfile,
)
from report_builder.generation.profile import (
    _default_back_matter,
    _default_front_matter,
)
from api.report_builder_api import generate_phase_api as G


def _report():
    """Two sections / two questions: q1 (para + figure→chart), q2 (para + table)."""
    return {
        "metadata": {"reportId": "rpt_cust", "status": "draft",
                     "period": {"current": "2023-24"}},
        "semanticAST": {"sections": [
            {"sectionId": "sec_wpr", "title": "Worker Population Ratio", "order": 1,
             "children": ["p_intro", "fig_1"]},
            {"sectionId": "sec_state", "title": "State Ranking", "order": 2,
             "children": ["p_state", "tbl_state"]},
        ]},
        "contentAST": {"blocks": [
            {"blockId": "p_intro", "kind": "paragraph",
             "content": "Intro WPR sentence at 53.4%.",
             "provenance": {"questionId": "q_wpr_01"}},
            {"blockId": "p_state", "kind": "paragraph",
             "content": "State ranking sentence.",
             "provenance": {"questionId": "q_wpr_02"}},
        ]},
        "figureAST": {"figures": [
            {"figureId": "fig_1", "caption": "WPR by Sector", "chartRef": "chart_1"},
        ]},
        "chartAST": {"charts": [
            {"chartId": "chart_1", "chartType": "grouped_bar", "title": "WPR by Sector",
             "biQuery": "q_wpr_01",
             "yAxis": {"unit": "percent"},
             "series": [{"label": "WPR", "points": [
                 {"x": "Rural", "y": 56.3}, {"x": "Urban", "y": 47.1}]}],
             "provenance": {"questionId": "q_wpr_01"}},
        ]},
        "tableAST": {"tables": [
            {"tableId": "tbl_state", "title": "By State", "biQuery": "q_wpr_02",
             "columns": [
                 {"columnId": "col_state", "header": "State", "role": "dimension",
                  "align": "left", "format": None},
                 {"columnId": "col_v", "header": "WPR", "role": "measure",
                  "unit": "percent", "format": "percent.1", "align": "right"}],
             "rows": [{"col_state": "Himachal Pradesh", "col_v": 65.1,
                       "rowIds": ["r:state=HP"]}],
             "provenance": {"questionId": "q_wpr_02"}},
        ]},
    }


# ── deep-merge / effective profile ────────────────────────────────────────────

def test_effective_profile_override_wins():
    eff = effective_profile({"theme": "mospi_navy", "locale": "en-IN"},
                            {"theme": "mospi_saffron", "locale": "hi-IN"})
    assert eff["theme"] == "mospi_saffron"
    assert eff["locale"] == "hi-IN"
    # Untouched defaults survive.
    assert eff["numberSystem"] == "indian"


def test_effective_profile_perquestion_deep_merge():
    template = {"perQuestion": {"q1": {"chartType": "bar", "tone": "formal"}}}
    overrides = {"perQuestion": {"q1": {"chartType": "line"}}}
    eff = effective_profile(template, overrides)
    # chartType replaced, tone preserved (per-question deep merge).
    assert eff["perQuestion"]["q1"] == {"chartType": "line", "tone": "formal"}


def test_deep_merge_skips_none_and_replaces_lists():
    base = {"a": 1, "list": [1, 2], "n": "keep"}
    out = deep_merge(base, {"a": 2, "list": [9], "n": None})
    assert out == {"a": 2, "list": [9], "n": "keep"}


def test_overrides_to_dict_is_sparse():
    sparse = ReportOverrides.from_dict({"theme": "x"}).to_dict()
    assert sparse == {"theme": "x"}  # unset keys dropped


def test_template_profile_from_dict_fills_defaults():
    prof = TemplateProfile.from_dict({"theme": "mospi_navy"}).to_dict()
    assert prof["theme"] == "mospi_navy"
    assert prof["frontMatter"] == _default_front_matter()
    assert prof["backMatter"] == _default_back_matter()


# ── apply_profile ─────────────────────────────────────────────────────────────

def test_apply_profile_reorders_sections():
    eff = effective_profile({}, {"sectionOrder": ["sec_state", "sec_wpr"]})
    out = apply_profile(_report(), eff)
    secs = out["semanticAST"]["sections"]
    assert [s["sectionId"] for s in secs] == ["sec_state", "sec_wpr"]
    assert [s["order"] for s in secs] == [1, 2]


def test_apply_profile_filters_questions():
    eff = effective_profile({}, {"includedQuestions": ["q_wpr_01"]})
    out = apply_profile(_report(), eff)
    secs = out["semanticAST"]["sections"]
    # q2 section dropped entirely; q1 section + children retained.
    assert [s["sectionId"] for s in secs] == ["sec_wpr"]
    assert secs[0]["children"] == ["p_intro", "fig_1"]


def test_apply_profile_swaps_chart_type():
    eff = effective_profile({}, {"perQuestion": {"q_wpr_01": {"chartType": "line"}}})
    out = apply_profile(_report(), eff)
    assert out["chartAST"]["charts"][0]["chartType"] == "line"


def test_apply_profile_table_format_dict():
    eff = effective_profile({}, {"perQuestion": {"q_wpr_02": {"tableFormat": {"col_v": "percent.2"}}}})
    out = apply_profile(_report(), eff)
    cols = {c["columnId"]: c for c in out["tableAST"]["tables"][0]["columns"]}
    assert cols["col_v"]["format"] == "percent.2"
    assert cols["col_state"]["format"] is None  # untouched


def test_apply_profile_table_format_string_hits_measures():
    eff = effective_profile({}, {"perQuestion": {"q_wpr_02": {"tableFormat": "number.0"}}})
    out = apply_profile(_report(), eff)
    cols = {c["columnId"]: c for c in out["tableAST"]["tables"][0]["columns"]}
    assert cols["col_v"]["format"] == "number.0"      # measure column
    assert cols["col_state"]["format"] is None         # dimension untouched


def test_apply_profile_stamps_metadata():
    eff = effective_profile({"theme": "mospi_saffron"}, {"locale": "hi-IN", "numberSystem": "international"})
    out = apply_profile(_report(), eff)
    md = out["metadata"]
    assert md["locale"] == "hi-IN"
    assert md["numberSystem"] == "international"
    assert md["theme"] == "mospi_saffron"
    assert "customization" in md


def test_apply_profile_does_not_mutate_input():
    report = _report()
    snapshot = json.dumps(report, sort_keys=True)
    apply_profile(report, effective_profile({}, {"sectionOrder": ["sec_state", "sec_wpr"],
                                                 "perQuestion": {"q_wpr_01": {"chartType": "line"}}}))
    assert json.dumps(report, sort_keys=True) == snapshot


# ── render_flags ──────────────────────────────────────────────────────────────

def test_render_flags_maps_matter_and_system():
    eff = effective_profile({}, {"frontMatter": {"cover": False, "toc": True},
                                 "backMatter": {"glossary": False, "notes": False},
                                 "numberSystem": "international", "locale": "hi-IN"})
    flags = render_flags(eff)
    assert flags["include_cover"] is False
    assert flags["include_toc"] is True
    assert flags["include_appendix"] is False
    assert flags["number_system"] == "international"
    assert flags["locale"] == "hi-IN"
    assert flags["number_elements"] is True  # toc on ⇒ numbering on


# ── API ───────────────────────────────────────────────────────────────────────

def test_api_profile_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_profile_path", lambda t, s: tmp_path / "profile.json")
    saved = G.put_profile("t", "s", {"theme": "mospi_navy", "numberSystem": "international"})
    assert saved["theme"] == "mospi_navy"
    assert saved["numberSystem"] == "international"
    loaded = G.get_profile("t", "s")
    assert loaded == saved


def test_api_overrides_patch_deep_merges(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_overrides_path", lambda t, s: tmp_path / "overrides.json")
    G.patch_overrides("t", "s", {"perQuestion": {"q1": {"chartType": "bar", "tone": "formal"}}})
    merged = G.patch_overrides("t", "s", {"perQuestion": {"q1": {"chartType": "line"}}})
    # second PATCH deep-merges per question; stays sparse (no defaults).
    assert merged == {"perQuestion": {"q1": {"chartType": "line", "tone": "formal"}}}
    assert G.get_overrides("t", "s") == merged


def test_api_render_html_applies_overrides(tmp_path, monkeypatch):
    rp = tmp_path / "report.output.ast.json"
    rp.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(G, "_report_path", lambda t, s: rp)
    monkeypatch.setattr(G, "_profile_path", lambda t, s: tmp_path / "profile.json")
    monkeypatch.setattr(G, "_overrides_path", lambda t, s: tmp_path / "overrides.json")

    G.patch_overrides("t", "s", {"includedQuestions": ["q_wpr_01"]})
    resp = G.render_customized("t", "s", fmt="html")
    body = resp.body.decode("utf-8")
    assert resp.status_code == 200
    assert "Intro WPR sentence" in body        # q1 retained
    assert "State ranking sentence" not in body  # q2 filtered out


def test_api_render_404_when_no_report(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_report_path", lambda t, s: tmp_path / "missing.json")
    with pytest.raises(HTTPException) as ei:
        G.render_customized("t", "s", fmt="html")
    assert ei.value.status_code == 404


def test_api_render_pdf_503_when_unavailable(tmp_path, monkeypatch):
    rp = tmp_path / "report.output.ast.json"
    rp.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(G, "_report_path", lambda t, s: rp)
    monkeypatch.setattr(G, "_profile_path", lambda t, s: tmp_path / "profile.json")
    monkeypatch.setattr(G, "_overrides_path", lambda t, s: tmp_path / "overrides.json")
    monkeypatch.setattr(G, "pdf_available", lambda engine="weasyprint": False)
    with pytest.raises(HTTPException) as ei:
        G.render_customized("t", "s", fmt="pdf")
    assert ei.value.status_code == 503
