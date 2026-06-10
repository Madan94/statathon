"""Tests for the S4 execution coordinator (`coordinator.run_execution`).

Proves the correctness core — bundle → adapter → coordinator → normalize/formula/
physical — behaves to contract:
- a DIRECT plan produces exactly what the physical `run_analytics` produces;
- a SHARE plan routes to `formula_exec` (aggregate-then-divide, not a row-ratio mean);
- a `reported_value` plan never falls back to a silent mean;
- normalization runs *before* execution;
- a mixed bundle merges physical and formula outputs into one AST;
- a BLOCKED plan is refused (skipped), never softened;
- a DEGRADED plan's caveat is visible in the per-plan trace.
"""
from __future__ import annotations

import pandas as pd
import pytest

from report_builder.binding.execution_contracts import FormulaSpec, NormalizationPlan
from report_builder.generation.bundle_adapter import AdaptedPlan
from report_builder.generation.config import load_profile
from report_builder.generation.coordinator import (
    CoordinatorResult,
    run_execution,
    run_execution_detailed,
)
from report_builder.generation.executor import run_analytics
from report_builder.generation.schema import AnalyticsPlanRec, PlanMeasure


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _adapted(
    *,
    qid: str,
    measure: str = "",
    dims: list[str] | None = None,
    operation: str = "group_aggregate",
    agg: str = "sum",
    ftype: str = "DIRECT",
    num: str = "",
    den: str = "",
    multiplier: float = 1.0,
    base: float | None = None,
    time_col: str = "",
    time_window: dict | None = None,
    weight: str | None = None,
    filters: list[str] | None = None,
    normalization: NormalizationPlan | None = None,
    status: str = "EXECUTABLE",
    plan_id: str | None = None,
) -> AdaptedPlan:
    measure_col = measure or num
    rec = AnalyticsPlanRec(
        planId=plan_id or f"plan_{qid}",
        questionId=qid,
        operation=operation,
        measure=PlanMeasure(columnExpr=measure_col, agg=agg, weightColumn=weight),
        groupBy=list(dims or []),
        filters=list(filters or []),
        sort={"by": measure_col, "order": "desc"},
    )
    fs = FormulaSpec(
        type=ftype, numeratorColumn=num, denominatorColumn=den,
        multiplier=multiplier, baseValue=base, timeWindow=dict(time_window or {}),
        weightColumn=weight,
    )
    return AdaptedPlan(
        planRec=rec, questionId=qid, status=status, measureColumn=measure_col,
        formulaSpec=fs, normalizationPlan=normalization or NormalizationPlan(type="NONE"),
        timeColumn=time_col,
    )


def _agg_rows(analytics, agg_id: str) -> dict:
    for a in analytics.aggregations:
        if a.aggId == agg_id:
            return {tuple(r.key.values()): r.value for r in a.rows}
    raise AssertionError(f"aggregation {agg_id} not found")


# ─────────────────────────────────────────────────────────────────────────────
# 1. DIRECT path == old run_analytics
# ─────────────────────────────────────────────────────────────────────────────

def test_direct_path_equals_run_analytics():
    df = pd.DataFrame({
        "sal": [50000, 52000, 70000, 68000],
        "sector": ["Rural", "Rural", "Urban", "Urban"],
    })
    plan = _adapted(qid="q_sal", measure="sal", dims=["sector"], agg="mean")

    coord_a, coord_e, coord_ri = run_execution([plan], df)
    base_a, base_e, base_ri = run_analytics([plan.planRec], df)

    # Same analyticsAST + evidenceAST + row_index, value-for-value (ignoring the
    # non-deterministic per-execution `ms` timing).
    def _strip_ms(ast: dict) -> dict:
        for e in ast.get("executions", []):
            e["ms"] = 0
        return ast

    assert _strip_ms(coord_a.to_dict()) == _strip_ms(base_a.to_dict())
    assert coord_e.to_dict() == base_e.to_dict()
    assert coord_ri == base_ri


# ─────────────────────────────────────────────────────────────────────────────
# 2. SHARE routes to formula_exec (aggregate-then-divide)
# ─────────────────────────────────────────────────────────────────────────────

def test_share_routes_to_formula_exec():
    df = pd.DataFrame({
        "State": ["Kerala", "Kerala", "Bihar", "Bihar"],
        "literate": [90, 810, 30, 570],
        "population": [100, 900, 100, 900],
    })
    plan = _adapted(
        qid="q_lit", ftype="SHARE", num="literate", den="population",
        dims=["State"], multiplier=100.0,
    )
    detail = run_execution_detailed([plan], df, profile=load_profile("mospi"))
    assert isinstance(detail, CoordinatorResult)
    assert detail.outcomes[0].engine == "formula:SHARE"
    vals = _agg_rows(detail.analytics, "agg_q_lit")
    assert vals[("Kerala",)] == 90.0
    assert vals[("Bihar",)] == 60.0          # 600/1000×100, NOT 46.7 (mean of ratios)


# ─────────────────────────────────────────────────────────────────────────────
# 3. reported_value does not hit the mean fallback
# ─────────────────────────────────────────────────────────────────────────────

def test_reported_value_not_mean_fallback():
    df = pd.DataFrame({"State": ["A", "A"], "rate": [60.0, 70.0]})
    plan = _adapted(qid="q_r", measure="rate", dims=["State"], agg="reported_value")
    detail = run_execution_detailed([plan], df, profile=load_profile("default"))  # strict
    assert detail.outcomes[0].engine == "formula:DIRECT"   # routed to formula_exec
    vals = _agg_rows(detail.analytics, "agg_q_r")
    assert vals[("A",)] is None              # ambiguous, NOT 65.0 (the silent mean)
    assert detail.outcomes[0].status == "degraded"


# ─────────────────────────────────────────────────────────────────────────────
# 4. normalization runs before execution
# ─────────────────────────────────────────────────────────────────────────────

def test_normalization_runs_before_execution():
    # Wide table → melt to long → THEN aggregate the melted value column by member.
    df = pd.DataFrame({"State": ["A", "B"], "2020": [10, 20], "2021": [12, 22]})
    nplan = NormalizationPlan(
        type="WIDE_TO_LONG", idVars=["State"],
        valueVar="value", memberVar="year", memberLabels=["2020", "2021"],
    )
    plan = _adapted(
        qid="q_t", measure="value", dims=["year"], agg="sum", normalization=nplan,
    )
    detail = run_execution_detailed([plan], df)
    # Without the melt, "value"/"year" would not exist and the result would be empty.
    vals = _agg_rows(detail.analytics, "agg_q_t")
    assert vals[("2020",)] == 30.0           # 10 + 20
    assert vals[("2021",)] == 34.0           # 12 + 22
    assert detail.outcomes[0].status == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# 5. mixed bundle merges physical + formula outputs
# ─────────────────────────────────────────────────────────────────────────────

def test_mixed_bundle_merges_physical_and_formula():
    df = pd.DataFrame({
        "State": ["A", "A", "B", "B"],
        "sal": [100, 200, 300, 100],
        "literate": [90, 810, 30, 570],
        "population": [100, 900, 100, 900],
    })
    direct = _adapted(qid="q_sal", measure="sal", dims=["State"], agg="sum")
    share = _adapted(qid="q_lit", ftype="SHARE", num="literate", den="population",
                     dims=["State"], multiplier=100.0)
    detail = run_execution_detailed([direct, share], df, profile=load_profile("mospi"))

    engines = {o.questionId: o.engine for o in detail.outcomes}
    assert engines["q_sal"] == "pandas"
    assert engines["q_lit"] == "formula:SHARE"

    # both aggregations present in one merged AST
    sal = _agg_rows(detail.analytics, "agg_q_sal")
    lit = _agg_rows(detail.analytics, "agg_q_lit")
    assert sal[("A",)] == 300.0 and sal[("B",)] == 400.0
    assert lit[("A",)] == 90.0 and lit[("B",)] == 60.0
    # one plan + one execution recorded per question
    assert len(detail.analytics.plans) == 2
    assert {e.executionId for e in detail.analytics.executions} == {"exec_q_sal", "exec_q_lit"}
    # evidence merged for both
    assert {ev.questionId for ev in detail.evidence.evidence} == {"q_sal", "q_lit"}


# ─────────────────────────────────────────────────────────────────────────────
# 6. BLOCKED plan refused (skipped), never softened
# ─────────────────────────────────────────────────────────────────────────────

def test_blocked_plan_is_refused():
    df = pd.DataFrame({"State": ["A"], "n": [10]})
    plan = _adapted(qid="q_b", measure="n", dims=["State"], agg="sum", status="BLOCKED")
    detail = run_execution_detailed([plan], df)
    assert detail.outcomes[0].engine == "skipped"
    assert detail.outcomes[0].status == "blocked"
    # no values produced
    assert detail.analytics.aggregations == []
    assert detail.analytics.metrics == []
    # execution recorded as skipped (so it is not counted as answered downstream)
    assert detail.analytics.executions[0].status == "skipped"


# ─────────────────────────────────────────────────────────────────────────────
# 7. DEGRADED trace is visible
# ─────────────────────────────────────────────────────────────────────────────

def test_degraded_trace_visible():
    # SHARE with a zero denominator for group X → that group is None + a diagnostic.
    df = pd.DataFrame({"g": ["X", "Y"], "n": [5, 10], "d": [0, 50]})
    plan = _adapted(qid="q_d", ftype="SHARE", num="n", den="d", dims=["g"], multiplier=100.0)
    detail = run_execution_detailed([plan], df, profile=load_profile("mospi"))
    assert detail.outcomes[0].status == "degraded"
    assert any("denominator" in d.lower() for d in detail.outcomes[0].diagnostics)
    # flattened diagnostics carry the plan id for traceability
    assert any(d.startswith("plan_q_d") for d in detail.diagnostics)


# ─────────────────────────────────────────────────────────────────────────────
# 8. run_execution is a drop-in triple
# ─────────────────────────────────────────────────────────────────────────────

def test_run_execution_returns_triple():
    df = pd.DataFrame({"n": [1, 2, 3]})
    plan = _adapted(qid="q_m", measure="n", operation="metric", agg="sum")
    result = run_execution([plan], df)
    assert isinstance(result, tuple) and len(result) == 3
    analytics, evidence, row_index = result
    assert analytics.metrics[0].value == 6.0


# ─────────────────────────────────────────────────────────────────────────────
# 9. empty input → empty ASTs, no crash
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_plan_list():
    detail = run_execution_detailed([], pd.DataFrame({"a": [1]}))
    assert detail.analytics.plans == []
    assert detail.evidence.evidence == []
    assert detail.outcomes == []
