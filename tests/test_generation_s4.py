"""S4 gate tests — generation analytics core (plan adapter + executor).

Two tracks:
  1. SHAPE vs gold — the plan/aggregation/ranking/metric/evidence shapes match
     ``report_builder/gold_standard/report.output.ast.json`` field-for-field.
  2. MATH + PROVENANCE — on a synthetic PLFS-like frame the executor computes
     correct weighted ratios and every value carries non-empty ``rowIds``.

Fully offline and deterministic (no GPU, no LLM, no real microdata).
"""
from __future__ import annotations

import pandas as pd

from report_builder.binding.schema import (
    BindingAST,
    BoundColumn,
    ColumnProfile,
    DatasetAST,
    EntityBinding,
    QuestionBinding,
    ResolvedFilter,
    ResolvedRoles,
    ResolvedTime,
)
from report_builder.generation.planner_adapter import build_plan, build_plans
from report_builder.generation.executor import run_analytics


# ── fixtures ────────────────────────────────────────────────────────────────

def _binding() -> BindingAST:
    """A confirmed binding mapping WPR entities to a synthetic frame's columns."""
    return BindingAST(
        templateId="tpl_plfs_annual_v1",
        datasetId="ds_test",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="Worker Population Ratio",
                          entityType="measure", columns=[BoundColumn(column="wpr")]),
            EntityBinding(entityId="ent_sector", entityName="Sector",
                          entityType="dimension", columns=[BoundColumn(column="sector")]),
            EntityBinding(entityId="ent_state", entityName="State/UT",
                          entityType="dimension", columns=[BoundColumn(column="state")]),
            EntityBinding(entityId="ent_age_group", entityName="Age Group",
                          entityType="dimension", columns=[BoundColumn(column="age")]),
            EntityBinding(entityId="ent_period", entityName="Survey Period",
                          entityType="time", columns=[BoundColumn(column="period")]),
        ],
        questionBindings=[
            QuestionBinding(questionId="q_wpr_01", status="executable", resolvedRoles=ResolvedRoles(
                measures=["wpr"], dimensions=["sector"],
                filters=[ResolvedFilter(column="age", op="ge", value=15)],
                time=ResolvedTime(column="period", periods={"current": "2023-24"}, timeResolved=True))),
            QuestionBinding(questionId="q_wpr_02", status="executable", resolvedRoles=ResolvedRoles(
                measures=["wpr"], dimensions=["state"], filters=[], time=ResolvedTime())),
        ],
    )


def _dataset() -> DatasetAST:
    return DatasetAST(datasetId="ds_test", rowCount=8, archetype="PLFS", columns=[
        ColumnProfile(name="wpr", dtype="number", role="measure"),
        ColumnProfile(name="sector", dtype="string", role="dimension"),
        ColumnProfile(name="state", dtype="string", role="dimension"),
        ColumnProfile(name="age", dtype="number", role="dimension"),
        ColumnProfile(name="weight", dtype="number", role="measure"),
        ColumnProfile(name="period", dtype="string", role="time"),
    ])


def _blueprint() -> dict:
    spec_q1 = {
        "operation": "group_aggregate",
        "measure": {"entityRef": "ent_wpr", "agg": "weighted_ratio"},
        "groupBy": [{"entityRef": "ent_sector"}],
        "filters": [{"entityRef": "ent_age_group", "op": "eq", "valueFrom": "defaultMember"}],
        "sort": {"by": "measure", "order": "desc"},
        "topN": None,
    }
    spec_q2 = {
        "operation": "rank",
        "measure": {"entityRef": "ent_wpr", "agg": "weighted_ratio"},
        "groupBy": [{"entityRef": "ent_state"}],
        "filters": [],
        "sort": {"by": "measure", "order": "desc"},
        "topN": 10,
    }
    return {
        "entities": [
            {"entityId": "ent_wpr", "canonicalName": "Worker Population Ratio", "aliases": ["WPR"]},
            {"entityId": "ent_sector", "canonicalName": "Sector"},
            {"entityId": "ent_state", "canonicalName": "State/UT"},
        ],
        "topics": [{"topicId": "topic_wpr", "questions": [
            {"questionId": "q_wpr_01", "intent": "Compare WPR across sector.",
             "questionType": "comparison", "analyticsSpec": spec_q1,
             "answerStructure": {"components": [{"componentId": "q_wpr_01_c1"}]}},
            {"questionId": "q_wpr_02", "intent": "Rank States by WPR.",
             "questionType": "ranking", "analyticsSpec": spec_q2,
             "answerStructure": {"components": [{"componentId": "q_wpr_02_c1"}]}},
        ]}],
    }


def _frame() -> pd.DataFrame:
    # Rural rows weight-average to a higher WPR than Urban; one row is age<15 (filtered).
    return pd.DataFrame([
        {"wpr": 60.0, "sector": "Rural", "state": "HP", "age": 30, "weight": 2.0, "period": "2023-24"},
        {"wpr": 50.0, "sector": "Rural", "state": "HP", "age": 40, "weight": 1.0, "period": "2023-24"},
        {"wpr": 40.0, "sector": "Urban", "state": "HP", "age": 25, "weight": 1.0, "period": "2023-24"},
        {"wpr": 50.0, "sector": "Urban", "state": "SK", "age": 35, "weight": 1.0, "period": "2023-24"},
        {"wpr": 70.0, "sector": "Rural", "state": "SK", "age": 50, "weight": 1.0, "period": "2023-24"},
        {"wpr": 99.0, "sector": "Rural", "state": "HP", "age": 10, "weight": 5.0, "period": "2023-24"},
    ])


# ── G1: plan adapter shape ──────────────────────────────────────────────────

def test_plan_matches_gold_group_aggregate_shape():
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    q = bp["topics"][0]["questions"][0]
    plan = build_plan(q, binding.questionBindings[0], binding, ds, blueprint_entities=bp["entities"]).to_dict()
    assert plan["planId"] == "plan_q_wpr_01"
    assert plan["questionId"] == "q_wpr_01"
    assert plan["operation"] == "group_aggregate"
    assert plan["measure"]["columnExpr"] == "wpr"
    assert plan["measure"]["agg"] == "weighted_ratio"
    assert plan["measure"]["weightColumn"] == "weight"      # found from datasetAST
    assert plan["groupBy"] == ["sector"]
    assert plan["filters"] == ["age>=15"]                   # resolved filter rendered
    assert plan["sort"] == {"by": "wpr", "order": "desc"}    # "measure" → measure column


def test_plan_matches_gold_rank_shape():
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    q = bp["topics"][0]["questions"][1]
    plan = build_plan(q, binding.questionBindings[1], binding, ds, blueprint_entities=bp["entities"]).to_dict()
    assert plan["operation"] == "rank"
    assert plan["groupBy"] == ["state"]
    assert plan["topN"] == 10
    assert plan["filters"] == []


def test_build_plans_skips_blocked_questions():
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    binding.questionBindings[1].status = "blocked"
    plans = build_plans(bp, binding, ds)
    assert [p.questionId for p in plans] == ["q_wpr_01"]


def test_entity_name_reference_is_normalized_to_id():
    """A noisy blueprint that refers to a measure by NAME still resolves to a column."""
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    q = bp["topics"][0]["questions"][0]
    q["analyticsSpec"]["measure"]["entityRef"] = "Worker Population Ratio"  # name, not id
    # drop the resolvedRoles measure so the adapter must use the spec path
    qb = binding.questionBindings[0]
    qb.resolvedRoles.measures = []
    plan = build_plan(q, qb, binding, ds, blueprint_entities=bp["entities"]).to_dict()
    assert plan["measure"]["columnExpr"] == "wpr"


# ── G2: executor math + provenance + gold rollup shapes ─────────────────────

def test_group_aggregate_weighted_ratio_and_provenance():
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    plans = build_plans(bp, binding, ds)
    analytics, evidence, row_index = run_analytics(plans, _frame(),
                                                   question_meta={"q_wpr_01": {"label": "All-India WPR"}})
    a = analytics.to_dict()
    # one aggregation for q_wpr_01, grouped by sector, age<15 row excluded
    agg = next(x for x in a["aggregations"] if x["questionId"] == "q_wpr_01")
    assert agg["aggId"] == "agg_q_wpr_01"
    assert agg["groupBy"] == "sector"
    assert agg["measure"] == "wpr"
    rural = next(r for r in agg["rows"] if r["key"]["sector"] == "Rural")
    # Rural weighted ratio = (60*2 + 50*1 + 70*1)/(2+1+1)*100/100 = 240/4 = 60.0
    assert rural["value"] == 60.0
    assert rural["n"] == 3                                   # age<15 row dropped
    assert rural["rowIds"] == ["r:sector=Rural"]
    # provenance index resolves the token to concrete rows
    assert row_index["r:sector=Rural"]
    # rows sorted desc by value → Rural (60) before Urban (45)
    assert agg["rows"][0]["key"]["sector"] == "Rural"


def test_group_aggregate_emits_executions_and_evidence():
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    plans = build_plans(bp, binding, ds)
    analytics, evidence, _ = run_analytics(plans, _frame())
    a, e = analytics.to_dict(), evidence.to_dict()
    ex = next(x for x in a["executions"] if x["executionId"] == "exec_q_wpr_01")
    assert ex["planRef"] == "plan_q_wpr_01"
    assert ex["status"] == "ok"
    assert ex["rowsScanned"] == 5                            # 6 rows − 1 age<15
    ev = next(x for x in e["evidence"] if x["questionId"] == "q_wpr_01")
    assert ev["kind"] == "aggregation"
    assert ev["analyticsRef"] == "agg_q_wpr_01"
    assert ev["rowIds"]                                      # non-empty provenance
    assert ev["computation"] == "weighted_ratio"
    assert ev["confidence"] > 0.5


def test_rank_orders_states_with_rowids():
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    plans = build_plans(bp, binding, ds)
    analytics, _, _ = run_analytics(plans, _frame())
    a = analytics.to_dict()
    ranking = next(x for x in a["rankings"] if x["questionId"] == "q_wpr_02")
    assert ranking["rankId"] == "rank_q_wpr_02"
    assert ranking["order"] == "desc"
    assert ranking["items"][0]["rank"] == 1
    assert all(it["rowIds"] for it in ranking["items"])
    # ranks are strictly increasing
    assert [it["rank"] for it in ranking["items"]] == list(range(1, len(ranking["items"]) + 1))


def test_every_executable_question_yields_value_with_rowids():
    """The core invariant: no executable question produces a value without provenance."""
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    plans = build_plans(bp, binding, ds)
    analytics, evidence, _ = run_analytics(plans, _frame())
    e = evidence.to_dict()
    qids = {ev["questionId"] for ev in e["evidence"]}
    assert qids == {"q_wpr_01", "q_wpr_02"}
    for ev in e["evidence"]:
        assert ev["value"] is not None
        assert ev["rowIds"], f"{ev['questionId']} has no rowIds"


def test_missing_filter_column_widens_not_errors():
    """A filter on an absent column is skipped (widen), lowering confidence not crashing."""
    bp, binding, ds = _blueprint(), _binding(), _dataset()
    binding.questionBindings[0].resolvedRoles.filters = [ResolvedFilter(column="nonexistent", op="eq", value="X")]
    plans = build_plans(bp, binding, ds)
    analytics, evidence, _ = run_analytics(plans, _frame())
    a = analytics.to_dict()
    ex = next(x for x in a["executions"] if x["executionId"] == "exec_q_wpr_01")
    assert ex["status"] == "ok"
    assert ex["rowsScanned"] == 6                            # nothing filtered
    ev = next(x for x in evidence.to_dict()["evidence"] if x["questionId"] == "q_wpr_01")
    assert ev["confidence"] < 0.95                           # penalised for widening


def test_real_mock_csv_smoke():
    """The core runs on the real mock MoSPI CSV (real file, real dtypes) and
    yields aggregations + metrics with provenance for a sal-by-sector question."""
    import pathlib

    csv = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw_uploads" / \
        "sess_9722157d_mospi_mock_survey_data.csv"
    if not csv.exists():
        import pytest
        pytest.skip("mock CSV not present")
    df = pd.read_csv(csv)

    binding = BindingAST(
        templateId="tpl_mock", datasetId="ds_mock",
        entityBindings=[
            EntityBinding(entityId="ent_sal", entityName="Salary", entityType="measure",
                          columns=[BoundColumn(column="sal")]),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                          columns=[BoundColumn(column="sector")]),
        ],
        questionBindings=[QuestionBinding(questionId="q_sal_01", status="executable",
                          resolvedRoles=ResolvedRoles(measures=["sal"], dimensions=["sector"]))],
    )
    blueprint = {
        "entities": [{"entityId": "ent_sal", "canonicalName": "Salary"},
                     {"entityId": "ent_sector", "canonicalName": "Sector"}],
        "topics": [{"topicId": "t1", "questions": [{
            "questionId": "q_sal_01", "intent": "Average salary by sector",
            "questionType": "comparison",
            "analyticsSpec": {"operation": "group_aggregate",
                              "measure": {"entityRef": "ent_sal", "agg": "mean"},
                              "groupBy": [{"entityRef": "ent_sector"}], "filters": [],
                              "sort": {"by": "measure", "order": "desc"}},
            "answerStructure": {"components": [{"componentId": "q_sal_01_c1"}]}}]}],
    }
    plans = build_plans(blueprint, binding, None)
    analytics, evidence, row_index = run_analytics(plans, df)
    a = analytics.to_dict()
    agg = next(x for x in a["aggregations"] if x["questionId"] == "q_sal_01")
    assert {r["key"]["sector"] for r in agg["rows"]} == {"Rural", "Urban"}
    assert all(r["value"] is not None and r["rowIds"] for r in agg["rows"])
    assert all(row_index[tok] for r in agg["rows"] for tok in r["rowIds"])


def test_gold_schema_roundtrip_stability():
    """The produced ASTs round-trip through from_dict/to_dict unchanged."""
    from report_builder.generation.schema import AnalyticsAST, EvidenceAST

    bp, binding, ds = _blueprint(), _binding(), _dataset()
    plans = build_plans(bp, binding, ds)
    analytics, evidence, _ = run_analytics(plans, _frame())
    ad, ed = analytics.to_dict(), evidence.to_dict()
    assert AnalyticsAST.from_dict(ad).to_dict() == ad
    assert EvidenceAST.from_dict(ed).to_dict() == ed
