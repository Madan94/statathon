"""S5a gate tests — the filler pours analytics values into template slots.

Covers chart fill (1-D aggregation → points), flat table fill (ranking → rows),
pivot table fill (2-key aggregation → rural/urban columns), figure caption +
slot status, footnote template rendering, and provenance/rowIds carry-through.

Fully offline and deterministic.
"""
from __future__ import annotations

import pandas as pd

from report_builder.binding.schema import (
    BindingAST, BoundColumn, ColumnProfile, DatasetAST, EntityBinding,
    QuestionBinding, ResolvedRoles,
)
from report_builder.generation.planner_adapter import build_plan, build_plans
from report_builder.generation.executor import run_analytics
from report_builder.generation.filler import fill_visuals


# ── template AST fixtures (value-free slots, like template.ast.json) ─────────

def _chart_template() -> dict:
    return {"charts": [{
        "chartId": "chart_wpr_sector", "biQuery": "q_wpr_01", "chartType": "grouped_bar",
        "title": "WPR by Sector",
        "xAxis": {"entityRef": "ent_sector", "label": "Sector"},
        "yAxis": {"entityRef": "ent_wpr", "label": "WPR (%)", "unit": "percent"},
        "paletteRef": "pal_mospi_default", "series": [],
        "slot": {"fillFrom": "q_wpr_01_c2", "status": "empty"},
    }]}


def _figure_template() -> dict:
    return {"figures": [{
        "figureId": "fig_wpr_01", "templateRef": "ft_wpr_01",
        "caption": "Worker Population Ratio by Sector, {{period.current}}",
        "chartRef": "chart_wpr_sector", "styleRef": "s_caption",
        "slot": {"status": "empty"},
    }]}


def _flat_table_template() -> dict:
    return {"tables": [{
        "tableId": "table_state_rank", "biQuery": "q_rank_01",
        "title": "States by WPR",
        "columns": [
            {"columnId": "col_state", "header": "State/UT", "role": "dimension",
             "entityRef": "ent_state", "align": "left"},
            {"columnId": "col_wpr", "header": "WPR", "role": "measure",
             "entityRef": "ent_wpr", "unit": "percent", "format": "percent.1", "align": "right"},
        ],
        "rows": [],
        "footnotes": [{"noteId": "fn_src", "text": "",
                       "textTemplate": "Source: {{dataset.title}}, {{period.current}}."}],
        "slot": {"fillFrom": "q_rank_01", "status": "empty"},
    }]}


def _pivot_table_template() -> dict:
    return {"tables": [{
        "tableId": "table_wpr_state", "biQuery": "q_pivot_01",
        "title": "WPR by State and Sector",
        "columnGroups": [
            {"groupId": "grp_rural", "label": "Rural", "spanRefs": ["col_rural"]},
            {"groupId": "grp_urban", "label": "Urban", "spanRefs": ["col_urban"]},
        ],
        "columns": [
            {"columnId": "col_state", "header": "State/UT", "role": "dimension",
             "entityRef": "ent_state", "align": "left"},
            {"columnId": "col_rural", "header": "Rural", "role": "measure",
             "entityRef": "ent_wpr", "group": "grp_rural", "unit": "percent", "align": "right"},
            {"columnId": "col_urban", "header": "Urban", "role": "measure",
             "entityRef": "ent_wpr", "group": "grp_urban", "unit": "percent", "align": "right"},
        ],
        "rows": [],
        "slot": {"fillFrom": "q_pivot_01", "status": "empty"},
    }]}


# ── analytics fixtures (the executor output the filler consumes) ─────────────

def _sector_binding() -> BindingAST:
    return BindingAST(
        templateId="t", datasetId="d",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="WPR", entityType="measure",
                          columns=[BoundColumn(column="wpr")]),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                          columns=[BoundColumn(column="sector")]),
        ],
        questionBindings=[QuestionBinding(questionId="q_wpr_01", status="executable",
                          resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["sector"]))],
    )


def _sector_blueprint() -> dict:
    return {"entities": [{"entityId": "ent_wpr", "canonicalName": "WPR"},
                         {"entityId": "ent_sector", "canonicalName": "Sector"}],
            "topics": [{"topicId": "t", "questions": [{
                "questionId": "q_wpr_01", "intent": "WPR by sector", "questionType": "comparison",
                "analyticsSpec": {"operation": "group_aggregate",
                                  "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                                  "groupBy": [{"entityRef": "ent_sector"}],
                                  "sort": {"by": "measure", "order": "desc"}},
                "answerStructure": {"components": [{"componentId": "q_wpr_01_c1"}]}}]}]}


def _sector_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"wpr": 56.3, "sector": "Rural"}, {"wpr": 56.3, "sector": "Rural"},
        {"wpr": 47.1, "sector": "Urban"}, {"wpr": 47.1, "sector": "Urban"},
    ])


def _sector_analytics():
    bp, binding = _sector_blueprint(), _sector_binding()
    plans = build_plans(bp, binding, None)
    analytics, evidence, _ = run_analytics(plans, _sector_frame())
    return analytics.to_dict(), evidence.to_dict()


# ── chart fill ───────────────────────────────────────────────────────────────

def test_chart_fill_points_colors_and_provenance():
    analytics, evidence = _sector_analytics()
    out = fill_visuals({"chartAST": _chart_template()}, analytics, evidence)
    chart = out["chartAST"]["charts"][0]
    assert chart["slot"]["status"] == "filled"
    pts = chart["series"][0]["points"]
    assert [p["x"] for p in pts] == ["Rural", "Urban"]      # sorted desc by value
    assert pts[0]["y"] == 56.3 and pts[1]["y"] == 47.1
    assert all(p["color"].startswith("#") for p in pts)
    assert pts[0]["rowIds"] == ["r:sector=Rural"]
    assert chart["provenance"] == {"questionId": "q_wpr_01",
                                   "analyticsRef": "agg_q_wpr_01",
                                   "evidenceRef": "ev_q_wpr_01"}


def test_chart_empty_when_no_analytics():
    out = fill_visuals({"chartAST": _chart_template()}, {"aggregations": []}, {"evidence": []})
    chart = out["chartAST"]["charts"][0]
    assert chart["slot"]["status"] == "empty"
    assert chart["series"] == []


# ── figure fill ──────────────────────────────────────────────────────────────

def test_figure_caption_rendered_and_status_follows_chart():
    analytics, evidence = _sector_analytics()
    template = {"chartAST": _chart_template(), "figureAST": _figure_template()}
    out = fill_visuals(template, analytics, evidence,
                       context={"period": {"current": "2023-24"}})
    fig = out["figureAST"]["figures"][0]
    assert fig["caption"] == "Worker Population Ratio by Sector, 2023-24"
    assert fig["slot"]["status"] == "filled"


# ── flat table fill ──────────────────────────────────────────────────────────

def test_flat_table_fill_from_ranking():
    # Build a ranking analytics for q_rank_01 (states by wpr).
    binding = BindingAST(templateId="t", datasetId="d",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="WPR", entityType="measure",
                          columns=[BoundColumn(column="wpr")]),
            EntityBinding(entityId="ent_state", entityName="State", entityType="dimension",
                          columns=[BoundColumn(column="state")]),
        ],
        questionBindings=[QuestionBinding(questionId="q_rank_01", status="executable",
                          resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["state"]))])
    bp = {"entities": [], "topics": [{"topicId": "t", "questions": [{
        "questionId": "q_rank_01", "questionType": "ranking",
        "analyticsSpec": {"operation": "rank",
                          "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                          "groupBy": [{"entityRef": "ent_state"}],
                          "sort": {"by": "measure", "order": "desc"}, "topN": 5},
        "answerStructure": {"components": []}}]}]}
    frame = pd.DataFrame([
        {"wpr": 65.1, "state": "HP"}, {"wpr": 63.0, "state": "SK"}, {"wpr": 50.0, "state": "MH"}])
    plans = build_plans(bp, binding, None)
    analytics, evidence, _ = run_analytics(plans, frame)

    out = fill_visuals({"tableAST": _flat_table_template()},
                       analytics.to_dict(), evidence.to_dict(),
                       context={"dataset": {"title": "PLFS 2023-24"}, "period": {"current": "2023-24"}})
    table = out["tableAST"]["tables"][0]
    assert table["slot"]["status"] == "filled"
    assert table["rows"][0] == {"col_state": "HP", "col_wpr": 65.1, "rowIds": ["r:state=HP"]}
    assert table["rows"][0]["col_wpr"] >= table["rows"][1]["col_wpr"]   # ranked desc
    # footnote textTemplate rendered from context
    assert table["footnotes"][0]["text"] == "Source: PLFS 2023-24, 2023-24."
    assert table["provenance"]["analyticsRef"] == "rank_q_rank_01"


# ── pivot table fill (the real MoSPI rural/urban shape) ──────────────────────

def test_pivot_table_fill_state_by_sector():
    binding = BindingAST(templateId="t", datasetId="d",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="WPR", entityType="measure",
                          columns=[BoundColumn(column="wpr")]),
            EntityBinding(entityId="ent_state", entityName="State", entityType="dimension",
                          columns=[BoundColumn(column="state")]),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                          columns=[BoundColumn(column="sector")]),
        ],
        questionBindings=[QuestionBinding(questionId="q_pivot_01", status="executable",
                          resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["state", "sector"]))])
    bp = {"entities": [], "topics": [{"topicId": "t", "questions": [{
        "questionId": "q_pivot_01", "questionType": "comparison",
        "analyticsSpec": {"operation": "group_aggregate",
                          "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                          "groupBy": [{"entityRef": "ent_state"}, {"entityRef": "ent_sector"}],
                          "sort": {"by": "measure", "order": "desc"}},
        "answerStructure": {"components": []}}]}]}
    frame = pd.DataFrame([
        {"wpr": 65.1, "state": "HP", "sector": "Rural"},
        {"wpr": 54.0, "state": "HP", "sector": "Urban"},
        {"wpr": 63.0, "state": "SK", "sector": "Rural"},
        {"wpr": 58.2, "state": "SK", "sector": "Urban"}])
    plans = build_plans(bp, binding, None)
    analytics, evidence, _ = run_analytics(plans, frame)

    out = fill_visuals({"tableAST": _pivot_table_template()},
                       analytics.to_dict(), evidence.to_dict())
    table = out["tableAST"]["tables"][0]
    assert table["slot"]["status"] == "filled"
    by_state = {r["col_state"]: r for r in table["rows"]}
    assert by_state["HP"]["col_rural"] == 65.1
    assert by_state["HP"]["col_urban"] == 54.0
    assert by_state["SK"]["col_rural"] == 63.0
    assert by_state["SK"]["col_urban"] == 58.2
    # both contributing rowIds carried onto the pivoted row
    assert set(by_state["HP"]["rowIds"]) == {"r:state=HP,sector=Rural", "r:state=HP,sector=Urban"}


def test_multi_groupby_aggregation_has_composite_keys():
    binding = BindingAST(templateId="t", datasetId="d",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="WPR", entityType="measure",
                          columns=[BoundColumn(column="wpr")]),
            EntityBinding(entityId="ent_state", entityName="State", entityType="dimension",
                          columns=[BoundColumn(column="state")]),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                          columns=[BoundColumn(column="sector")]),
        ],
        questionBindings=[QuestionBinding(questionId="q_pivot_01", status="executable",
                          resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["state", "sector"]))])
    bp = {"entities": [], "topics": [{"topicId": "t", "questions": [{
        "questionId": "q_pivot_01", "questionType": "comparison",
        "analyticsSpec": {"operation": "group_aggregate",
                          "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                          "groupBy": [{"entityRef": "ent_state"}, {"entityRef": "ent_sector"}]},
        "answerStructure": {"components": []}}]}]}
    frame = pd.DataFrame([
        {"wpr": 65.1, "state": "HP", "sector": "Rural"},
        {"wpr": 54.0, "state": "HP", "sector": "Urban"}])
    plans = build_plans(bp, binding, None)
    analytics, _, _ = run_analytics(plans, frame)
    agg = analytics.to_dict()["aggregations"][0]
    assert agg["groupBy"] == ["state", "sector"]
    assert agg["rows"][0]["key"] == {"state": "HP", "sector": "Rural"}
    assert agg["rows"][0]["rowIds"] == ["r:state=HP,sector=Rural"]
