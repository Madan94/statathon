"""S4b — Executor: run plans over a DataFrame → ``analyticsAST`` + ``evidenceAST``.

A small, purpose-built, fully-deterministic pandas executor. It deliberately does
*not* reuse ``deep_bi.AnalyticsExecutor`` because that emits a different contract
(``results[]`` / ``final_table`` with row-id caps) that would need heavy reshaping;
this executor produces the **exact gold** ``aggregations`` / ``rankings`` /
``trends`` / ``metrics`` shapes directly, each row carrying a ``rowIds`` provenance
token so every number traces back to its source rows.

Provenance tokens follow the gold convention: a stable, human-readable selector
such as ``"r:sector=Rural"`` (a group) or ``"r:all"`` (the whole filtered frame),
plus — for full auditability — the executor can also attach the concrete positional
row indices behind each token via the returned ``RowIndex`` map.

Engine label is ``"pandas"`` (gold uses ``"duckdb"``; the backend is swappable).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import numpy as np
import pandas as pd

from report_builder.generation.schema import (
    Aggregation,
    AggregationRow,
    AnalyticsAST,
    AnalyticsPlanRec,
    Evidence,
    EvidenceAST,
    ExecutionRec,
    Metric,
    Ranking,
    RankingItem,
    Trend,
    TrendPoint,
)

logger = logging.getLogger(__name__)

_FILTER_RE = re.compile(r"^\s*([A-Za-z_][\w ]*?)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$")


# ─────────────────────────────────────────────────────────────────────────────
# Filtering
# ─────────────────────────────────────────────────────────────────────────────


def _coerce(value: str) -> Any:
    v = value.strip()
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _apply_filters(df: pd.DataFrame, exprs: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Apply ``col OP value`` filter strings; return (filtered frame, applied list).

    A filter whose column is missing is skipped (widen-on-missing — never error),
    matching the binding phase's "never silently drop rows by guessing" rule.
    """
    cur = df
    applied: list[str] = []
    for expr in exprs or []:
        m = _FILTER_RE.match(expr)
        if not m:
            continue
        col, op, raw = m.group(1).strip(), m.group(2), _coerce(m.group(3))
        if col not in cur.columns:
            logger.warning("[exec] filter column %r not in dataset — widening", col)
            continue
        series = cur[col]
        try:
            if op == "==":
                mask = series.astype(str) == str(raw) if series.dtype == object else series == raw
            elif op == "!=":
                mask = series.astype(str) != str(raw) if series.dtype == object else series != raw
            elif op == ">=":
                mask = series >= raw
            elif op == "<=":
                mask = series <= raw
            elif op == ">":
                mask = series > raw
            else:
                mask = series < raw
        except TypeError:
            logger.warning("[exec] filter %r type-mismatch — widening", expr)
            continue
        cur = cur[mask]
        applied.append(expr)
    return cur, applied


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation math
# ─────────────────────────────────────────────────────────────────────────────


def _agg_value(frame: pd.DataFrame, measure: str, agg: str, weight: str | None) -> float | None:
    """Compute one scalar measure over ``frame`` (None if not computable)."""
    if measure not in frame.columns or frame.empty:
        return None
    col = pd.to_numeric(frame[measure], errors="coerce")
    if agg in ("weighted_mean", "weighted_ratio") and weight and weight in frame.columns:
        # A weighted mean of the measure column. Any percent-scaling for a 0/1
        # share lives in the *derived-measure expression* (e.g. the gold binding
        # ``100 * weighted_share(...)``), never in the agg itself, so a column that
        # is already a percentage is not double-scaled.
        w = pd.to_numeric(frame[weight], errors="coerce")
        valid = col.notna() & w.notna()
        denom = w[valid].sum()
        if denom == 0:
            return None
        return _round(float((col[valid] * w[valid]).sum() / denom))
    if agg in ("weighted_sum",) and weight and weight in frame.columns:
        w = pd.to_numeric(frame[weight], errors="coerce")
        return float((col * w).sum(skipna=True))
    if agg in ("sum", "weighted_sum"):
        return float(col.sum(skipna=True))
    if agg in ("count",):
        return int(col.notna().sum())
    if agg in ("median",):
        return _round(col.median(skipna=True))
    if agg in ("min",):
        return _round(col.min(skipna=True))
    if agg in ("max",):
        return _round(col.max(skipna=True))
    # mean / ratio / default
    return _round(col.mean(skipna=True))


def _round(v: Any, ndigits: int = 1) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), ndigits)


# ─────────────────────────────────────────────────────────────────────────────
# Per-operation executors
# ─────────────────────────────────────────────────────────────────────────────


def _row_token(prefix_pairs: dict[str, Any]) -> str:
    if not prefix_pairs:
        return "r:all"
    return "r:" + ",".join(f"{k}={v}" for k, v in prefix_pairs.items())


def _exec_group_aggregate(plan: AnalyticsPlanRec, df: pd.DataFrame) -> tuple[Aggregation, dict[str, list[int]]]:
    measure, agg, weight = plan.measure.columnExpr, plan.measure.agg, plan.measure.weightColumn
    # Keep only groupBy columns that actually exist (widen-on-missing, never error).
    group_cols = [c for c in (plan.groupBy or []) if c and c in df.columns]
    row_index: dict[str, list[int]] = {}
    rows: list[AggregationRow] = []
    if group_cols:
        gkey = group_cols[0] if len(group_cols) == 1 else group_cols
        for member, sub in df.groupby(gkey, sort=False):
            # member is a scalar for 1 col, a tuple for many — normalise to a key dict.
            members = (member,) if len(group_cols) == 1 else tuple(member)
            key = {col: _native(val) for col, val in zip(group_cols, members)}
            token = _row_token(key)
            row_index[token] = [int(i) for i in sub.index.tolist()]
            rows.append(AggregationRow(
                key=key,
                value=_agg_value(sub, measure, agg, weight),
                n=int(len(sub)),
                rowIds=[token],
            ))
        order = (plan.sort or {}).get("order", "desc")
        rows.sort(key=lambda r: (r.value is None, r.value if r.value is not None else 0),
                  reverse=(order != "asc"))
    # ``groupBy`` stays a single column name when 1-D (gold shape); a list when N-D.
    group_by_field: Any = group_cols[0] if len(group_cols) == 1 else group_cols
    agg_obj = Aggregation(
        aggId=f"agg_{plan.questionId}",
        questionId=plan.questionId,
        groupBy=group_by_field,
        measure=measure,
        rows=rows,
    )
    return agg_obj, row_index


def _exec_rank(plan: AnalyticsPlanRec, df: pd.DataFrame) -> tuple[Ranking, dict[str, list[int]]]:
    measure, agg, weight = plan.measure.columnExpr, plan.measure.agg, plan.measure.weightColumn
    group_col = plan.groupBy[0] if plan.groupBy else ""
    order = (plan.sort or {}).get("order", "desc")
    row_index: dict[str, list[int]] = {}
    scored: list[tuple[Any, float | None, list[int]]] = []
    if group_col and group_col in df.columns:
        for member, sub in df.groupby(group_col, sort=False):
            scored.append((member, _agg_value(sub, measure, agg, weight),
                           [int(i) for i in sub.index.tolist()]))
    scored = [s for s in scored if s[1] is not None]
    scored.sort(key=lambda s: s[1], reverse=(order != "asc"))
    if plan.topN:
        scored = scored[: plan.topN]
    items: list[RankingItem] = []
    for rank, (member, value, idxs) in enumerate(scored, start=1):
        token = _row_token({group_col: member})
        row_index[token] = idxs
        items.append(RankingItem(rank=rank, key={group_col: _native(member)}, value=value, rowIds=[token]))
    ranking = Ranking(
        rankId=f"rank_{plan.questionId}",
        questionId=plan.questionId,
        measure=measure,
        order=order,
        items=items,
    )
    return ranking, row_index


def _exec_trend(plan: AnalyticsPlanRec, df: pd.DataFrame) -> tuple[Trend, dict[str, list[int]]]:
    measure, agg, weight = plan.measure.columnExpr, plan.measure.agg, plan.measure.weightColumn
    time_col = plan.groupBy[0] if plan.groupBy else ""
    row_index: dict[str, list[int]] = {}
    points: list[TrendPoint] = []
    if time_col and time_col in df.columns:
        for period, sub in df.groupby(time_col, sort=True):
            token = _row_token({time_col: period})
            row_index[token] = [int(i) for i in sub.index.tolist()]
            points.append(TrendPoint(period=str(period), value=_agg_value(sub, measure, agg, weight), rowIds=[token]))
    trend = Trend(
        trendId=f"trend_{plan.questionId}",
        questionId=plan.questionId,
        measure=measure,
        dimension=time_col,
        points=points,
    )
    return trend, row_index


def _exec_metric(plan: AnalyticsPlanRec, df: pd.DataFrame, label: str) -> tuple[Metric, dict[str, list[int]]]:
    measure, agg, weight = plan.measure.columnExpr, plan.measure.agg, plan.measure.weightColumn
    token = "r:all"
    row_index = {token: [int(i) for i in df.index.tolist()]}
    metric = Metric(
        metricId=f"m_{plan.questionId}",
        questionId=plan.questionId,
        label=label or measure,
        value=_agg_value(df, measure, agg, weight),
        unit="percent" if agg == "weighted_ratio" else None,
        rowIds=[token],
    )
    return metric, row_index


def _native(v: Any) -> Any:
    """Convert numpy scalars to plain python for clean JSON."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


# ─────────────────────────────────────────────────────────────────────────────
# Top-level runner
# ─────────────────────────────────────────────────────────────────────────────


def run_analytics(
    plans: list[AnalyticsPlanRec],
    df: pd.DataFrame,
    *,
    question_meta: dict[str, dict[str, Any]] | None = None,
) -> tuple[AnalyticsAST, EvidenceAST, dict[str, list[int]]]:
    """Execute every plan and roll results into ``analyticsAST`` + ``evidenceAST``.

    ``question_meta[qid]`` may carry ``{"label": str, "components": [...]}`` so
    metric labels and per-component evidence wiring match the blueprint. Returns
    the two ASTs plus a ``row_index`` mapping each provenance token to the concrete
    positional row indices behind it (kept out of the JSON, used by the filler/audit).
    """
    df = df.reset_index(drop=True) if df is not None else pd.DataFrame()
    question_meta = question_meta or {}
    analytics = AnalyticsAST()
    evidence = EvidenceAST()
    row_index: dict[str, list[int]] = {}

    for plan in plans:
        analytics.plans.append(plan)
        t0 = time.perf_counter()
        filtered, applied = _apply_filters(df, plan.filters)
        status = "ok"
        kind = ""
        analytics_ref = ""
        value: Any = None
        columns = _plan_columns(plan)

        try:
            if plan.operation == "rank":
                ranking, ridx = _exec_rank(plan, filtered)
                analytics.rankings.append(ranking)
                row_index.update(ridx)
                kind, analytics_ref = "ranking", ranking.rankId
                value = ranking.items[0].value if ranking.items else None
                status = "ok" if ranking.items else "empty"
            elif plan.operation == "trend":
                trend, ridx = _exec_trend(plan, filtered)
                analytics.trends.append(trend)
                row_index.update(ridx)
                kind, analytics_ref = "trend", trend.trendId
                value = trend.points[-1].value if trend.points else None
                status = "ok" if trend.points else "empty"
            elif plan.operation == "metric":
                label = question_meta.get(plan.questionId, {}).get("label", "")
                metric, ridx = _exec_metric(plan, filtered, label)
                analytics.metrics.append(metric)
                row_index.update(ridx)
                kind, analytics_ref = "metric", metric.metricId
                value = metric.value
                status = "ok" if metric.value is not None else "empty"
            else:  # group_aggregate (default)
                agg_obj, ridx = _exec_group_aggregate(plan, filtered)
                analytics.aggregations.append(agg_obj)
                row_index.update(ridx)
                kind, analytics_ref = "aggregation", agg_obj.aggId
                value = agg_obj.rows[0].value if agg_obj.rows else None
                status = "ok" if agg_obj.rows else "empty"
                # A group_aggregate question usually also surfaces an all-India metric.
                metric, mridx = _exec_metric(plan, filtered,
                                             question_meta.get(plan.questionId, {}).get("label", ""))
                if metric.value is not None:
                    analytics.metrics.append(metric)
                    row_index.update(mridx)
        except Exception as exc:  # never let one question kill the run
            logger.exception("[exec] question %s failed: %s", plan.questionId, exc)
            status = "error"

        ms = int((time.perf_counter() - t0) * 1000)
        analytics.executions.append(ExecutionRec(
            executionId=f"exec_{plan.questionId}",
            planRef=plan.planId,
            engine="pandas",
            rowsScanned=int(len(filtered)),
            ms=ms,
            status=status,
        ))

        # One evidence record per question (component-level wiring is added by the
        # filler, which knows the component ids; here we anchor it to the question).
        if analytics_ref:
            all_row_ids = _collect_tokens(analytics_ref, analytics)
            evidence.evidence.append(Evidence(
                evidenceId=f"ev_{plan.questionId}",
                questionId=plan.questionId,
                componentId="",
                kind=kind,
                analyticsRef=analytics_ref,
                columns=columns,
                rowIds=all_row_ids,
                computation=plan.measure.agg,
                value=value,
                confidence=_confidence(status, applied, plan),
            ))

    return analytics, evidence, row_index


def _plan_columns(plan: AnalyticsPlanRec) -> list[str]:
    cols: list[str] = []
    if plan.measure.columnExpr:
        cols.append(plan.measure.columnExpr)
    if plan.measure.weightColumn:
        cols.append(plan.measure.weightColumn)
    cols.extend(c for c in plan.groupBy if c not in cols)
    return cols


def _collect_tokens(analytics_ref: str, analytics: AnalyticsAST) -> list[str]:
    for a in analytics.aggregations:
        if a.aggId == analytics_ref:
            return [t for r in a.rows for t in r.rowIds]
    for r in analytics.rankings:
        if r.rankId == analytics_ref:
            return [t for it in r.items for t in it.rowIds]
    for t in analytics.trends:
        if t.trendId == analytics_ref:
            return [tok for p in t.points for tok in p.rowIds]
    for m in analytics.metrics:
        if m.metricId == analytics_ref:
            return list(m.rowIds)
    return []


def _confidence(status: str, applied: list[str], plan: AnalyticsPlanRec) -> float:
    """A simple calibrated confidence: full when clean, penalised when degraded."""
    if status != "ok":
        return 0.3
    conf = 0.95
    # Penalise if a declared filter could not be applied (widened result).
    if len(applied) < len(plan.filters):
        conf -= 0.15
    if not plan.measure.columnExpr:
        conf -= 0.4
    return round(max(0.0, conf), 2)
