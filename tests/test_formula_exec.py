"""Tests for the gold formula executor (`formula_exec`).

This is the math the frozen physical-column executor cannot do: SHARE / RATE /
RATIO / GROWTH / CAGR / INDEX / DIFFERENCE and deterministic `reported_value`.
The non-negotiable invariants exercised here:

* SHARE/RATE/RATIO aggregate numerator and denominator **at the same grain, then
  divide** — never the mean of per-row ratios.
* `reported_value` is **never** a silent `mean()`: single→use, equal→use,
  differing→ambiguous (None) unless a weighted policy + valid weight reconciles it.
* A zero denominator yields `None` for that group with a diagnostic — it never crashes.
* A defensively-seen BLOCKED shape (missing denominator/base/timeWindow) is **refused**,
  not softened into a runnable number.
"""
from __future__ import annotations

import pandas as pd
import pytest

from report_builder.binding.execution_contracts import FormulaSpec
from report_builder.generation.bundle_adapter import AdaptedPlan
from report_builder.generation.config import GenerationConfig, load_profile
from report_builder.generation.formula_exec import FormulaResult, compute_formula
from report_builder.generation.registry import FormulaRegistry
from report_builder.generation.schema import AnalyticsPlanRec, PlanMeasure


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _adapted(
    *,
    qid: str,
    num: str = "",
    den: str = "",
    measure: str = "",
    dims: list[str] | None = None,
    operation: str = "group_aggregate",
    ftype: str = "DIRECT",
    agg: str = "sum",
    multiplier: float = 1.0,
    base: float | None = None,
    time_col: str = "",
    time_window: dict | None = None,
    weight: str | None = None,
    filters: list[str] | None = None,
    top_n: int | None = None,
    status: str = "EXECUTABLE",
) -> AdaptedPlan:
    measure_col = measure or num
    fs = FormulaSpec(
        type=ftype,
        numeratorColumn=num,
        denominatorColumn=den,
        multiplier=multiplier,
        baseValue=base,
        timeWindow=dict(time_window or {}),
        weightColumn=weight,
    )
    rec = AnalyticsPlanRec(
        planId=f"plan_{qid}",
        questionId=qid,
        operation=operation,
        measure=PlanMeasure(columnExpr=measure_col, agg=agg, weightColumn=weight),
        groupBy=list(dims or []),
        filters=list(filters or []),
        sort={"by": measure_col, "order": "desc"},
        topN=top_n,
    )
    return AdaptedPlan(
        planRec=rec,
        questionId=qid,
        status=status,
        measureColumn=measure_col,
        formulaSpec=fs,
        timeColumn=time_col,
    )


def _agg_by_key(result: FormulaResult, col: str) -> dict:
    assert result.aggregations, "expected at least one aggregation"
    return {r.key[col]: r.value for r in result.aggregations[0].rows}


# ─────────────────────────────────────────────────────────────────────────────
# SHARE — aggregate-then-divide (the canonical MoSPI distribution)
# ─────────────────────────────────────────────────────────────────────────────

class TestShare:
    def test_share_aggregates_then_divides_never_averages_row_ratios(self):
        # Bihar's two rows have ratios 0.30 and 0.6333; their mean (×100 = 46.7)
        # is the WRONG answer. The right answer aggregates first: 600/1000 = 60.0.
        df = pd.DataFrame({
            "State": ["Kerala", "Kerala", "Bihar", "Bihar"],
            "literate": [90, 810, 30, 570],
            "population": [100, 900, 100, 900],
        })
        plan = _adapted(
            qid="q_lit", ftype="SHARE", num="literate", den="population",
            dims=["State"], multiplier=100.0,
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        vals = _agg_by_key(res, "State")
        assert vals["Kerala"] == 90.0
        assert vals["Bihar"] == 60.0          # 600/1000×100, NOT 46.7 (mean of ratios)
        assert res.status == "ok"

    def test_share_overall_metric_uses_grand_totals(self):
        df = pd.DataFrame({
            "State": ["Kerala", "Bihar"],
            "literate": [900, 600],
            "population": [1000, 1000],
        })
        plan = _adapted(
            qid="q_lit", ftype="SHARE", num="literate", den="population",
            dims=["State"], multiplier=100.0,
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        assert res.metrics, "SHARE with groups should also surface an overall metric"
        assert res.metrics[0].value == 75.0   # 1500/2000×100

    def test_share_default_multiplier_from_profile_when_spec_is_one(self):
        df = pd.DataFrame({"g": ["A"], "n": [1], "d": [4]})
        plan = _adapted(qid="q", ftype="SHARE", num="n", den="d", dims=["g"], multiplier=1.0)
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        # multiplier defaults to 100 (share) → 1/4×100 = 25.0
        assert _agg_by_key(res, "g")["A"] == 25.0

    def test_share_zero_denominator_is_none_with_diagnostic_not_crash(self):
        df = pd.DataFrame({"g": ["X", "Y"], "n": [5, 10], "d": [0, 50]})
        plan = _adapted(qid="q", ftype="SHARE", num="n", den="d", dims=["g"], multiplier=100.0)
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        vals = _agg_by_key(res, "g")
        assert vals["X"] is None              # 5/0 → None, never inf/crash
        assert vals["Y"] == 20.0
        assert res.status == "degraded"
        assert any("denominator" in d.lower() for d in res.diagnostics)


# ─────────────────────────────────────────────────────────────────────────────
# reported_value — deterministic, never a silent mean
# ─────────────────────────────────────────────────────────────────────────────

class TestReportedValue:
    def test_single_value_used(self):
        df = pd.DataFrame({"State": ["A"], "rate": [42.0]})
        plan = _adapted(qid="q", ftype="DIRECT", measure="rate", dims=["State"], agg="reported_value")
        res = compute_formula(plan, df, profile=load_profile("default"))
        assert _agg_by_key(res, "State")["A"] == 42.0

    def test_equal_values_used(self):
        df = pd.DataFrame({"State": ["A", "A"], "rate": [50.0, 50.0]})
        plan = _adapted(qid="q", ftype="DIRECT", measure="rate", dims=["State"], agg="reported_value")
        res = compute_formula(plan, df, profile=load_profile("default"))
        assert _agg_by_key(res, "State")["A"] == 50.0

    def test_differing_values_strict_is_ambiguous_not_mean(self):
        df = pd.DataFrame({"State": ["A", "A"], "rate": [60.0, 70.0]})
        plan = _adapted(qid="q", ftype="DIRECT", measure="rate", dims=["State"], agg="reported_value")
        res = compute_formula(plan, df, profile=load_profile("default"))   # strict
        assert _agg_by_key(res, "State")["A"] is None    # NOT 65.0 (the silent mean)
        assert res.status == "degraded"
        assert any("reported" in d.lower() or "ambiguous" in d.lower() for d in res.diagnostics)

    def test_differing_values_weighted_policy_reconciles(self):
        df = pd.DataFrame({"State": ["A", "A"], "rate": [60.0, 70.0], "wt": [2, 3]})
        plan = _adapted(
            qid="q", ftype="DIRECT", measure="rate", dims=["State"],
            agg="reported_value", weight="wt",
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))    # weighted_mean policy
        # (60×2 + 70×3) / 5 = 66.0
        assert _agg_by_key(res, "State")["A"] == 66.0
        assert res.status == "degraded"


# ─────────────────────────────────────────────────────────────────────────────
# RATE / RATIO — same-grain quotient with different default multipliers
# ─────────────────────────────────────────────────────────────────────────────

class TestRateRatio:
    def test_rate_per_thousand(self):
        df = pd.DataFrame({
            "District": ["A", "A", "B"],
            "events": [2, 3, 4],
            "pop": [600, 400, 2000],
        })
        plan = _adapted(qid="q", ftype="RATE", num="events", den="pop", dims=["District"])
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        vals = _agg_by_key(res, "District")
        assert vals["A"] == 5.0    # 5/1000×1000
        assert vals["B"] == 2.0    # 4/2000×1000

    def test_ratio_no_multiplier_aggregate_then_divide(self):
        df = pd.DataFrame({
            "Group": ["A", "A", "B"],
            "num": [1, 5, 4],
            "den": [2, 8, 5],
        })
        plan = _adapted(qid="q", ftype="RATIO", num="num", den="den", dims=["Group"])
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        vals = _agg_by_key(res, "Group")
        assert vals["A"] == 0.6    # 6/10, NOT mean(0.5, 0.625)=0.5625
        assert vals["B"] == 0.8    # 4/5


# ─────────────────────────────────────────────────────────────────────────────
# GROWTH / DIFFERENCE / CAGR — time-window math
# ─────────────────────────────────────────────────────────────────────────────

class TestTimeFormulas:
    def test_growth_yoy_percent(self):
        df = pd.DataFrame({"Year": [2019, 2020], "gdp": [100.0, 110.0]})
        plan = _adapted(
            qid="q", ftype="GROWTH", measure="gdp", agg="mean", time_col="Year",
            time_window={"current": 2020, "prior": 2019},
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        assert res.metrics[0].value == 10.0    # (110-100)/100×100

    def test_difference_absolute(self):
        df = pd.DataFrame({"Year": [2019, 2020], "gdp": [100.0, 110.0]})
        plan = _adapted(
            qid="q", ftype="DIFFERENCE", measure="gdp", agg="mean", time_col="Year",
            time_window={"current": 2020, "prior": 2019},
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        assert res.metrics[0].value == 10.0    # 110 - 100

    def test_cagr_compound_rate(self):
        df = pd.DataFrame({"Year": [2015, 2020], "val": [100.0, 200.0]})
        plan = _adapted(
            qid="q", ftype="CAGR", measure="val", agg="mean", time_col="Year",
            time_window={"current": 2020, "prior": 2015, "periods": 5},
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        # (200/100)^(1/5) - 1 = 0.1487 → ×100 = 14.9
        assert res.metrics[0].value == pytest.approx(14.9, abs=0.1)


# ─────────────────────────────────────────────────────────────────────────────
# INDEX — value / base × 100
# ─────────────────────────────────────────────────────────────────────────────

class TestIndex:
    def test_index_against_base(self):
        df = pd.DataFrame({"Year": [2020, 2021], "price": [200.0, 240.0]})
        plan = _adapted(
            qid="q", ftype="INDEX", measure="price", agg="mean",
            dims=["Year"], base=200.0, multiplier=100.0,
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        vals = _agg_by_key(res, "Year")
        assert vals[2020] == 100.0   # 200/200×100
        assert vals[2021] == 120.0   # 240/200×100


# ─────────────────────────────────────────────────────────────────────────────
# DIRECT — passthrough to plain aggregation
# ─────────────────────────────────────────────────────────────────────────────

class TestDirect:
    def test_direct_group_sum(self):
        df = pd.DataFrame({"State": ["A", "A", "B"], "n": [10, 20, 5]})
        plan = _adapted(qid="q", ftype="DIRECT", measure="n", dims=["State"], agg="sum")
        res = compute_formula(plan, df, profile=load_profile("default"))
        vals = _agg_by_key(res, "State")
        assert vals["A"] == 30.0
        assert vals["B"] == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# RANK over a formula value
# ─────────────────────────────────────────────────────────────────────────────

class TestRankOverFormula:
    def test_rank_share_top_n(self):
        df = pd.DataFrame({
            "State": ["A", "B", "C"],
            "num": [90, 60, 30],
            "den": [100, 100, 100],
        })
        plan = _adapted(
            qid="q", ftype="SHARE", num="num", den="den", dims=["State"],
            operation="rank", multiplier=100.0, top_n=2,
        )
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        assert res.rankings, "rank operation should produce a ranking"
        items = res.rankings[0].items
        assert len(items) == 2                       # topN respected
        assert items[0].key["State"] == "A" and items[0].value == 90.0
        assert items[1].key["State"] == "B" and items[1].value == 60.0


# ─────────────────────────────────────────────────────────────────────────────
# Defensive refusal — a BLOCKED-shaped plan is never softened into a number
# ─────────────────────────────────────────────────────────────────────────────

class TestRefusal:
    def test_share_missing_denominator_is_refused(self):
        df = pd.DataFrame({"g": ["A"], "n": [10]})
        plan = _adapted(qid="q", ftype="SHARE", num="n", den="", dims=["g"], multiplier=100.0)
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        assert res.status == "blocked"
        assert not any(r.value is not None for a in res.aggregations for r in a.rows)
        assert any("denominator" in d.lower() for d in res.diagnostics)

    def test_index_missing_base_is_refused(self):
        df = pd.DataFrame({"Year": [2020], "price": [200.0]})
        plan = _adapted(qid="q", ftype="INDEX", measure="price", dims=["Year"], base=None)
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        assert res.status == "blocked"
        assert any("base" in d.lower() for d in res.diagnostics)

    def test_cagr_missing_timewindow_is_refused(self):
        df = pd.DataFrame({"Year": [2015, 2020], "val": [100.0, 200.0]})
        plan = _adapted(qid="q", ftype="CAGR", measure="val", time_col="Year", time_window={})
        res = compute_formula(plan, df, profile=load_profile("mospi"))
        assert res.status == "blocked"


# ─────────────────────────────────────────────────────────────────────────────
# Registry — dynamic dispatch (not a hardcoded if-chain)
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_all_contract_formula_types_are_registered(self):
        for ftype in ("DIRECT", "SHARE", "RATE", "RATIO", "GROWTH", "CAGR", "INDEX", "DIFFERENCE"):
            assert FormulaRegistry.get(ftype) is not None, f"{ftype} handler missing"

    def test_unknown_type_falls_back_to_direct(self):
        assert FormulaRegistry.resolve("NOT_A_REAL_TYPE") is FormulaRegistry.get("DIRECT")
