"""R5 gate — editing with validation, override-audit and versioning.

Pure-transform tests (prose number-gate, override flag + audit, free text,
immutability, version bump) plus the API surface (version snapshotting, original
preserved, ``400`` on rejected edits) — endpoint functions called directly with
the stash directory monkeypatched.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from report_builder.generation import (
    apply_edit,
    bump_version,
    current_version,
    EditRejected,
)
from report_builder.binding import review as R
from api.report_builder_api import generate_phase_api as G


def _report():
    return {
        "metadata": {"reportId": "rpt_edit", "status": "draft",
                     "period": {"current": "2023-24"}},
        "analyticsAST": {
            "aggregations": [{"aggId": "a1", "questionId": "q_wpr_01",
                              "rows": [{"key": {"sector": "Rural"}, "value": 56.3},
                                       {"key": {"sector": "Urban"}, "value": 47.1}]}],
            "rankings": [],
            "metrics": [{"metricId": "m1", "questionId": "q_wpr_01",
                         "label": "All-India WPR", "value": 53.4}],
            "trends": [],
        },
        "contentAST": {"blocks": [
            {"blockId": "p_intro", "kind": "paragraph",
             "content": "WPR stood at 53.4%, with rural 56.3% above urban 47.1%.",
             "provenance": {"questionId": "q_wpr_01"}},
        ]},
        "figureAST": {"figures": [
            {"figureId": "fig_1", "caption": "WPR by Sector", "chartRef": "chart_1"},
        ]},
        "chartAST": {"charts": [
            {"chartId": "chart_1", "chartType": "grouped_bar", "biQuery": "q_wpr_01",
             "series": [{"label": "WPR", "points": [
                 {"x": "Rural", "y": 56.3}, {"x": "Urban", "y": 47.1}]}],
             "provenance": {"questionId": "q_wpr_01"}},
        ]},
        "tableAST": {"tables": [
            {"tableId": "tbl_state", "title": "By State", "biQuery": "q_wpr_02",
             "columns": [
                 {"columnId": "col_state", "header": "State", "role": "dimension"},
                 {"columnId": "col_v", "header": "WPR", "role": "measure",
                  "unit": "percent", "format": "percent.1"}],
             "rows": [{"col_state": "Himachal Pradesh", "col_v": 65.1,
                       "rowIds": ["r:state=HP"]}],
             "footnotes": [{"noteId": "fn_src", "text": "Source: PLFS."}],
             "provenance": {"questionId": "q_wpr_02"}},
        ]},
        "semanticAST": {"sections": [
            {"sectionId": "sec_wpr", "title": "Worker Population Ratio", "order": 1,
             "children": ["p_intro", "fig_1"]},
        ]},
    }


# ── prose edit (number gate) ──────────────────────────────────────────────────

def test_prose_edit_rejects_hallucinated_number():
    with pytest.raises(EditRejected):
        apply_edit(_report(), {"target": {"kind": "block", "id": "p_intro"},
                               "value": "WPR was actually 99.9%.", "by": "me"})


def test_prose_edit_accepts_supported_numbers():
    rep, audit = apply_edit(_report(), {
        "target": {"kind": "block", "id": "p_intro"},
        "value": "Rural WPR (56.3%) exceeded urban (47.1%).", "by": "officer"})
    assert rep["contentAST"]["blocks"][0]["content"].startswith("Rural WPR")
    assert audit["overridden"] is False
    assert audit["by"] == "officer"


def test_prose_edit_allows_stated_gap():
    # 9.2 = 56.3 − 47.1 is derivable ⇒ allowed.
    rep, _ = apply_edit(_report(), {
        "target": {"kind": "block", "id": "p_intro"},
        "value": "Rural exceeded urban by 9.2 percentage points.", "by": "me"})
    assert "9.2" in rep["contentAST"]["blocks"][0]["content"]


# ── number override ───────────────────────────────────────────────────────────

def test_number_override_requires_reason():
    with pytest.raises(EditRejected):
        apply_edit(_report(), {"target": {"kind": "table_cell", "id": "tbl_state",
                                          "col": "col_v", "rowIds": ["r:state=HP"]},
                               "value": 70.0, "by": "me"})


def test_table_cell_override_flags_and_audits():
    rep, audit = apply_edit(_report(), {
        "target": {"kind": "table_cell", "id": "tbl_state", "col": "col_v",
                   "rowIds": ["r:state=HP"]},
        "value": 70.0, "by": "officer", "reason": "revised post-validation"})
    row = rep["tableAST"]["tables"][0]["rows"][0]
    assert row["col_v"] == 70.0
    assert "col_v" in row["overridden"]
    assert audit["overridden"] is True
    assert audit["old"] == 65.1 and audit["new"] == 70.0
    assert audit["reason"] == "revised post-validation"
    assert rep["auditAST"]["humanReview"]["edits"][-1] == audit


def test_chart_point_override():
    rep, audit = apply_edit(_report(), {
        "target": {"kind": "chart_point", "id": "chart_1", "series": 0, "point": 1},
        "value": 50.0, "by": "me", "reason": "correction"})
    pt = rep["chartAST"]["charts"][0]["series"][0]["points"][1]
    assert pt["y"] == 50.0 and pt["overridden"] is True
    assert audit["overridden"] is True


# ── free text ─────────────────────────────────────────────────────────────────

def test_section_title_free_edit():
    rep, audit = apply_edit(_report(), {
        "target": {"kind": "section_title", "id": "sec_wpr"},
        "value": "Employment Indicators", "by": "me"})
    assert rep["semanticAST"]["sections"][0]["title"] == "Employment Indicators"
    assert audit["overridden"] is False


def test_caption_free_edit():
    rep, _ = apply_edit(_report(), {
        "target": {"kind": "figure_caption", "id": "fig_1"},
        "value": "Updated caption", "by": "me"})
    assert rep["figureAST"]["figures"][0]["caption"] == "Updated caption"


def test_edit_unknown_target_rejected():
    with pytest.raises(EditRejected):
        apply_edit(_report(), {"target": {"kind": "block", "id": "nope"},
                               "value": "x", "by": "me"})


def test_apply_edit_does_not_mutate_input():
    report = _report()
    snapshot = json.dumps(report, sort_keys=True)
    apply_edit(report, {"target": {"kind": "table_cell", "id": "tbl_state",
                                   "col": "col_v", "rowIds": ["r:state=HP"]},
                        "value": 70.0, "by": "me", "reason": "r"})
    assert json.dumps(report, sort_keys=True) == snapshot


# ── version helpers ───────────────────────────────────────────────────────────

def test_version_helpers():
    rep = _report()
    assert current_version(rep) == 1
    bump_version(rep, 4)
    assert current_version(rep) == 4


# ── API: versioning + audit ───────────────────────────────────────────────────

def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_DEFAULT_STORE", tmp_path)
    G._report_path("t", "s").write_text(json.dumps(_report()), encoding="utf-8")


def test_api_edit_snapshots_and_preserves_original(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    out = G.edit_report("t", "s", G.EditIn(
        target={"kind": "table_cell", "id": "tbl_state", "col": "col_v",
                "rowIds": ["r:state=HP"]},
        value=70.0, by="officer", reason="revised"))
    assert out.ok and out.version == 2
    assert G._list_versions("t", "s") == [1, 2]

    original = G.get_report("t", "s", version=1)
    assert original["tableAST"]["tables"][0]["rows"][0]["col_v"] == 65.1  # preserved

    current = G.get_report("t", "s")
    assert current["tableAST"]["tables"][0]["rows"][0]["col_v"] == 70.0
    assert current["metadata"]["version"] == 2


def test_api_versions_list_grows(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    G.edit_report("t", "s", G.EditIn(target={"kind": "section_title", "id": "sec_wpr"},
                                     value="Title A", by="me"))
    G.edit_report("t", "s", G.EditIn(target={"kind": "section_title", "id": "sec_wpr"},
                                     value="Title B", by="me"))
    info = G.get_versions("t", "s")
    assert info["versions"] == [1, 2, 3]
    assert info["current"] == 3


def test_api_edit_400_on_hallucinated_prose(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as ei:
        G.edit_report("t", "s", G.EditIn(target={"kind": "block", "id": "p_intro"},
                                         value="WPR was 99.9%.", by="me"))
    assert ei.value.status_code == 400
    # Rejected edit writes no versions.
    assert G._list_versions("t", "s") == []


def test_api_edit_400_on_missing_reason(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as ei:
        G.edit_report("t", "s", G.EditIn(
            target={"kind": "table_cell", "id": "tbl_state", "col": "col_v",
                    "rowIds": ["r:state=HP"]},
            value=70.0, by="me"))
    assert ei.value.status_code == 400


def test_api_report_version_404(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as ei:
        G.get_report("t", "s", version=99)
    assert ei.value.status_code == 404
