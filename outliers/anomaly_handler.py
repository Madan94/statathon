"""Assemble anomaly intelligence + row-level candidates (no mutation)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from outliers.confidence_engine import anomaly_row_confidence
from outliers.fit_engine import method_recommendation
from outliers.iqr_engine import iqr_records
from outliers.zscore_engine import zscore_records


def build_anomaly_intelligence(
    df: pd.DataFrame,
    schema: dict[str, str],
) -> dict[str, Any]:
    per_column: list[dict[str, Any]] = []
    flat_candidates: list[dict[str, Any]] = []

    for col in df.columns:
        if schema.get(col) != "numeric":
            continue
        series = df[col]
        pick = method_recommendation(series)
        z_rows = zscore_records(series, str(col))
        i_rows = iqr_records(series, str(col))
        preferred = pick.get("recommended") or "Z_SCORE"
        primary = z_rows if preferred == "Z_SCORE" else i_rows
        mc = float(pick.get("z_score_confidence") or 0) if preferred == "Z_SCORE" else float(
            pick.get("iqr_confidence") or 0
        )
        per_column.append(
            {
                "column": str(col),
                "recommended": preferred,
                "z_score_confidence": pick.get("z_score_confidence"),
                "iqr_confidence": pick.get("iqr_confidence"),
                "distribution_hint": pick.get("distribution_hint"),
                "z_score_hits": z_rows,
                "iqr_hits": i_rows,
            }
        )
        for hit in primary:
            conf = anomaly_row_confidence(mc, hit.get("severity"))
            flat_candidates.append(
                {
                    "row": int(hit["row"]),
                    "column": str(col),
                    "value": hit.get("value"),
                    "method": hit.get("method"),
                    "confidence": conf,
                    "severity": hit.get("severity"),
                    "candidate_action": "REMOVE_VALUE",
                    "alternate_actions": ["KEEP", "REMOVE_ROW", "MARK_VALID"],
                    "explain": {"primary_method": preferred, "metric": hit.get("z_abs") or hit.get("iqr_excess")},
                }
            )

    return {
        "anomaly_results": per_column,
        "anomaly_candidates": flat_candidates,
        "summary": {
            "numeric_columns_scanned": len(per_column),
            "candidate_flags": len(flat_candidates),
        },
    }
