"""Context-Aware Rule Validation Engine.

Sits between Knowledge Graph construction and statistical anomaly detection
in the analysis pipeline. Replaces nothing — it consumes the discovered
rules from `rule_discovery.py`, executes them, classifies the violations,
and emits user-reviewable validation candidates.

End-to-end flow:

      Knowledge Graph
            |
            v
    discover_all_rules()        <- 5 sources: kg / ontology / library /
            |                                 statistical / archetype
            v
    [single-col rules]   [multi-col rules]
            |                    |
            v                    v
    execute_single_column     execute_multi_column
            |                    |
            +--------+-----------+
                     v
            classify_violations          <- CRITICAL / HIGH / MEDIUM / LOW
                     v
            score_rule_confidence        <- 5-factor calibrated confidence
                     v
            build_review_candidates      <- with kg_explanation per row
                     v
            (user reviews; AuditLog records each action)
                     v
            approved dataset -> Z-score / IQR
"""
from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from validation.rule_discovery import DiscoveredRule, discover_all_rules
from validation.rule_confidence import score_rule_confidence
from validation.violation_classifier import (
    classify_violation, relative_magnitude, severity_summary,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-column execution
# ---------------------------------------------------------------------------


def _matches_column(pattern: str, column: str) -> bool:
    if not pattern:
        return False
    try:
        return re.search(pattern, str(column)) is not None
    except re.error:
        return pattern == column


def execute_single_column_rule(
    df: pd.DataFrame,
    rule: DiscoveredRule,
    *,
    target_column: str,
) -> dict[str, Any] | None:
    """Run one rule against one column and return a violation block (or None)."""
    if target_column not in df.columns:
        return None
    s = df[target_column].reset_index(drop=True)
    params = rule.params or {}
    rt = rule.rule_type
    n = len(s)
    if n == 0:
        return None

    violations: list[dict[str, Any]] = []

    if rt == "numeric_between":
        lo, hi = float(params["min"]), float(params["max"])
        numeric = pd.to_numeric(s, errors="coerce")
        mask = (~numeric.isna()) & ((numeric < lo) | (numeric > hi))
        for pos in mask[mask].index.tolist():
            v = float(numeric.iloc[pos])
            violations.append({
                "row": int(pos), "value": v,
                "magnitude": relative_magnitude(v, lo, hi),
            })

    elif rt == "numeric_min":
        lo = float(params["min"])
        numeric = pd.to_numeric(s, errors="coerce")
        mask = (~numeric.isna()) & (numeric < lo)
        for pos in mask[mask].index.tolist():
            v = float(numeric.iloc[pos])
            violations.append({
                "row": int(pos), "value": v,
                "magnitude": relative_magnitude(v, lo, None),
            })

    elif rt == "numeric_max":
        hi = float(params["max"])
        numeric = pd.to_numeric(s, errors="coerce")
        mask = (~numeric.isna()) & (numeric > hi)
        for pos in mask[mask].index.tolist():
            v = float(numeric.iloc[pos])
            violations.append({
                "row": int(pos), "value": v,
                "magnitude": relative_magnitude(v, None, hi),
            })

    elif rt == "regex_or_null":
        patt = re.compile(str(params.get("pattern", "")))
        for pos in range(n):
            v = s.iloc[pos]
            if pd.isna(v):
                continue
            if not patt.fullmatch(str(v).strip()):
                violations.append({"row": int(pos), "value": v})

    elif rt == "categorical_in_set":
        allowed = {str(a).strip().lower() for a in (params.get("values_ci") or [])}
        for pos in range(n):
            v = s.iloc[pos]
            if pd.isna(v):
                continue
            if str(v).strip().lower() not in allowed:
                violations.append({"row": int(pos), "value": v})

    elif rt == "is_integer_like":
        numeric = pd.to_numeric(s, errors="coerce")
        mask = (~numeric.isna()) & ((numeric - numeric.round()).abs() > 1e-9)
        for pos in mask[mask].index.tolist():
            violations.append({"row": int(pos), "value": float(numeric.iloc[pos])})

    else:
        return None

    if not violations:
        return None

    return {
        "rule_id": rule.rule_id,
        "rule_type": rt,
        "kind": "single_column",
        "column": target_column,
        "violation_count": len(violations),
        "violation_rate": round(len(violations) / max(n, 1), 4),
        "violations": violations,
        "rule_source": rule.source,
        "rule_severity_hint": rule.severity,
        "explanation": rule.explanation,
        "kg_relationships": rule.kg_relationships,
        "confidence_signals": rule.confidence_signals,
    }


# ---------------------------------------------------------------------------
# Multi-column execution
# ---------------------------------------------------------------------------


def execute_multi_column_rule(
    df: pd.DataFrame,
    rule: DiscoveredRule,
) -> dict[str, Any] | None:
    """Run a multi-column rule. Supports types coming from rule_discovery."""
    rt = rule.rule_type
    params = rule.params or {}
    n = len(df)
    if n == 0:
        return None

    if rt == "aggregation_equals":
        comps = params.get("components") or rule.columns[:-1]
        target = params.get("target") or (rule.columns[-1] if rule.columns else None)
        tol = float(params.get("tolerance_rel", 0.01))
        if not comps or not target:
            return None
        comps = [c for c in comps if c in df.columns]
        if not comps or target not in df.columns:
            return None
        sum_comp = pd.concat(
            [pd.to_numeric(df[c], errors="coerce") for c in comps], axis=1
        ).sum(axis=1, min_count=1)
        tgt = pd.to_numeric(df[target], errors="coerce")
        denom = tgt.abs().replace(0, pd.NA)
        rel_err = (sum_comp - tgt).abs() / denom
        mask = (~tgt.isna()) & (~sum_comp.isna()) & (rel_err > tol)
        rows = mask[mask].index.tolist()
        if not rows:
            return None
        return {
            "rule_id": rule.rule_id,
            "rule_type": rt,
            "kind": "multi_column",
            "columns": comps + [target],
            "violation_count": len(rows),
            "violation_rate": round(len(rows) / max(n, 1), 4),
            "violations": [{"row": int(i), "components": comps, "target": target} for i in rows],
            "rule_source": rule.source,
            "rule_severity_hint": rule.severity,
            "explanation": rule.explanation,
            "kg_relationships": rule.kg_relationships,
            "confidence_signals": rule.confidence_signals,
        }

    if rt == "less_than_or_equal":
        left = params.get("left") or (rule.columns[0] if rule.columns else None)
        right = params.get("right") or (rule.columns[1] if len(rule.columns) > 1 else None)
        if not (left and right and left in df.columns and right in df.columns):
            return None
        l = pd.to_numeric(df[left], errors="coerce")
        r = pd.to_numeric(df[right], errors="coerce")
        mask = (~l.isna()) & (~r.isna()) & (l > r)
        rows = mask[mask].index.tolist()
        if not rows:
            return None
        return {
            "rule_id": rule.rule_id,
            "rule_type": rt,
            "kind": "multi_column",
            "columns": [left, right],
            "violation_count": len(rows),
            "violation_rate": round(len(rows) / max(n, 1), 4),
            "violations": [{"row": int(i), "left": left, "right": right} for i in rows],
            "rule_source": rule.source,
            "rule_severity_hint": rule.severity,
            "explanation": rule.explanation,
            "kg_relationships": rule.kg_relationships,
            "confidence_signals": rule.confidence_signals,
        }

    if rt == "date_order":
        left = params.get("left") or (rule.columns[0] if rule.columns else None)
        right = params.get("right") or (rule.columns[1] if len(rule.columns) > 1 else None)
        if not (left and right and left in df.columns and right in df.columns):
            return None
        l = pd.to_datetime(df[left], errors="coerce")
        r = pd.to_datetime(df[right], errors="coerce")
        mask = (~l.isna()) & (~r.isna()) & (l > r)
        rows = mask[mask].index.tolist()
        if not rows:
            return None
        return {
            "rule_id": rule.rule_id,
            "rule_type": rt,
            "kind": "multi_column",
            "columns": [left, right],
            "violation_count": len(rows),
            "violation_rate": round(len(rows) / max(n, 1), 4),
            "violations": [{"row": int(i), "left": left, "right": right} for i in rows],
            "rule_source": rule.source,
            "rule_severity_hint": rule.severity,
            "explanation": rule.explanation,
            "kg_relationships": rule.kg_relationships,
            "confidence_signals": rule.confidence_signals,
        }

    if rt == "correlation_consistency":
        if len(rule.columns) != 2:
            return None
        a, b = rule.columns
        if a not in df.columns or b not in df.columns:
            return None
        a_num = pd.to_numeric(df[a], errors="coerce")
        b_num = pd.to_numeric(df[b], errors="coerce")
        if a_num.dropna().size < 10 or b_num.dropna().size < 10:
            return None
        corr = a_num.corr(b_num)
        min_corr = float(params.get("min_corr", 0.30))
        if pd.isna(corr) or abs(corr) >= min_corr:
            return None
        # The whole-column violation: emit one synthetic row index for review
        return {
            "rule_id": rule.rule_id,
            "rule_type": rt,
            "kind": "multi_column",
            "columns": [a, b],
            "violation_count": 1,
            "violation_rate": 1.0,
            "violations": [{"row": -1, "observed_corr": float(corr)}],
            "rule_source": rule.source,
            "rule_severity_hint": rule.severity,
            "explanation": f"{rule.explanation}; observed correlation {corr:.2f} below expected {min_corr}",
            "kg_relationships": rule.kg_relationships,
            "confidence_signals": rule.confidence_signals,
        }

    return None


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_context_aware_validation(
    df: pd.DataFrame,
    *,
    columns_meta: dict[str, dict[str, Any]] | None = None,
    schema_graph: dict[str, Any] | None = None,
    priority_dependencies: dict[str, Any] | None = None,
    column_profiles: dict[str, Any] | None = None,
    unified_domains: list[dict[str, Any]] | None = None,
    archetypes: list[dict[str, Any]] | None = None,
    library_path: Any = None,
) -> dict[str, Any]:
    """Execute the validation gate.

    Output:
      {
        "rules_discovered": <int>,
        "single_column": [{ rule_id, column, violations[], severity, ... }, ...],
        "multi_column":  [{ rule_id, columns[], violations[], severity, ... }, ...],
        "summary": {
          "rules_discovered": N,
          "rules_fired": M,
          "severity_breakdown": {"CRITICAL": x, "HIGH": y, ...},
          "approved": bool,        # True when no CRITICAL violations
        },
        "validation_candidates": [...]  # row-level rollup for AGUI
      }
    """
    columns = list(df.columns)
    rules = discover_all_rules(
        columns=columns,
        columns_meta=columns_meta,
        schema_graph=schema_graph,
        priority_dependencies=priority_dependencies,
        column_profiles=column_profiles,
        unified_domains=unified_domains,
        archetypes=archetypes,
        library_path=library_path,
    )

    single_results: list[dict[str, Any]] = []
    multi_results: list[dict[str, Any]] = []

    for rule in rules:
        if rule.kind == "single_column":
            # The rule's `columns` may be a pattern (from the library) or an
            # explicit column name (from ontology / statistical / kg).
            target = rule.columns[0] if rule.columns else None
            if target and target in df.columns:
                hit = execute_single_column_rule(df, rule, target_column=target)
                if hit:
                    single_results.append(_finalize(hit, rule))
            elif target:
                # Treat as regex pattern — match every column that fits
                for col in columns:
                    if _matches_column(target, col):
                        hit = execute_single_column_rule(df, rule, target_column=col)
                        if hit:
                            single_results.append(_finalize(hit, rule))
        else:
            hit = execute_multi_column_rule(df, rule)
            if hit:
                multi_results.append(_finalize(hit, rule))

    candidates = _build_review_candidates(single_results + multi_results)
    sev_counts = severity_summary(candidates)
    approved = sev_counts["CRITICAL"] == 0

    return {
        "rules_discovered": len(rules),
        "single_column": single_results,
        "multi_column": multi_results,
        "summary": {
            "rules_discovered": len(rules),
            "rules_fired": len(single_results) + len(multi_results),
            "severity_breakdown": sev_counts,
            "candidate_count": len(candidates),
            "approved": approved,
            "source_breakdown": _source_counts(rules),
        },
        "validation_candidates": candidates,
    }


def _finalize(hit: dict[str, Any], rule: DiscoveredRule) -> dict[str, Any]:
    """Attach calibrated confidence + per-violation severity classification."""
    conf = score_rule_confidence(rule.confidence_signals or {})
    hit["confidence"] = round(conf.get("value", 0.5), 4)
    hit["confidence_band"] = conf.get("band", "medium")
    hit["confidence_explain"] = conf.get("explain")

    # Classify the rule overall + each violation row
    overall_severity = classify_violation(
        rule_source=rule.source,
        rule_type=rule.rule_type,
        severity_hint=rule.severity,
        violation_magnitude=max(
            (v.get("magnitude") or 0.0) for v in hit.get("violations") or [{}]
        ) if hit.get("violations") else None,
        rule_confidence=hit["confidence"],
    )
    hit["severity"] = overall_severity

    for v in hit.get("violations") or []:
        row_severity = classify_violation(
            rule_source=rule.source,
            rule_type=rule.rule_type,
            severity_hint=rule.severity,
            violation_magnitude=v.get("magnitude"),
            rule_confidence=hit["confidence"],
        )
        v["severity"] = row_severity
    return hit


def _build_review_candidates(
    rule_hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Row-level rollup the AGUI can render for user review."""
    out: list[dict[str, Any]] = []
    for hit in rule_hits:
        for v in hit.get("violations") or []:
            out.append({
                "rule_id": hit["rule_id"],
                "rule_type": hit["rule_type"],
                "kind": hit["kind"],
                "column": hit.get("column"),
                "columns": hit.get("columns"),
                "row": v.get("row"),
                "value": v.get("value"),
                "severity": v.get("severity") or hit.get("severity"),
                "confidence": hit.get("confidence"),
                "confidence_band": hit.get("confidence_band"),
                "rule_source": hit.get("rule_source"),
                "kg_relationships": hit.get("kg_relationships"),
                "explanation": hit.get("explanation"),
                "user_actions_allowed": [
                    "KEEP", "MODIFY", "TREAT_AS_MISSING", "REMOVE_ROW", "IGNORE_RULE",
                ],
            })
    # CRITICAL first, then HIGH, then MEDIUM, then LOW; within same severity by confidence desc
    _rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    out.sort(
        key=lambda c: (_rank.get(str(c["severity"]).upper(), 0), float(c.get("confidence") or 0)),
        reverse=True,
    )
    return out


def _source_counts(rules: list[DiscoveredRule]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rules:
        out[r.source] = out.get(r.source, 0) + 1
    return out
