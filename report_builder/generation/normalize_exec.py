"""S4-gold normalization executor — reshape a frame safely before analytics.

The binder may attach a `NormalizationPlan` to a question (melt wide year columns,
strip embedded header/total rows, derive a column). This module applies that plan
**before** the formula/physical executors run, so analytics always sees a tidy frame.

Safety is the whole point:
  * `DERIVE_COLUMN` is evaluated with a strict Python-`ast` whitelist — **never**
    `eval`/`exec`. Only numeric constants, column names, and the arithmetic operators
    ``+ - * / ** %`` (plus unary ±) are allowed. Attribute access, subscripting, calls,
    imports, lambdas, comprehensions and dunder names are rejected; an unsafe expression
    degrades with `NORMALIZE_UNSAFE_EXPRESSION` and produces **no** output column.
  * `JOIN` / `UNION` / `PIVOT` are not implemented yet — they return a clear
    `NORMALIZE_UNSUPPORTED:<TYPE>` degrade with the frame unchanged, never a guess.
  * Every reshape returns a `transformations` list so S5/S6 lineage can record what
    happened to the rows.

This module deliberately does NOT route plans (that is the future S4 coordinator) and
does NOT touch the binder/extraction contracts.
"""
from __future__ import annotations

import ast
import logging
import math
import operator
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from report_builder.binding.execution_contracts import NormalizationPlan
from report_builder.generation._agg import _apply_filters
from report_builder.generation.bundle_adapter import AdaptedPlan

logger = logging.getLogger(__name__)


@dataclass
class NormalizationResult:
    """Outcome of applying a `NormalizationPlan` to a frame."""

    frame: pd.DataFrame
    diagnostics: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    status: str = "ok"               # ok | degraded


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def apply_normalization(plan: AdaptedPlan, df: pd.DataFrame) -> NormalizationResult:
    """Apply ``plan``'s normalization to ``df`` (coordinator-facing entry point).

    Carries the full ``AdaptedPlan`` so `FILTER_ROWS` can use the resolved structured
    filters on ``planRec.filters`` and later phases can attach lineage.
    """
    nplan = plan.normalizationPlan or NormalizationPlan()
    structured_filters = list(plan.planRec.filters or [])
    return apply_normalization_plan(nplan, df, structured_filters=structured_filters)


def apply_normalization_plan(
    plan: NormalizationPlan,
    df: pd.DataFrame,
    *,
    structured_filters: list[str] | None = None,
) -> NormalizationResult:
    """Apply a bare `NormalizationPlan` to ``df`` (no AdaptedPlan context needed)."""
    frame = df if df is not None else pd.DataFrame()
    ntype = (plan.type or "NONE").upper()

    if ntype == "NONE":
        return NormalizationResult(frame, [], [], "ok")
    if ntype == "WIDE_TO_LONG":
        return _wide_to_long(plan, frame)
    if ntype == "FILTER_ROWS":
        return _filter_rows(frame, structured_filters or [])
    if ntype == "DERIVE_COLUMN":
        return _derive_column(plan, frame)
    if ntype in ("JOIN", "UNION", "PIVOT"):
        return _unsupported(ntype, frame)
    # Unknown type — degrade safely, never guess.
    logger.info("[normalize] unknown normalization type %r — degrading", ntype)
    return NormalizationResult(frame, [f"NORMALIZE_UNSUPPORTED:{ntype}"], [], "degraded")


# ─────────────────────────────────────────────────────────────────────────────
# WIDE_TO_LONG
# ─────────────────────────────────────────────────────────────────────────────


def _wide_to_long(plan: NormalizationPlan, df: pd.DataFrame) -> NormalizationResult:
    """Melt the wide ``memberLabels`` columns into (memberVar, valueVar) long rows."""
    id_vars = [c for c in (plan.idVars or []) if c]
    missing_id = [c for c in id_vars if c not in df.columns]
    if not id_vars or missing_id:
        detail = missing_id or "(none specified)"
        return NormalizationResult(
            df, [f"NORMALIZE_WIDE_TO_LONG: missing idVars {detail}"], [], "degraded",
        )

    requested = [c for c in (plan.memberLabels or []) if c]
    present = [c for c in requested if c in df.columns]
    if not requested or not present:
        return NormalizationResult(
            df, [f"NORMALIZE_WIDE_TO_LONG: no member columns found from {requested}"], [], "degraded",
        )

    member_var = plan.memberVar or "member"
    value_var = plan.valueVar or "value"
    melted = df.melt(
        id_vars=id_vars, value_vars=present,
        var_name=member_var, value_name=value_var,
    )
    diagnostics: list[str] = []
    missing_members = [c for c in requested if c not in present]
    if missing_members:
        diagnostics.append(f"NORMALIZE_WIDE_TO_LONG: skipped absent member columns {missing_members}")
    transformations = [f"melt:id={id_vars};members={present}->{member_var}/{value_var}"]
    return NormalizationResult(melted, diagnostics, transformations, "ok")


# ─────────────────────────────────────────────────────────────────────────────
# FILTER_ROWS
# ─────────────────────────────────────────────────────────────────────────────


def _filter_rows(df: pd.DataFrame, structured_filters: list[str]) -> NormalizationResult:
    """Apply resolved structured ``col OP value`` filters (no arbitrary expressions)."""
    if not structured_filters:
        return NormalizationResult(
            df, ["NORMALIZE_FILTER_ROWS: no structured filters to apply"], [], "degraded",
        )
    filtered, applied = _apply_filters(df, structured_filters)
    transformations = [f"filter:{a}" for a in applied]
    if len(applied) < len(structured_filters):
        unapplied = [f for f in structured_filters if f not in applied]
        return NormalizationResult(
            filtered, [f"NORMALIZE_FILTER_ROWS: could not safely apply {unapplied}"],
            transformations, "degraded",
        )
    return NormalizationResult(filtered, [], transformations, "ok")


# ─────────────────────────────────────────────────────────────────────────────
# DERIVE_COLUMN — AST-whitelisted arithmetic (never eval/exec)
# ─────────────────────────────────────────────────────────────────────────────

# Operator nodes we allow, mapped to their (safe) implementations.
_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: _safe_div(a, b),
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARYOPS: dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Every AST node type permitted anywhere in a DERIVE_COLUMN expression.
_ALLOWED_NODES: tuple[type, ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.UAdd, ast.USub,
)


def _safe_div(a: Any, b: Any) -> Any:
    """Divide without raising or yielding ±inf — a zero denominator becomes NaN."""
    try:
        result = a / b
    except ZeroDivisionError:
        return float("nan")
    if isinstance(result, pd.Series):
        return result.replace([np.inf, -np.inf], np.nan)
    if isinstance(result, float) and math.isinf(result):
        return float("nan")
    return result


def _validate_expr(tree: ast.AST) -> tuple[bool, str]:
    """Return (ok, reason). Reject any node/name outside the arithmetic whitelist."""
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return False, f"disallowed {type(node).__name__}"
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                return False, "non-numeric constant"
        if isinstance(node, ast.Name):
            if node.id.startswith("__") or node.id.endswith("__"):
                return False, f"dunder name {node.id!r}"
    return True, ""


def _eval_expr(node: ast.AST, df: pd.DataFrame) -> Any:
    """Evaluate a pre-validated arithmetic node against ``df`` columns."""
    if isinstance(node, ast.Expression):
        return _eval_expr(node.body, df)
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_eval_expr(node.left, df), _eval_expr(node.right, df))
    if isinstance(node, ast.UnaryOp):
        return _UNARYOPS[type(node.op)](_eval_expr(node.operand, df))
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return pd.to_numeric(df[node.id], errors="coerce")
    raise ValueError(f"unexpected node {type(node).__name__}")


def _column_names(tree: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]


def _derive_column(plan: NormalizationPlan, df: pd.DataFrame) -> NormalizationResult:
    """Compute ``outputColumn = <expression>`` with the AST-whitelisted evaluator."""
    expr = (plan.expression or "").strip()
    out_col = (plan.outputColumn or "").strip()
    if not expr or not out_col:
        return NormalizationResult(
            df, ["NORMALIZE_DERIVE_COLUMN: missing expression or outputColumn"], [], "degraded",
        )

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return NormalizationResult(
            df, [f"NORMALIZE_UNSAFE_EXPRESSION: parse error ({exc.msg})"], [], "degraded",
        )

    ok, reason = _validate_expr(tree)
    if not ok:
        logger.info("[normalize] rejecting unsafe DERIVE_COLUMN %r: %s", expr, reason)
        return NormalizationResult(
            df, [f"NORMALIZE_UNSAFE_EXPRESSION: {reason}"], [], "degraded",
        )

    missing = [c for c in dict.fromkeys(_column_names(tree)) if c not in df.columns]
    if missing:
        return NormalizationResult(
            df, [f"NORMALIZE_MISSING_COLUMN: {missing}"], [], "degraded",
        )

    try:
        series = _eval_expr(tree, df)
    except Exception as exc:  # defensive — validation should prevent this
        return NormalizationResult(
            df, [f"NORMALIZE_DERIVE_FAILED: {exc}"], [], "degraded",
        )

    out = df.copy()
    out[out_col] = series
    return NormalizationResult(out, [], [f"derive:{out_col}={expr}"], "ok")


# ─────────────────────────────────────────────────────────────────────────────
# Unsupported reshapes — degrade clearly, never guess
# ─────────────────────────────────────────────────────────────────────────────


def _unsupported(ntype: str, df: pd.DataFrame) -> NormalizationResult:
    logger.info("[normalize] %s not implemented — degrading, frame unchanged", ntype)
    return NormalizationResult(df, [f"NORMALIZE_UNSUPPORTED:{ntype}"], [], "degraded")
