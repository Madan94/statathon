"""Tests for the safe normalization executor (`normalize_exec`).

Proves the Phase 2 contract:
- NONE is an identity reshape.
- WIDE_TO_LONG melts a MoSPI-style wide table and degrades (never guesses) when the
  id column or the member columns are absent.
- DERIVE_COLUMN computes arithmetic with an AST whitelist — divide-by-zero is NaN
  (not inf / not a crash) and any unsafe expression (import, attribute, subscript,
  call, dunder) is rejected with NORMALIZE_UNSAFE_EXPRESSION and NO output column.
- FILTER_ROWS applies resolved structured filters only.
- JOIN / UNION / PIVOT degrade with NORMALIZE_UNSUPPORTED:<TYPE>, frame unchanged.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from report_builder.binding.execution_contracts import NormalizationPlan
from report_builder.generation.bundle_adapter import AdaptedPlan
from report_builder.generation.normalize_exec import (
    NormalizationResult,
    apply_normalization,
    apply_normalization_plan,
)
from report_builder.generation.schema import AnalyticsPlanRec


def _adapted(nplan: NormalizationPlan, *, filters: list[str] | None = None, qid: str = "q") -> AdaptedPlan:
    rec = AnalyticsPlanRec(planId=f"plan_{qid}", questionId=qid, filters=list(filters or []))
    return AdaptedPlan(planRec=rec, questionId=qid, normalizationPlan=nplan)


# ─────────────────────────────────────────────────────────────────────────────
# 1. NONE
# ─────────────────────────────────────────────────────────────────────────────

def test_none_returns_frame_unchanged():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    res = apply_normalization(_adapted(NormalizationPlan(type="NONE")), df)
    assert isinstance(res, NormalizationResult)
    assert res.status == "ok"
    assert res.diagnostics == []
    assert res.frame.equals(df)


# ─────────────────────────────────────────────────────────────────────────────
# 2-4. WIDE_TO_LONG
# ─────────────────────────────────────────────────────────────────────────────

def test_wide_to_long_melts_mospi_wide_table():
    df = pd.DataFrame({"State": ["A", "B"], "2020": [10, 20], "2021": [12, 22]})
    nplan = NormalizationPlan(
        type="WIDE_TO_LONG", idVars=["State"],
        valueVar="value", memberVar="member", memberLabels=["2020", "2021"],
    )
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "ok"
    assert list(res.frame.columns) == ["State", "member", "value"]
    assert len(res.frame) == 4
    a2020 = res.frame[(res.frame["State"] == "A") & (res.frame["member"] == "2020")]
    assert a2020["value"].iloc[0] == 10
    assert res.transformations, "a transformation hint must be recorded for lineage"


def test_wide_to_long_missing_id_var_degrades():
    df = pd.DataFrame({"2020": [10], "2021": [12]})  # no State column
    nplan = NormalizationPlan(type="WIDE_TO_LONG", idVars=["State"], memberLabels=["2020", "2021"])
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "degraded"
    assert any("idVars" in d for d in res.diagnostics)
    assert res.frame.equals(df)


def test_wide_to_long_missing_value_columns_degrades():
    df = pd.DataFrame({"State": ["A"], "x": [1]})  # member columns absent
    nplan = NormalizationPlan(type="WIDE_TO_LONG", idVars=["State"], memberLabels=["2020", "2021"])
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "degraded"
    assert any("member" in d.lower() for d in res.diagnostics)
    assert res.frame.equals(df)


# ─────────────────────────────────────────────────────────────────────────────
# 5-6. DERIVE_COLUMN — safe arithmetic
# ─────────────────────────────────────────────────────────────────────────────

def test_derive_column_safe_arithmetic():
    df = pd.DataFrame({"numerator": [50, 30], "denominator": [200, 60]})
    nplan = NormalizationPlan(
        type="DERIVE_COLUMN", expression="numerator / denominator * 100", outputColumn="share",
    )
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "ok"
    assert res.frame["share"].iloc[0] == 25.0
    assert res.frame["share"].iloc[1] == 50.0
    assert res.transformations


def test_derive_column_divide_by_zero_is_nan():
    df = pd.DataFrame({"n": [5, 10], "d": [0, 50]})
    nplan = NormalizationPlan(type="DERIVE_COLUMN", expression="n / d", outputColumn="r")
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "ok"
    assert math.isnan(res.frame["r"].iloc[0])     # 5/0 → NaN, never inf, never crash
    assert res.frame["r"].iloc[1] == 0.2


# ─────────────────────────────────────────────────────────────────────────────
# 7-8. DERIVE_COLUMN — unsafe expressions rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_derive_column_rejects_import_expression():
    df = pd.DataFrame({"a": [1]})
    nplan = NormalizationPlan(
        type="DERIVE_COLUMN",
        expression='__import__("os").system("echo pwned")',
        outputColumn="evil",
    )
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "degraded"
    assert any("NORMALIZE_UNSAFE_EXPRESSION" in d for d in res.diagnostics)
    assert "evil" not in res.frame.columns
    assert res.frame.equals(df)


@pytest.mark.parametrize("expr", [
    "a.real",          # attribute access
    "a[0]",            # subscript
    "abs(a)",          # function call
    "a.__class__",     # dunder via attribute
    "(lambda: 1)()",   # lambda + call
    "[x for x in a]",  # comprehension
])
def test_derive_column_rejects_unsafe_access(expr):
    df = pd.DataFrame({"a": [1, 2]})
    nplan = NormalizationPlan(type="DERIVE_COLUMN", expression=expr, outputColumn="out")
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "degraded"
    assert any("NORMALIZE_UNSAFE_EXPRESSION" in d for d in res.diagnostics)
    assert "out" not in res.frame.columns


def test_derive_column_missing_column_degrades():
    df = pd.DataFrame({"a": [1, 2]})
    nplan = NormalizationPlan(type="DERIVE_COLUMN", expression="a / b", outputColumn="out")
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "degraded"
    assert any("NORMALIZE_MISSING_COLUMN" in d for d in res.diagnostics)
    assert "out" not in res.frame.columns


# ─────────────────────────────────────────────────────────────────────────────
# 9. FILTER_ROWS
# ─────────────────────────────────────────────────────────────────────────────

def test_filter_rows_applies_safe_filter():
    df = pd.DataFrame({"age": [10, 20, 30], "v": [1, 2, 3]})
    nplan = NormalizationPlan(type="FILTER_ROWS")
    res = apply_normalization(_adapted(nplan, filters=["age>=20"]), df)
    assert res.status == "ok"
    assert list(res.frame["age"]) == [20, 30]
    assert res.transformations


def test_filter_rows_unappliable_filter_degrades():
    df = pd.DataFrame({"age": [10, 20]})
    nplan = NormalizationPlan(type="FILTER_ROWS")
    res = apply_normalization(_adapted(nplan, filters=["missing_col==1"]), df)
    assert res.status == "degraded"
    assert any("FILTER_ROWS" in d for d in res.diagnostics)


# ─────────────────────────────────────────────────────────────────────────────
# 10. JOIN / UNION / PIVOT — unsupported, degrade
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ntype", ["JOIN", "UNION", "PIVOT"])
def test_unsupported_types_degrade(ntype):
    df = pd.DataFrame({"a": [1, 2]})
    nplan = NormalizationPlan(type=ntype)
    res = apply_normalization(_adapted(nplan), df)
    assert res.status == "degraded"
    assert any(f"NORMALIZE_UNSUPPORTED:{ntype}" in d for d in res.diagnostics)
    assert res.frame.equals(df)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper works without AdaptedPlan context
# ─────────────────────────────────────────────────────────────────────────────

def test_apply_normalization_plan_direct():
    df = pd.DataFrame({"State": ["A"], "2020": [10], "2021": [12]})
    nplan = NormalizationPlan(type="WIDE_TO_LONG", idVars=["State"], memberLabels=["2020", "2021"])
    res = apply_normalization_plan(nplan, df)
    assert res.status == "ok"
    assert len(res.frame) == 2
