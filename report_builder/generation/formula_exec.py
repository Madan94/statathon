"""S4-gold formula executor — the math the physical-column executor cannot do.

The frozen render executor reads a *physical* column (`frame[columnExpr]`) and
reduces it (sum/mean/…). It has no expression evaluator, so derived statistics —
SHARE, RATE, RATIO, GROWTH, CAGR, INDEX, DIFFERENCE — and the deterministic
`reported_value` collapse must be computed here, from the binder's structured
`FormulaSpec`, never from a formula *string*.

Design:
  * Every formula family is a small handler registered on :class:`FormulaRegistry`,
    so the coordinator routes by `formulaSpec.type` with no central if/elif chain.
  * Each handler is built from one **grain-correct value function** `vfn(frame) ->
    (value, status, note)` that is applied per output group (and once over the whole
    filtered frame for the headline metric). SHARE/RATE/RATIO aggregate numerator and
    denominator *separately at that grain, then divide* — the cardinal rule.
  * Policy (multipliers, rounding, zero-denominator handling, reported_value
    reconciliation) comes from a :class:`GenerationConfig` profile — never hardcoded.

The result is shaped into the same gold `analyticsAST` pieces the executor emits
(`Aggregation` / `Ranking` / `Metric`) with `rowIds` provenance, so S5/S6 cannot tell
whether a number came from the plain executor or from here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from report_builder.generation._agg import (
    _agg_value,
    _apply_filters,
    _native,
    _round,
    _row_token,
    reported_value_detail,
)
from report_builder.generation.bundle_adapter import AdaptedPlan
from report_builder.generation.config import GenerationConfig, load_profile
from report_builder.generation.registry import FormulaRegistry
from report_builder.generation.schema import (
    Aggregation,
    AggregationRow,
    Evidence,
    Metric,
    Ranking,
    RankingItem,
    Trend,
)

logger = logging.getLogger(__name__)

# A value function: given a frame, return (value, status, note) for one grain.
ValueFn = Callable[[pd.DataFrame], "tuple[float | None, str, str]"]


@dataclass
class FormulaResult:
    """The gold analytics pieces produced for one plan, plus diagnostics/status."""

    status: str = "ok"                 # ok | degraded | empty | blocked | error
    aggregations: list[Aggregation] = field(default_factory=list)
    rankings: list[Ranking] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    trends: list[Trend] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    row_index: dict[str, list[int]] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def compute_formula(
    plan: AdaptedPlan,
    df: pd.DataFrame,
    *,
    profile: GenerationConfig | None = None,
) -> FormulaResult:
    """Route ``plan`` to its formula handler and compute the value(s).

    ``profile`` carries the policy (defaults to the deterministic ``default`` profile).
    A defensively-seen BLOCKED plan is refused, never softened into a number.
    """
    profile = profile or load_profile()
    if (plan.status or "").upper() == "BLOCKED":
        return _refuse(plan, "plan is BLOCKED — not executed")
    ftype = (plan.formulaSpec.type or "DIRECT").upper()
    handler = FormulaRegistry.resolve(ftype)
    try:
        return handler(plan, df, profile)
    except Exception as exc:  # never let one question kill the run
        logger.exception("[formula_exec] %s failed for %s: %s", ftype, plan.questionId, exc)
        return FormulaResult(status="error", diagnostics=[f"{ftype}: {exc}"])


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def _refuse(plan: AdaptedPlan, reason: str) -> FormulaResult:
    """Refuse to compute: emit a BLOCKED result with a diagnostic and no values."""
    logger.info("[formula_exec] refusing %s: %s", plan.questionId, reason)
    return FormulaResult(status="blocked", diagnostics=[reason])


def _filtered(plan: AdaptedPlan, df: pd.DataFrame) -> pd.DataFrame:
    frame = (df if df is not None else pd.DataFrame()).reset_index(drop=True)
    frame, _applied = _apply_filters(frame, plan.planRec.filters)
    return frame


def _dims(plan: AdaptedPlan, frame: pd.DataFrame) -> list[str]:
    return [c for c in (plan.planRec.groupBy or []) if c and c in frame.columns]


def _sum(frame: pd.DataFrame, col: str, weight: str | None) -> float | None:
    """Sum (or weighted-sum) a physical column at this grain."""
    if not col or col not in frame.columns:
        return None
    if weight and weight in frame.columns:
        return _agg_value(frame, col, "weighted_sum", weight)
    return _agg_value(frame, col, "sum", None)


def _rollup_status(statuses: list[str]) -> str:
    s = set(statuses)
    if not s:
        return "empty"
    if "error" in s:
        return "error"
    if s == {"ok"}:
        return "ok"
    if s == {"empty"}:
        return "empty"
    return "degraded"


def _shape(
    plan: AdaptedPlan,
    df: pd.DataFrame,
    profile: GenerationConfig,
    vfn: ValueFn,
    *,
    label: str = "",
    op_default: str = "group_aggregate",
    make_overall_metric: bool = True,
) -> FormulaResult:
    """Apply ``vfn`` per output group and shape the result (aggregation/ranking/metric)."""
    res = FormulaResult()
    frame = _filtered(plan, df)
    op = plan.planRec.operation or op_default
    dims = _dims(plan, frame)
    qid = plan.questionId or plan.planRec.questionId
    measure_label = label or plan.measureColumn or plan.planRec.measure.columnExpr
    statuses: list[str] = []
    analytics_ref = ""
    kind = ""

    if dims:
        gkey = dims[0] if len(dims) == 1 else dims
        scored: list[tuple[dict[str, Any], str, float | None, int]] = []
        for member, sub in frame.groupby(gkey, sort=False):
            members = (member,) if len(dims) == 1 else tuple(member)
            key = {c: _native(v) for c, v in zip(dims, members)}
            token = _row_token(key)
            res.row_index[token] = [int(i) for i in sub.index.tolist()]
            value, st, note = vfn(sub)
            statuses.append(st)
            if note:
                res.diagnostics.append(f"{token}: {note}")
            scored.append((key, token, value, int(len(sub))))

        if op == "rank":
            order = (plan.planRec.sort or {}).get("order", "desc")
            ranked = [s for s in scored if s[2] is not None]
            ranked.sort(key=lambda s: s[2], reverse=(order != "asc"))
            if plan.planRec.topN:
                ranked = ranked[: plan.planRec.topN]
            items = [
                RankingItem(rank=i, key=k, value=v, rowIds=[tok])
                for i, (k, tok, v, _n) in enumerate(ranked, start=1)
            ]
            res.rankings.append(Ranking(
                rankId=f"rank_{qid}", questionId=qid, measure=measure_label,
                order=order, items=items,
            ))
            analytics_ref, kind = f"rank_{qid}", "ranking"
        else:
            order = (plan.planRec.sort or {}).get("order", "desc")
            rows = [
                AggregationRow(key=k, value=v, n=n, rowIds=[tok])
                for (k, tok, v, n) in scored
            ]
            rows.sort(
                key=lambda r: (r.value is None, r.value if r.value is not None else 0),
                reverse=(order != "asc"),
            )
            group_by_field: Any = dims[0] if len(dims) == 1 else dims
            res.aggregations.append(Aggregation(
                aggId=f"agg_{qid}", questionId=qid, groupBy=group_by_field,
                measure=measure_label, rows=rows,
            ))
            analytics_ref, kind = f"agg_{qid}", "aggregation"

        if make_overall_metric:
            ov, _ov_st, _ov_note = vfn(frame)
            if ov is not None:
                res.row_index["r:all"] = [int(i) for i in frame.index.tolist()]
                res.metrics.append(Metric(
                    metricId=f"m_{qid}", questionId=qid, label=measure_label,
                    value=ov, rowIds=["r:all"],
                ))
    else:
        value, st, note = vfn(frame)
        statuses.append(st)
        if note:
            res.diagnostics.append(note)
        res.row_index["r:all"] = [int(i) for i in frame.index.tolist()]
        res.metrics.append(Metric(
            metricId=f"m_{qid}", questionId=qid, label=measure_label,
            value=value, rowIds=["r:all"],
        ))
        analytics_ref, kind = f"m_{qid}", "metric"

    res.status = _rollup_status(statuses)
    res.evidence.append(_evidence(plan, qid, kind, analytics_ref, res))
    return res


def _evidence(plan: AdaptedPlan, qid: str, kind: str, analytics_ref: str,
              res: FormulaResult) -> Evidence:
    tokens: list[str] = []
    for a in res.aggregations:
        if a.aggId == analytics_ref:
            tokens = [t for r in a.rows for t in r.rowIds]
    for r in res.rankings:
        if r.rankId == analytics_ref:
            tokens = [t for it in r.items for t in it.rowIds]
    for m in res.metrics:
        if m.metricId == analytics_ref:
            tokens = list(m.rowIds)
    columns = [c for c in (
        plan.measureColumn,
        plan.formulaSpec.numeratorColumn,
        plan.formulaSpec.denominatorColumn,
        plan.timeColumn,
    ) if c]
    return Evidence(
        evidenceId=f"ev_{qid}", questionId=qid, componentId="",
        kind=kind or "metric", analyticsRef=analytics_ref, columns=columns,
        rowIds=tokens, computation=plan.formulaSpec.type or "DIRECT",
        value=None, confidence=0.9 if res.status == "ok" else 0.5,
    )


def _period_frames(plan: AdaptedPlan, frame: pd.DataFrame) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Split a frame into (current, prior) period subframes from the timeWindow."""
    tw = plan.formulaSpec.timeWindow or {}
    tcol = plan.timeColumn
    cur, prior = tw.get("current"), tw.get("prior")
    if not tcol or tcol not in frame.columns or cur is None or prior is None:
        return None, None
    cur_f = frame[frame[tcol].astype(str) == str(cur)]
    prior_f = frame[frame[tcol].astype(str) == str(prior)]
    return cur_f, prior_f


# ─────────────────────────────────────────────────────────────────────────────
# Handlers (registered dynamically)
# ─────────────────────────────────────────────────────────────────────────────


@FormulaRegistry.register("DIRECT")
def _direct(plan: AdaptedPlan, df: pd.DataFrame, profile: GenerationConfig) -> FormulaResult:
    """Plain aggregation of a physical column (incl. deterministic reported_value)."""
    measure = plan.measureColumn or plan.planRec.measure.columnExpr
    agg = plan.planRec.measure.agg or "mean"
    weight = plan.planRec.measure.weightColumn

    def vfn(frame: pd.DataFrame) -> tuple[float | None, str, str]:
        if not measure or measure not in frame.columns:
            return None, "empty", ""
        if agg == "reported_value":
            w = frame[weight] if (weight and weight in frame.columns) else None
            rv = reported_value_detail(
                frame[measure], w,
                policy=profile.reported_value_policy, ndigits=profile.rounding,
            )
            return rv.value, rv.status, rv.note
        v = _agg_value(frame, measure, agg, weight, ndigits=profile.rounding)
        return v, ("ok" if v is not None else "empty"), ""

    return _shape(plan, df, profile, vfn, label=measure)


@FormulaRegistry.register("SHARE", "RATE", "RATIO")
def _quotient(plan: AdaptedPlan, df: pd.DataFrame, profile: GenerationConfig) -> FormulaResult:
    """numerator / denominator × multiplier — aggregate-then-divide at each grain."""
    ftype = (plan.formulaSpec.type or "").upper()
    num = plan.formulaSpec.numeratorColumn or plan.measureColumn or plan.planRec.measure.columnExpr
    den = plan.formulaSpec.denominatorColumn
    if not den:
        return _refuse(plan, f"{ftype}: missing denominatorColumn — cannot divide")
    weight = plan.formulaSpec.weightColumn or plan.planRec.measure.weightColumn
    mult = profile.multiplier_for(ftype, plan.formulaSpec.multiplier)

    def vfn(frame: pd.DataFrame) -> tuple[float | None, str, str]:
        n = _sum(frame, num, weight)
        d = _sum(frame, den, weight)
        if n is None or d is None:
            return None, "empty", ""
        if d == 0:
            if profile.zero_denominator_policy == "error":
                return None, "error", f"zero denominator ({den})"
            return None, "degraded", f"zero denominator ({den}) — value undefined"
        return _round(n / d * mult, profile.rounding), "ok", ""

    return _shape(plan, df, profile, vfn, label=num)


@FormulaRegistry.register("INDEX")
def _index(plan: AdaptedPlan, df: pd.DataFrame, profile: GenerationConfig) -> FormulaResult:
    """value / baseValue × multiplier."""
    if plan.formulaSpec.baseValue is None:
        return _refuse(plan, "INDEX: missing baseValue")
    base = float(plan.formulaSpec.baseValue)
    if base == 0:
        return _refuse(plan, "INDEX: baseValue is zero")
    measure = plan.measureColumn or plan.planRec.measure.columnExpr
    agg = plan.planRec.measure.agg or "mean"
    weight = plan.planRec.measure.weightColumn
    mult = profile.multiplier_for("INDEX", plan.formulaSpec.multiplier)

    def vfn(frame: pd.DataFrame) -> tuple[float | None, str, str]:
        v = _agg_value(frame, measure, agg, weight, ndigits=profile.rounding)
        if v is None:
            return None, "empty", ""
        return _round(v / base * mult, profile.rounding), "ok", ""

    return _shape(plan, df, profile, vfn, label=measure)


@FormulaRegistry.register("GROWTH", "DIFFERENCE")
def _delta(plan: AdaptedPlan, df: pd.DataFrame, profile: GenerationConfig) -> FormulaResult:
    """GROWTH = (cur-prior)/prior × multiplier; DIFFERENCE = cur - prior (absolute)."""
    ftype = (plan.formulaSpec.type or "").upper()
    tw = plan.formulaSpec.timeWindow or {}
    if tw.get("current") is None or tw.get("prior") is None:
        return _refuse(plan, f"{ftype}: missing timeWindow current/prior")
    measure = plan.measureColumn or plan.planRec.measure.columnExpr
    agg = plan.planRec.measure.agg or "mean"
    weight = plan.planRec.measure.weightColumn
    mult = profile.multiplier_for("GROWTH", plan.formulaSpec.multiplier)

    def vfn(frame: pd.DataFrame) -> tuple[float | None, str, str]:
        cur_f, prior_f = _period_frames(plan, frame)
        if cur_f is None:
            return None, "empty", f"{ftype}: time column/window unresolved"
        cv = _agg_value(cur_f, measure, agg, weight, ndigits=profile.rounding)
        pv = _agg_value(prior_f, measure, agg, weight, ndigits=profile.rounding)
        if cv is None or pv is None:
            return None, "empty", f"{ftype}: missing current/prior value"
        if ftype == "DIFFERENCE":
            return _round(cv - pv, profile.rounding), "ok", ""
        if pv == 0:
            return None, "degraded", "GROWTH: zero prior value — undefined"
        return _round((cv - pv) / pv * mult, profile.rounding), "ok", ""

    return _shape(plan, df, profile, vfn, label=measure, op_default="trend")


@FormulaRegistry.register("CAGR")
def _cagr(plan: AdaptedPlan, df: pd.DataFrame, profile: GenerationConfig) -> FormulaResult:
    """(end/start)^(1/periods) - 1, scaled by the multiplier (percent by default)."""
    tw = plan.formulaSpec.timeWindow or {}
    if tw.get("current") is None or tw.get("prior") is None or not tw.get("periods"):
        return _refuse(plan, "CAGR: missing timeWindow current/prior/periods")
    try:
        periods = float(tw.get("periods") or 0)
    except (TypeError, ValueError):
        periods = 0.0
    if periods <= 0:
        return _refuse(plan, "CAGR: periods must be > 0")
    measure = plan.measureColumn or plan.planRec.measure.columnExpr
    agg = plan.planRec.measure.agg or "mean"
    weight = plan.planRec.measure.weightColumn
    mult = profile.multiplier_for("CAGR", plan.formulaSpec.multiplier)

    def vfn(frame: pd.DataFrame) -> tuple[float | None, str, str]:
        cur_f, prior_f = _period_frames(plan, frame)
        if cur_f is None:
            return None, "empty", "CAGR: time column/window unresolved"
        end = _agg_value(cur_f, measure, agg, weight, ndigits=profile.rounding)
        start = _agg_value(prior_f, measure, agg, weight, ndigits=profile.rounding)
        if end is None or start is None or start == 0:
            return None, "degraded", "CAGR: missing or zero endpoint"
        ratio = end / start
        if ratio <= 0:
            return None, "degraded", "CAGR: non-positive value ratio"
        return _round((ratio ** (1.0 / periods) - 1.0) * mult, profile.rounding), "ok", ""

    return _shape(plan, df, profile, vfn, label=measure, op_default="trend")
