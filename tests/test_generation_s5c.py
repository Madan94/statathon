"""S5c gate tests — the assembler stitches subtrees into report.output.ast.json.

Covers: gold top-key shape + order, metadata/coverage computation, subtree
embedding, semanticAST carry-through, and the provenance validator (accepts a
traceable report; flags dangling evidenceRef, unresolved rowIds, and inconsistent
coverage). Runs an end-to-end S4→S5a→S5b→S5c chain on a synthetic frame.

Fully offline and deterministic.
"""
from __future__ import annotations

import pandas as pd

from report_builder.binding.schema import (
    BindingAST, BoundColumn, ColumnProfile, DatasetAST, EntityBinding,
    QuestionBinding, ResolvedRoles, ResolvedFilter,
)
from report_builder.generation.planner_adapter import build_plans
from report_builder.generation.executor import run_analytics
from report_builder.generation.filler import fill_visuals
from report_builder.generation.narrator import narrate
from report_builder.generation.assembler import (
    assemble_report, validate_report, SCHEMA_ID, TOP_KEYS,
)


# ── fixtures: a full template + binding + frame ───────────────────────────────

def _template() -> dict:
    return {
        "metadata": {"templateId": "tpl_wpr_v1"},
        "styleAST": {"styles": []},
        "semanticAST": {"sections": [{
            "sectionId": "sec_wpr", "title": "Worker Population Ratio", "level": 1,
            "order": 1, "topicRef": "topic_wpr",
            "children": ["p_wpr_intro", "fig_wpr_01", "table_wpr_state"]}]},
        "contentAST": {"blocks": [{
            "blockId": "p_wpr_intro", "kind": "paragraph", "styleRef": "s_body",
            "content": "", "biQuery": "q_wpr_01",
            "slot": {"fillFrom": "q_wpr_01_c1", "status": "empty"}}]},
        "chartAST": {"charts": [{
            "chartId": "chart_wpr_sector", "biQuery": "q_wpr_01", "chartType": "grouped_bar",
            "title": "WPR by Sector",
            "xAxis": {"entityRef": "ent_sector", "label": "Sector"},
            "yAxis": {"entityRef": "ent_wpr", "label": "WPR (%)", "unit": "percent"},
            "paletteRef": "pal_mospi_default", "series": [],
            "slot": {"fillFrom": "q_wpr_01_c2", "status": "empty"}}]},
        "figureAST": {"figures": [{
            "figureId": "fig_wpr_01", "templateRef": "ft_wpr_01",
            "caption": "WPR by Sector, {{period.current}}", "chartRef": "chart_wpr_sector",
            "styleRef": "s_caption", "slot": {"status": "empty"}}]},
        "tableAST": {"tables": [{
            "tableId": "table_wpr_state", "biQuery": "q_wpr_02", "title": "States by WPR",
            "columns": [
                {"columnId": "col_state", "header": "State/UT", "role": "dimension",
                 "entityRef": "ent_state", "align": "left"},
                {"columnId": "col_wpr", "header": "WPR", "role": "measure",
                 "entityRef": "ent_wpr", "unit": "percent", "align": "right"}],
            "rows": [], "slot": {"fillFrom": "q_wpr_02", "status": "empty"}}]},
    }


def _binding() -> BindingAST:
    return BindingAST(
        templateId="tpl_wpr_v1", datasetId="ds_test",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="WPR", entityType="measure",
                          columns=[BoundColumn(column="wpr")], status="confirmed"),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                          columns=[BoundColumn(column="sector")], status="confirmed"),
            EntityBinding(entityId="ent_state", entityName="State", entityType="dimension",
                          columns=[BoundColumn(column="state")], status="confirmed"),
        ],
        questionBindings=[
            QuestionBinding(questionId="q_wpr_01", status="executable",
                resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["sector"],
                    filters=[ResolvedFilter(column="age", op="ge", value=15)])),
            QuestionBinding(questionId="q_wpr_02", status="executable",
                resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["state"])),
        ],
    )


def _blueprint() -> dict:
    return {"entities": [
                {"entityId": "ent_wpr", "canonicalName": "Worker Population Ratio"},
                {"entityId": "ent_sector", "canonicalName": "Sector"},
                {"entityId": "ent_state", "canonicalName": "State/UT"}],
            "topics": [{"topicId": "topic_wpr", "questions": [
                {"questionId": "q_wpr_01", "questionType": "comparison",
                 "analyticsSpec": {"operation": "group_aggregate",
                                   "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                                   "groupBy": [{"entityRef": "ent_sector"}],
                                   "sort": {"by": "measure", "order": "desc"}},
                 "answerStructure": {"components": [{"componentId": "q_wpr_01_c1"}]}},
                {"questionId": "q_wpr_02", "questionType": "ranking",
                 "analyticsSpec": {"operation": "rank",
                                   "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                                   "groupBy": [{"entityRef": "ent_state"}],
                                   "sort": {"by": "measure", "order": "desc"}, "topN": 5},
                 "answerStructure": {"components": []}}]}]}


def _dataset() -> DatasetAST:
    return DatasetAST(datasetId="ds_test", rowCount=6, archetype="PLFS", columns=[
        ColumnProfile(name="wpr", dtype="number", role="measure"),
        ColumnProfile(name="sector", dtype="string", role="dimension"),
        ColumnProfile(name="state", dtype="string", role="dimension")])


def _frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"wpr": 56.3, "sector": "Rural", "state": "HP", "age": 30},
        {"wpr": 56.3, "sector": "Rural", "state": "SK", "age": 40},
        {"wpr": 47.1, "sector": "Urban", "state": "HP", "age": 25},
        {"wpr": 47.1, "sector": "Urban", "state": "SK", "age": 35}])


def _generate():
    """Run the whole generation chain and return (report, row_index, result)."""
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    template = _template()
    plans = build_plans(bp, binding, ds)
    a, e, row_index = run_analytics(plans, _frame(),
        question_meta={"q_wpr_01": {"label": "Worker Population Ratio"}})
    analytics, evidence = a.to_dict(), e.to_dict()
    context = {"period": {"current": "2023-24"}, "dataset": {"title": "Test PLFS"}}
    visuals = fill_visuals(template, analytics, evidence, context=context)
    narrated = narrate(template, analytics, evidence, context=context,
                       questions={"q_wpr_01": {"measureLabel": "Worker Population Ratio",
                                               "measureShort": "WPR", "dimensionNoun": "sector",
                                               "unit": "percent"}})
    report = assemble_report(template, datasetAST=ds, bindingAST=binding,
                             analyticsAST=analytics, evidenceAST=evidence, visuals=visuals,
                             contentAST=narrated["contentAST"], report_id="rpt_test_001",
                             period={"current": "2023-24", "prior": "2022-23", "delta": "yoy"})
    result = validate_report(report, row_index=row_index)
    return report, row_index, result


# ── shape ─────────────────────────────────────────────────────────────────────

def test_report_has_all_gold_top_keys_in_order():
    report, _, _ = _generate()
    assert list(report.keys()) == list(TOP_KEYS)
    assert report["$schema"] == SCHEMA_ID
    assert report["_doc"].startswith("GENERATED per run")


def test_metadata_and_coverage_computed():
    report, _, _ = _generate()
    md = report["metadata"]
    assert md["reportId"] == "rpt_test_001"
    assert md["templateId"] == "tpl_wpr_v1"
    assert md["blueprintRef"] == "tpl_wpr_v1"
    assert md["datasetRef"] == "ds_test"
    assert md["locale"] == "en-IN"
    assert md["period"] == {"current": "2023-24", "prior": "2022-23", "delta": "yoy"}
    assert md["status"] == "complete"
    cov = md["coverage"]
    assert cov["questionsTotal"] == 2
    assert cov["questionsAnswered"] == 2          # both executions ok
    assert cov["bindingsConfirmed"] == 3          # all entity bindings confirmed


def test_subtrees_embedded_and_semantic_carried_through():
    report, _, _ = _generate()
    assert report["datasetAST"]["datasetId"] == "ds_test"
    assert report["bindingAST"]["templateId"] == "tpl_wpr_v1"
    assert report["analyticsAST"]["aggregations"]
    assert report["evidenceAST"]["evidence"]
    assert report["contentAST"]["blocks"][0]["content"]      # narrated
    assert report["chartAST"]["charts"][0]["series"]         # filled
    assert report["tableAST"]["tables"][0]["rows"]           # filled
    # semanticAST is carried straight from the template
    assert report["semanticAST"]["sections"][0]["sectionId"] == "sec_wpr"


# ── validator: happy path ─────────────────────────────────────────────────────

def test_validator_accepts_fully_traceable_report():
    report, _, result = _generate()
    assert result["ok"] is True, result["errors"]
    assert result["errors"] == []
    assert result["stats"]["blocks"]["filled"] == result["stats"]["blocks"]["traced"]
    assert result["stats"]["chartPoints"]["filled"] == result["stats"]["chartPoints"]["traced"]
    assert result["stats"]["tableRows"]["filled"] == result["stats"]["tableRows"]["traced"]
    assert result["stats"]["chartPoints"]["filled"] == 2


# ── validator: failure detection ──────────────────────────────────────────────

def test_validator_flags_missing_top_key():
    report, _, _ = _generate()
    del report["evidenceAST"]
    result = validate_report(report)
    assert result["ok"] is False
    assert any("missing top-level key: evidenceAST" in e for e in result["errors"])


def test_validator_flags_dangling_evidence_ref():
    report, ridx, _ = _generate()
    report["contentAST"]["blocks"][0]["provenance"]["evidenceRef"] = "ev_does_not_exist"
    result = validate_report(report, row_index=ridx)
    assert result["ok"] is False
    assert any("missing evidenceRef ev_does_not_exist" in e for e in result["errors"])


def test_validator_flags_unresolved_chart_rowids():
    report, ridx, _ = _generate()
    report["chartAST"]["charts"][0]["series"][0]["points"][0]["rowIds"] = ["r:bogus"]
    result = validate_report(report, row_index=ridx)
    assert result["ok"] is False
    assert any("unresolved rowIds" in e for e in result["errors"])


def test_validator_flags_inconsistent_coverage():
    report, ridx, _ = _generate()
    report["metadata"]["coverage"]["questionsAnswered"] = 99
    result = validate_report(report, row_index=ridx)
    assert result["ok"] is False
    assert any("questionsAnswered exceeds questionsTotal" in e for e in result["errors"])


def test_validator_flags_evidence_missing_analytics_ref():
    report, ridx, _ = _generate()
    report["evidenceAST"]["evidence"][0]["analyticsRef"] = "agg_ghost"
    result = validate_report(report, row_index=ridx)
    assert result["ok"] is False
    assert any("missing analyticsRef agg_ghost" in e for e in result["errors"])


# ── assemble accepts plain dicts or objects ───────────────────────────────────

def test_assemble_accepts_plain_dicts():
    report, _, _ = _generate()
    # Re-assemble from plain dicts (not dataclasses) — must behave identically.
    again = assemble_report(
        {"metadata": {"templateId": "tpl_wpr_v1"}, "semanticAST": report["semanticAST"]},
        datasetAST=report["datasetAST"], bindingAST=report["bindingAST"],
        analyticsAST=report["analyticsAST"], evidenceAST=report["evidenceAST"],
        visuals={"tableAST": report["tableAST"], "chartAST": report["chartAST"],
                 "figureAST": report["figureAST"]},
        contentAST=report["contentAST"], report_id="rpt_again")
    assert list(again.keys()) == list(TOP_KEYS)
    assert again["metadata"]["reportId"] == "rpt_again"
    assert validate_report(again)["ok"] is True
