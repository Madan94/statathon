"""Validation Gate — runs between KG construction and Z-score/IQR.

This module is the bridge piece the spec calls for:

    Knowledge Graph
          v
    Single Column Validation
          v
    Multi Column Validation
          v
    User Decisions
          v
    Z-Score / IQR / Missing Value Intelligence

It composes:
  * validation.rule_discovery.discover_all_rules
  * validation.context_aware_engine.run_context_aware_validation
  * validation.audit_log.AuditLog (for recording user decisions)

The pipeline orchestrator should call `run_validation_gate(...)` AFTER the
KG sync step and BEFORE `build_anomaly_intelligence` /
`run_imputation_intelligence`. The returned bundle is written into the
AnalysisState as `state.validation_gate` and `state.validation_candidates`.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from validation.audit_log import AuditEntry, AuditLog
from validation.context_aware_engine import run_context_aware_validation

logger = logging.getLogger(__name__)


def run_validation_gate(
    df: pd.DataFrame,
    *,
    columns_meta: dict[str, dict[str, Any]] | None = None,
    schema_graph: dict[str, Any] | None = None,
    priority_dependencies: dict[str, Any] | None = None,
    column_profiles: dict[str, Any] | None = None,
    unified_domains: list[dict[str, Any]] | None = None,
    archetypes: list[dict[str, Any]] | None = None,
    column_normalization: list[dict[str, Any]] | None = None,
    library_path: Any = None,
    analysis_id: int | None = None,
) -> dict[str, Any]:
    """Run the validation gate. Returns:

        {
          "rules_discovered": int,
          "single_column":    [...],
          "multi_column":     [...],
          "validation_candidates": [...],   # row-level for AGUI
          "summary": {
              "rules_discovered": int,
              "rules_fired":      int,
              "severity_breakdown": {CRITICAL, HIGH, MEDIUM, LOW},
              "candidate_count":  int,
              "approved":         bool,     # True when CRITICAL == 0
              "source_breakdown": {kg, ontology, library, statistical, archetype},
          },
        }
    """
    out = run_context_aware_validation(
        df,
        columns_meta=columns_meta,
        schema_graph=schema_graph,
        priority_dependencies=priority_dependencies,
        column_profiles=column_profiles,
        unified_domains=unified_domains,
        archetypes=archetypes,
        library_path=library_path,
        column_normalization=column_normalization,
    )
    summary = out.get("summary") or {}
    sev = summary.get("severity_breakdown") or {}
    logger.info(
        "Validation gate (analysis=%s): %s rules discovered, %s fired, "
        "severity=%s, approved=%s",
        analysis_id, summary.get("rules_discovered"),
        summary.get("rules_fired"), sev, summary.get("approved"),
    )
    return out


def record_user_action(
    *,
    analysis_id: int | None,
    rule_id: str,
    rule_type: str,
    column: str,
    row_id: int | None,
    old_value: Any,
    new_value: Any,
    user_action: str,
    confidence: float,
    severity: str = "MEDIUM",
    user_id: int | None = None,
    diagnostics: dict[str, Any] | None = None,
    audit_log: AuditLog | None = None,
) -> int:
    """Persist one user decision to the audit trail."""
    log = audit_log or AuditLog()
    return log.append(AuditEntry(
        rule_id=rule_id, rule_type=rule_type,
        column=column, row_id=row_id,
        old_value=old_value, new_value=new_value,
        user_action=user_action, confidence=float(confidence),
        severity=severity.upper(),
        user_id=user_id, analysis_id=analysis_id,
        diagnostics=diagnostics or {},
    ))


def apply_user_decisions(
    df: pd.DataFrame,
    decisions: list[dict[str, Any]],
) -> pd.DataFrame:
    """Apply user decisions to a DataFrame and return the validated copy.

    Each decision is a dict:
        {
          "rule_id": str, "row_id": int, "column": str,
          "user_action": KEEP|MODIFY|TREAT_AS_MISSING|REMOVE_ROW|IGNORE_RULE,
          "new_value": <any> (only for MODIFY)
        }

    Order of operations:
      1. REMOVE_ROW decisions are collected and applied last so row indices
         used by earlier MODIFY / TREAT_AS_MISSING decisions stay stable.
      2. TREAT_AS_MISSING sets the cell to NaN.
      3. MODIFY writes `new_value`.
      4. KEEP / IGNORE_RULE no-op.
    """
    if df.empty or not decisions:
        return df.copy()

    out = df.copy()
    rows_to_drop: set[int] = set()
    for d in decisions:
        action = str(d.get("user_action") or "").upper()
        row_id = d.get("row_id")
        col = d.get("column")
        if col and col not in out.columns:
            continue
        if action in ("KEEP", "IGNORE_RULE"):
            continue
        if action == "REMOVE_ROW" and isinstance(row_id, int):
            rows_to_drop.add(int(row_id))
            continue
        if action == "TREAT_AS_MISSING" and isinstance(row_id, int) and col in out.columns:
            try:
                out.at[out.index[row_id], col] = None
            except Exception as exc:
                logger.info("TREAT_AS_MISSING failed for row %s col %s: %s", row_id, col, exc)
            continue
        if action == "MODIFY" and isinstance(row_id, int) and col in out.columns:
            try:
                out.at[out.index[row_id], col] = d.get("new_value")
            except Exception as exc:
                logger.info("MODIFY failed for row %s col %s: %s", row_id, col, exc)

    if rows_to_drop:
        keep = [i for i in range(len(out)) if i not in rows_to_drop]
        out = out.iloc[keep].reset_index(drop=True)
    return out
