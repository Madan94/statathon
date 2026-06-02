"""Single-column deterministic rule evaluation (no deletes)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.single_column.confidence_engine import rule_confidence, semantic_dtype_alignment
from validation.single_column.rule_repository import CompiledRule


def _is_cat_like(series: pd.Series, max_distinct_ratio: float = 0.12) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return False
    u = non_null.nunique()
    ratio = float(u) / max(len(non_null), 1)
    return not pd.api.types.is_numeric_dtype(series) or ratio <= max_distinct_ratio


def evaluate_rule_positions(series: pd.Series, rule: CompiledRule) -> tuple[list[int], str]:
    """
    Violations as **positional** row indices 0 .. len-1 aligned to ``series``.
    """
    rule_type = rule.rule_type
    params = rule.params
    diagnostics: list[str] = []

    if rule_type == "numeric_between":
        s = pd.to_numeric(series, errors="coerce")
        lo, hi = float(params["min"]), float(params["max"])
        mask = (~s.isna()) & ((s < lo) | (s > hi))
    elif rule_type == "numeric_min":
        s = pd.to_numeric(series, errors="coerce")
        lo = float(params["min"])
        mask = (~s.isna()) & (s < lo)
    elif rule_type == "numeric_max":
        s = pd.to_numeric(series, errors="coerce")
        hi = float(params["max"])
        mask = (~s.isna()) & (s > hi)
    elif rule_type == "is_integer_like":
        s = pd.to_numeric(series, errors="coerce")
        # True (violation) if numeric but not (approximately) integer
        mask = (~s.isna()) & ((s - s.round()).abs() > 1e-9)
    elif rule_type == "regex_or_null":
        import re

        patt = re.compile(str(params["pattern"]))
        vals = series.values
        nm = []

        def _matches(v):
            if pd.isna(v):
                return True
            return patt.fullmatch(str(v).strip()) is not None

        for i, v in enumerate(vals):
            nm.append(False if _matches(v) else True)
        mask = pd.Series(nm, dtype=bool, index=series.index)
        diagnostics.append("regex_allow_null")

    elif rule_type == "categorical_in_set":
        allowed_raw = params.get("values_ci") or []
        allowed = {str(a).strip().lower() for a in allowed_raw}

        def _ok(v):
            if pd.isna(v):
                return True
            return str(v).strip().lower() in allowed

        mask = ~series.reset_index(drop=True).map(_ok)
        diagnostics.append("categorical_set")
        positions = mask[mask].index.tolist()
        return sorted(int(i) for i in positions), ";".join(diagnostics) + f";violations={len(positions)}"

    else:
        return [], f"unsupported_rule_type:{rule_type}"

    positions_raw = []
    mask_bool = mask.to_numpy(dtype=bool)
    for i, flag in enumerate(mask_bool):
        if flag:
            positions_raw.append(i)
    diagnostics.append(f"violations={len(positions_raw)}")
    return positions_raw, ";".join(diagnostics)


def run_single_column_rules(
    df: pd.DataFrame,
    column: str,
    meta: dict[str, Any],
    rules: list[CompiledRule],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    semantic_domain = meta.get("domain")
    semantic_sub = meta.get("subdomain") or meta.get("sub_domain")
    sem_conf = float(meta.get("confidence") or 0.75)
    s = df[column].reset_index(drop=True)
    is_num = pd.api.types.is_numeric_dtype(s) or pd.to_numeric(s, errors="coerce").notna().mean() > 0.95
    is_cat = _is_cat_like(s if not is_num else pd.to_numeric(s, errors="coerce"))

    n = len(df)

    # Re-compile rules targeting this column semantics
    filtered = rules
    for rule in filtered:
        dtype_alignment = semantic_dtype_alignment(rule.rule_type, is_numeric=bool(is_num), is_cat_like=is_cat)
        viol_ix, diag = evaluate_rule_positions(s, rule)
        violation_frac = float(len(viol_ix)) / max(n, 1)
        confidence = rule_confidence(
            semantic_confidence=sem_conf,
            dtype_alignment=dtype_alignment,
            violation_frac=violation_frac,
        )
        out.append(
            {
                "column": column,
                "rule_id": rule.rule_id,
                "rule": rule.rule_name,
                "rule_expression": rule.rule_name,
                "violations": viol_ix,
                "confidence": confidence,
                "severity": rule.severity,
                "explain": diag,
                "domain": semantic_domain,
                "subdomain": semantic_sub,
            }
        )
    return out
