"""Assemble anomaly intelligence + row-level candidates with explainable confidence."""
from __future__ import annotations

from typing import Any

import pandas as pd

from outliers.confidence_engine import anomaly_row_confidence
from outliers.fit_engine import method_recommendation
from outliers.iqr_engine import iqr_records
from outliers.isolation_engine import isolation_records
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
        iso_rows = isolation_records(series, str(col))

        preferred = pick.get("recommended") or "Z_SCORE"

        # For the new ROBUST_ENSEMBLE pick combine z + iqr + iso.
        if preferred == "ROBUST_ENSEMBLE":
            primary_rows = z_rows + i_rows
            primary_conf = max(
                float(pick.get("z_score_confidence") or 0),
                float(pick.get("iqr_confidence") or 0),
                0.6,
            )
        elif preferred == "Z_SCORE":
            primary_rows = z_rows
            primary_conf = float(pick.get("z_score_confidence") or 0)
        else:
            primary_rows = i_rows
            primary_conf = float(pick.get("iqr_confidence") or 0)

        per_column.append(
            {
                "column": str(col),
                "recommended": preferred,
                "z_score_confidence": pick.get("z_score_confidence"),
                "iqr_confidence": pick.get("iqr_confidence"),
                "distribution_hint": pick.get("distribution_hint"),
                "rationale": pick.get("rationale"),
                "score_breakdown": pick.get("score_breakdown"),
                "z_score_hits": z_rows,
                "iqr_hits": i_rows,
                "isolation_hits": iso_rows,
            }
        )

        seen: set[tuple[int, str]] = set()
        for hit in primary_rows + iso_rows:
            key = (int(hit["row"]), str(hit.get("method") or ""))
            if key in seen:
                continue
            seen.add(key)
            method = str(hit.get("method") or preferred)
            base_mc = primary_conf if method != "ISOLATION_FOREST" else max(
                primary_conf,
                float(pick.get("iqr_confidence") or 0),
                0.45,
            )
            conf = anomaly_row_confidence(base_mc, hit.get("severity"))

            explain = {
                "primary_method": preferred,
                "method_used": method,
                "rationale": pick.get("rationale"),
                "method_confidence": primary_conf,
                "severity_band": hit.get("severity"),
                "distribution_hint": pick.get("distribution_hint"),
            }
            if method == "Z_SCORE":
                explain["z_abs"] = hit.get("z_abs")
                explain["thresholds"] = hit.get("thresholds")
            elif method == "IQR":
                explain["iqr_excess"] = hit.get("iqr_excess")
                explain["fence_multiplier"] = hit.get("fence_multiplier")
                explain["fence_bounds"] = [hit.get("q1"), hit.get("q3"), hit.get("iqr")]
            elif method == "ISOLATION_FOREST":
                explain["isolation_score"] = hit.get("score")

            flat_candidates.append(
                {
                    "row": int(hit["row"]),
                    "column": str(col),
                    "value": hit.get("value"),
                    "method": method,
                    "confidence": conf,
                    "severity": hit.get("severity"),
                    "candidate_action": "REMOVE_VALUE",
                    "alternate_actions": ["KEEP", "REMOVE_ROW", "MARK_VALID"],
                    "explain": explain,
                }
            )

    return {
        "anomaly_results": per_column,
        "anomaly_candidates": flat_candidates,
        "summary": {
            "numeric_columns_scanned": len(per_column),
            "candidate_flags": len(flat_candidates),
            "method_breakdown": _count_methods(flat_candidates),
        },
    }


def _count_methods(flat_candidates: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in flat_candidates:
        m = str(c.get("method") or "UNKNOWN")
        out[m] = out.get(m, 0) + 1
    return out
