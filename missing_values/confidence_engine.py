"""Missing-value method suitability scoring for review UI."""
from __future__ import annotations

from typing import Any

import pandas as pd

from imputation.imputation_manager import run_imputation_intelligence


def evaluate_column_methods(
    df: pd.DataFrame,
    schema: dict[str, str],
    column: str,
    *,
    semantic_confidence: float = 0.5,
    anomaly_results: list[dict[str, Any]] | None = None,
    graph_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score mean/median/mode/knn for one column (no mutation)."""
    subset = df[[column]].copy() if column in df.columns else df.iloc[:, :0]
    if subset.empty:
        return {
            "column": column,
            "recommended": "median",
            "confidence": 0.0,
            "alternatives": [],
            "reason": "column not found",
            "method_scores": {},
        }

    full = run_imputation_intelligence(
        df,
        schema,
        semantic_columns={column: {"confidence": semantic_confidence}},
        dependency_graph=None,
        schema_graph={"edges": graph_edges or []},
        anomaly_column_blocks=anomaly_results,
    )
    block = next(
        (r for r in full.get("imputation_results") or [] if r.get("column") == column),
        None,
    )
    if not block:
        return {
            "column": column,
            "recommended": "median",
            "confidence": 0.0,
            "alternatives": [],
            "reason": "no missing values",
            "method_scores": {},
        }

    scores = {
        "mean": float(block.get("mean") or 0),
        "median": float(block.get("median") or 0),
        "mode": float(block.get("mode") or 0),
        "knn": float(block.get("knn") or 0),
    }
    ranked = block.get("ranked_methods") or []
    alternatives = [
        {"method": r.get("method", "").lower(), "score": r.get("score"), "reason": r.get("reason")}
        for r in ranked
        if isinstance(r, dict)
    ]
    recommended = str(block.get("recommended") or "median").lower()
    reason = next(
        (a.get("reason") for a in alternatives if str(a.get("method")).lower() == recommended),
        "distribution-based recommendation",
    )
    return {
        "column": column,
        "recommended": recommended,
        "confidence": float(block.get("confidence") or 0),
        "confidence_band": block.get("confidence_band"),
        "alternatives": alternatives,
        "reason": reason,
        "method_scores": scores,
        "missing_count": block.get("missing_count"),
        "explain": block.get("explain"),
    }
