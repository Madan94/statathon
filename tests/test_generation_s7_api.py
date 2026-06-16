"""G7 gate tests — the generate-phase REST router (S4→S6 over HTTP).

Exercises the router functions directly (no live server) against a temporary,
self-contained binding stash + review record, using a controlled blueprint /
template / CSV so the test does not depend on the gold derived-measure binding.

Verifies: generate persists a valid report + HTML and returns the trace; the
report/report.html getters serve them; and the coverage-error gate blocks
generation. Fully offline.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi import HTTPException

from report_builder.binding import review as R
from report_builder.binding.review import ReviewRecord
from report_builder.binding.schema import (
    BindingAST, BoundColumn, ColumnProfile, DatasetAST, EntityBinding,
)
from api.report_builder_api import generate_phase_api as G
from api.report_builder_api.generate_phase_api import (
    GenerateIn, generate_report, get_report, get_report_html,
)

TEMPLATE_ID = "tpl_test_v1"
SIGNATURE = "sig_test_0001"


# ── controlled artifacts (consistent question id q_sal_01) ───────────────────

def _blueprint() -> dict:
    return {
        "metadata": {"title": "Test Survey"},
        "entities": [
            {"entityId": "ent_sal", "canonicalName": "Average Salary"},
            {"entityId": "ent_sector", "canonicalName": "Sector"}],
        "topics": [{"topicId": "topic_sal", "questions": [{
            "questionId": "q_sal_01", "intent": "Average salary by sector",
            "questionType": "comparison",
            "requiredEntities": [
                {"entityId": "ent_sal", "role": "measure", "required": True},
                {"entityId": "ent_sector", "role": "grouping", "required": True}],
            "analyticsSpec": {"operation": "group_aggregate",
                              "measure": {"entityRef": "ent_sal", "agg": "mean"},
                              "groupBy": [{"entityRef": "ent_sector"}],
                              "sort": {"by": "measure", "order": "desc"}},
            "answerStructure": {"components": [{"componentId": "q_sal_01_c1"}]}}]}],
    }


def _template_ast(template_id: str = "") -> dict:
    return {
        "metadata": {"templateId": TEMPLATE_ID},
        "semanticAST": {"sections": [{
            "sectionId": "sec_sal", "title": "Average Salary", "order": 1,
            "children": ["p_sal", "fig_sal", "table_sal"]}]},
        "contentAST": {"blocks": [{
            "blockId": "p_sal", "kind": "paragraph", "content": "", "biQuery": "q_sal_01",
            "slot": {"fillFrom": "q_sal_01_c1", "status": "empty"}}]},
        "chartAST": {"charts": [{
            "chartId": "chart_sal", "biQuery": "q_sal_01", "chartType": "grouped_bar",
            "xAxis": {"entityRef": "ent_sector", "label": "Sector"},
            "yAxis": {"entityRef": "ent_sal", "label": "Salary"},
            "series": [], "slot": {"fillFrom": "q_sal_01", "status": "empty"}}]},
        "figureAST": {"figures": [{
            "figureId": "fig_sal", "caption": "Salary by Sector, {{period.current}}",
            "chartRef": "chart_sal", "slot": {"status": "empty"}}]},
        "tableAST": {"tables": [{
            "tableId": "table_sal", "biQuery": "q_sal_01", "title": "Salary by Sector",
            "columns": [
                {"columnId": "col_sector", "header": "Sector", "role": "dimension"},
                {"columnId": "col_sal", "header": "Avg Salary", "role": "measure",
                 "format": "number.0"}],
            "rows": [], "slot": {"fillFrom": "q_sal_01", "status": "empty"}}]},
    }


def _dataset() -> DatasetAST:
    return DatasetAST(datasetId="ds_test", rowCount=6, archetype="survey", columns=[
        ColumnProfile(name="sal", dtype="number", role="measure"),
        ColumnProfile(name="sector", dtype="string", role="dimension")])


def _frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"sal": 50000, "sector": "Rural"}, {"sal": 52000, "sector": "Rural"},
        {"sal": 70000, "sector": "Urban"}, {"sal": 68000, "sector": "Urban"}])


def _entity_bindings() -> list[EntityBinding]:
    return [
        EntityBinding(entityId="ent_sal", entityName="Average Salary", entityType="measure",
                      columns=[BoundColumn(column="sal")], status="confirmed"),
        EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                      columns=[BoundColumn(column="sector")], status="confirmed"),
    ]


@pytest.fixture()
def stashed(tmp_path, monkeypatch):
    """Point the binding store at a temp dir and lay down a finalized session."""
    store = tmp_path / "bindings"
    store.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "_DEFAULT_STORE", store)
    # the router reads R._DEFAULT_STORE via its own _stash_path → picks up the patch.
    monkeypatch.setattr(G, "_load_template_ast", _template_ast)
    # Sandbox the freeze store too (the bundle factory freezes internally).
    from report_builder.binding import freeze_store
    monkeypatch.setattr(freeze_store, "FREEZE_DIR", store / "frozen")

    dataset, blueprint, df = _dataset(), _blueprint(), _frame()

    def _sp(suffix: str):
        return store / f"{TEMPLATE_ID}__{SIGNATURE}.{suffix}"

    _sp("dataset.json").write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
    _sp("blueprint.json").write_text(json.dumps(blueprint), encoding="utf-8")
    df.to_csv(_sp("data.csv"), index=False)

    record = ReviewRecord(
        templateId=TEMPLATE_ID, datasetSignature=SIGNATURE, datasetId="ds_test",
        proposals=[b.to_dict() for b in _entity_bindings()])
    R.save_record(record, storage_dir=store)
    return store


# ── generate ──────────────────────────────────────────────────────────────────

def test_generate_persists_valid_report_and_returns_trace(stashed):
    out = generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert out.valid is True, out.errors
    assert out.errors == []
    assert out.report_id.startswith("rpt_")
    assert out.coverage["questionsAnswered"] == 1
    assert out.coverage["questionsTotal"] == 1
    # narrative + fill traces surfaced for observability
    assert out.narrative_trace[0]["tier"] == "deterministic"
    assert any(t["kind"] == "chart" and t["status"] == "filled" for t in out.fill_trace)
    # artifacts persisted next to the stash
    assert (stashed / f"{TEMPLATE_ID}__{SIGNATURE}.report.output.ast.json").exists()
    assert (stashed / f"{TEMPLATE_ID}__{SIGNATURE}.report.html").exists()


def test_get_report_returns_assembled_ast(stashed):
    generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    report = get_report(TEMPLATE_ID, SIGNATURE)
    assert report["$schema"] == "bharatstat/report-output-ast/v1"
    assert report["contentAST"]["blocks"][0]["content"]            # narrated
    assert report["tableAST"]["tables"][0]["rows"]                 # filled
    # Urban avg (69000) > Rural avg (51000): chart sorted desc
    pts = report["chartAST"]["charts"][0]["series"][0]["points"]
    assert pts[0]["x"] == "Urban" and pts[0]["y"] == 69000.0


def test_get_report_html_served(stashed):
    generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    resp = get_report_html(TEMPLATE_ID, SIGNATURE)
    body = resp.body.decode("utf-8")
    assert body.startswith("<!DOCTYPE html>")
    assert "<svg" in body and "<table" in body
    assert "Average Salary" in body


# ── error paths ───────────────────────────────────────────────────────────────

def test_generate_missing_stash_409(tmp_path, monkeypatch):
    store = tmp_path / "empty"
    store.mkdir()
    monkeypatch.setattr(R, "_DEFAULT_STORE", store)
    with pytest.raises(HTTPException) as exc:
        generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert exc.value.status_code == 409


def test_get_report_before_generate_404(stashed):
    with pytest.raises(HTTPException) as exc:
        get_report(TEMPLATE_ID, SIGNATURE)
    assert exc.value.status_code == 404
