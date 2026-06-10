"""Shared, deterministic aggregation primitives for the generation phase.

These are the grain-correct building blocks used by **both** the physical-column
executor (`executor.py`) and the formula executor (`formula_exec.py`). Keeping them
in one place guarantees a SHARE numerator aggregated here is identical to a DIRECT
measure aggregated there — the same rounding, the same weighting, the same
provenance tokens.

Key invariants encoded here (do not weaken):
  * **`reported_value` is never a silent `mean()`.** A pre-aggregated rate/percent
    column collapses to a single representative value deterministically: one
    non-null → use it; all equal → use it; differing → reconcile by *weighted
    mean* only when a valid weight column and an explicit policy permit, otherwise
    the group is **ambiguous** (value `None`) and the caller marks it DEGRADED.
  * Aggregation reads a **physical column** (`pd.to_numeric(frame[col])`). There is
    no expression evaluator — derived quotients are the job of `formula_exec`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# A measure-aggregation vocabulary the executor understands. ``reported_value`` is
# handled specially (see ``reported_value_detail``); the rest are plain reductions.
AGG_FUNCS = (
    "weighted_ratio", "weighted_mean", "weighted_sum",
    "mean", "sum", "median", "count", "ratio", "min", "max",
    "reported_value",
)

_FILTER_RE = re.compile(r"^\s*([A-Za-z_][\w ]*?)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$")


# ─────────────────────────────────────────────────────────────────────────────
# Scalar / token helpers
# ─────────────────────────────────────────────────────────────────────────────


def _round(v: Any, ndigits: int = 1) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), ndigits)


def _native(v: Any) -> Any:
    """Convert numpy scalars to plain python for clean JSON."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def _row_token(prefix_pairs: dict[str, Any]) -> str:
    """A stable, human-readable provenance selector for a group of rows."""
    if not prefix_pairs:
        return "r:all"
    return "r:" + ",".join(f"{k}={v}" for k, v in prefix_pairs.items())


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
# reported_value — deterministic single-representative collapse (never silent mean)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ReportedValue:
    """Outcome of collapsing a pre-aggregated rate/percent column for one group."""

    value: float | None
    status: str          # "ok" | "degraded" | "ambiguous" | "empty"
    note: str = ""


def reported_value_detail(
    series: pd.Series,
    weight: pd.Series | None = None,
    *,
    policy: str = "strict",
    ndigits: int = 1,
) -> ReportedValue:
    """Collapse a group's already-computed rate/percent values to one number.

    Deterministic rules (in order):
      1. no non-null values            → ``empty`` (value None)
      2. exactly one non-null / all equal → ``ok`` (use it)
      3. differing values, ``policy='weighted_mean'`` and a valid weight column
                                        → ``degraded`` (weighted mean, with note)
      4. differing values otherwise    → ``ambiguous`` (value None)

    Rule 4 is the guardrail: a rate column is **never** silently averaged.
    """
    nums = pd.to_numeric(series, errors="coerce")
    mask = nums.notna()
    vals = nums[mask]
    if vals.empty:
        return ReportedValue(None, "empty", "no non-null values")
    uniq = pd.unique(vals)
    if len(vals) == 1 or len(uniq) == 1:
        return ReportedValue(_round(float(vals.iloc[0]), ndigits), "ok")
    if policy == "weighted_mean" and weight is not None:
        w = pd.to_numeric(weight, errors="coerce")
        try:
            w = w.loc[vals.index]
        except (KeyError, IndexError):
            w = w.reindex(vals.index)
        valid = vals.notna() & w.notna()
        denom = float(w[valid].sum()) if valid.any() else 0.0
        if denom != 0:
            wm = float((vals[valid] * w[valid]).sum() / denom)
            return ReportedValue(
                _round(wm, ndigits), "degraded",
                "differing reported values reconciled by weighted mean",
            )
    return ReportedValue(
        None, "ambiguous",
        "differing reported values; no valid weight/policy — left unaggregated",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scalar measure aggregation (one column → one number over a frame)
# ─────────────────────────────────────────────────────────────────────────────


def _agg_value(
    frame: pd.DataFrame,
    measure: str,
    agg: str,
    weight: str | None,
    *,
    ndigits: int = 1,
) -> float | None:
    """Compute one scalar measure over ``frame`` (None if not computable).

    ``reported_value`` uses the deterministic collapse (strict policy here — the
    executor does not reconcile by weight; ``formula_exec`` does that explicitly
    via :func:`reported_value_detail` with a profile policy).
    """
    if measure not in frame.columns or frame.empty:
        return None
    col = pd.to_numeric(frame[measure], errors="coerce")
    if agg == "reported_value":
        return reported_value_detail(col, policy="strict", ndigits=ndigits).value
    if agg in ("weighted_mean", "weighted_ratio") and weight and weight in frame.columns:
        # A weighted mean of the measure column. Any percent-scaling for a 0/1
        # share lives in the *derived-measure expression* (the formula multiplier),
        # never in the agg itself, so a column already a percentage is not double-scaled.
        w = pd.to_numeric(frame[weight], errors="coerce")
        valid = col.notna() & w.notna()
        denom = w[valid].sum()
        if denom == 0:
            return None
        return _round(float((col[valid] * w[valid]).sum() / denom), ndigits)
    if agg in ("weighted_sum",) and weight and weight in frame.columns:
        w = pd.to_numeric(frame[weight], errors="coerce")
        return float((col * w).sum(skipna=True))
    if agg in ("sum", "weighted_sum"):
        return float(col.sum(skipna=True))
    if agg in ("count",):
        return int(col.notna().sum())
    if agg in ("median",):
        return _round(col.median(skipna=True), ndigits)
    if agg in ("min",):
        return _round(col.min(skipna=True), ndigits)
    if agg in ("max",):
        return _round(col.max(skipna=True), ndigits)
    # mean / ratio / default
    return _round(col.mean(skipna=True), ndigits)
