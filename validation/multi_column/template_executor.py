"""Execute multi-column rule templates from the validation_rule_library.json.

Templates (declared under `multi_column_rules`):
  * less_than_or_equal     left <= right within tolerance
  * aggregation_equals     sum(components) [+/- sum(second_components)] ≈ target
  * date_order             pd.to_datetime(left) <= pd.to_datetime(right)

Each violation is row-level and tagged with the rule_id + diagnostics so the
existing violation engine and AGUI candidate UI can render it consistently.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def load_multi_column_rules(rule_library_path: str | Path) -> list[dict[str, Any]]:
    path = Path(rule_library_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse rule library: %s", exc)
        return []
    rules = data.get("multi_column_rules") if isinstance(data, dict) else None
    return [r for r in (rules or []) if isinstance(r, dict)]


def _resolve(patterns: list[str], df: pd.DataFrame) -> list[str]:
    """Return all df columns that match any of the regex patterns."""
    out: list[str] = []
    for p in patterns or []:
        try:
            rx = re.compile(p)
        except re.error:
            continue
        for c in df.columns:
            if rx.search(str(c)) and c not in out:
                out.append(str(c))
    return out


def _resolve_single(pattern: str, df: pd.DataFrame) -> str | None:
    matches = _resolve([pattern], df)
    return matches[0] if matches else None


def run_multi_column_rules(
    df: pd.DataFrame,
    rule_library_path: str | Path,
) -> list[dict[str, Any]]:
    rules = load_multi_column_rules(rule_library_path)
    if not rules:
        return []

    out: list[dict[str, Any]] = []
    n = len(df)
    if n == 0:
        return []

    for rule in rules:
        kind = rule.get("kind")
        rule_id = str(rule.get("id") or "multi_rule")
        severity = str(rule.get("severity") or "medium")
        domain = rule.get("domain")
        try:
            if kind == "less_than_or_equal":
                left_col = _resolve_single(rule.get("left", ""), df)
                right_col = _resolve_single(rule.get("right", ""), df)
                if not (left_col and right_col):
                    continue
                left = pd.to_numeric(df[left_col], errors="coerce")
                right = pd.to_numeric(df[right_col], errors="coerce")
                mask = (~left.isna()) & (~right.isna()) & (left > right)
                viols = mask[mask].index.tolist()
                if viols:
                    out.append({
                        "rule_id": rule_id,
                        "kind": kind,
                        "domain": domain,
                        "columns": [left_col, right_col],
                        "violations": [int(i) for i in viols],
                        "violation_count": len(viols),
                        "violation_rate": round(len(viols) / max(n, 1), 4),
                        "severity": severity,
                        "explain": f"{left_col} > {right_col} in {len(viols)} rows",
                    })

            elif kind == "aggregation_equals":
                comps = _resolve(rule.get("components") or [], df)
                seconds = _resolve(rule.get("second_components") or [], df)
                target_col = _resolve_single(rule.get("target", ""), df)
                aggregator = rule.get("aggregator") or "+"
                tol_rel = float(rule.get("tolerance_rel") or 0.01)
                if not (comps and target_col):
                    continue
                left_sum = pd.concat(
                    [pd.to_numeric(df[c], errors="coerce") for c in comps],
                    axis=1,
                ).sum(axis=1, min_count=1)
                if seconds:
                    right_sum = pd.concat(
                        [pd.to_numeric(df[c], errors="coerce") for c in seconds],
                        axis=1,
                    ).sum(axis=1, min_count=1)
                    if aggregator == "+":
                        composite = left_sum + right_sum
                    elif aggregator == "-":
                        composite = left_sum - right_sum
                    else:
                        composite = left_sum
                else:
                    composite = left_sum
                target = pd.to_numeric(df[target_col], errors="coerce")
                denom = target.abs().replace(0, pd.NA)
                rel_err = (composite - target).abs() / denom
                mask = (~target.isna()) & (~composite.isna()) & (rel_err > tol_rel)
                viols = mask[mask].index.tolist()
                if viols:
                    out.append({
                        "rule_id": rule_id,
                        "kind": kind,
                        "domain": domain,
                        "columns": comps + seconds + [target_col],
                        "violations": [int(i) for i in viols],
                        "violation_count": len(viols),
                        "violation_rate": round(len(viols) / max(n, 1), 4),
                        "severity": severity,
                        "explain": (
                            f"sum({comps}){' '+aggregator+' sum('+str(seconds)+')' if seconds else ''} "
                            f"≠ {target_col} (rel_tol={tol_rel}) in {len(viols)} rows"
                        ),
                    })

            elif kind == "date_order":
                left_col = _resolve_single(rule.get("left", ""), df)
                right_col = _resolve_single(rule.get("right", ""), df)
                if not (left_col and right_col):
                    continue
                left = pd.to_datetime(df[left_col], errors="coerce")
                right = pd.to_datetime(df[right_col], errors="coerce")
                mask = (~left.isna()) & (~right.isna()) & (left > right)
                viols = mask[mask].index.tolist()
                if viols:
                    out.append({
                        "rule_id": rule_id,
                        "kind": kind,
                        "domain": domain,
                        "columns": [left_col, right_col],
                        "violations": [int(i) for i in viols],
                        "violation_count": len(viols),
                        "violation_rate": round(len(viols) / max(n, 1), 4),
                        "severity": severity,
                        "explain": f"{left_col} > {right_col} (date) in {len(viols)} rows",
                    })

        except Exception as exc:
            logger.warning("Multi-column rule %s failed: %s", rule_id, exc)
            continue

    return out
