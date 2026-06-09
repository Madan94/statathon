"""Outlier workflow: goodness-of-fit + recommendations first, detection on user choice."""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from outliers.column_types import is_numeric_column
from outliers.confidence_engine import anomaly_row_confidence
from outliers.fit_engine import method_recommendation
from outliers.goodness_of_fit import build_goodness_of_fit_bundle
from outliers.iqr_engine import iqr_records
from outliers.zscore_engine import zscore_records

MethodChoice = Literal["Z_SCORE", "IQR"]


def build_outlier_method_analysis(
    df: pd.DataFrame,
    schema: dict[str, str],
) -> dict[str, Any]:
    """Step 1+2: goodness-of-fit and confidence scores — no detection."""
    gof = build_goodness_of_fit_bundle(df, schema)
    gof_by_col = {g["column"]: g for g in gof}

    per_column: list[dict[str, Any]] = []
    for col in df.columns:
        if not is_numeric_column(schema.get(col), df[col]):
            continue
        pick = method_recommendation(df[col])
        col_gof = gof_by_col.get(str(col), {})
        if pick.get("distribution_hint") and col_gof.get("shapiro_w_statistic") is None:
            hint = pick["distribution_hint"]
            if isinstance(hint, dict) and hint.get("shapiro_w_statistic") is not None:
                col_gof = {**col_gof, "shapiro_w_statistic": hint.get("shapiro_w_statistic")}
        per_column.append(
            {
                "column": str(col),
                "goodness_of_fit": col_gof,
                "recommended": pick.get("recommended"),
                "z_score_confidence": pick.get("z_score_confidence"),
                "iqr_confidence": pick.get("iqr_confidence"),
                "reason": pick.get("reason"),
                "z_score_pros": pick.get("z_score_pros"),
                "z_score_cons": pick.get("z_score_cons"),
                "iqr_pros": pick.get("iqr_pros"),
                "iqr_cons": pick.get("iqr_cons"),
                "distribution_hint": pick.get("distribution_hint"),
                "method_selected": None,
                "detection_run": False,
                "z_score_hits": [],
                "iqr_hits": [],
            }
        )

    return {
        "anomaly_results": per_column,
        "anomaly_candidates": [],
        "goodness_of_fit": gof,
        "method_selections": {},
        "summary": {
            "numeric_columns_scanned": len(per_column),
            "candidate_flags": 0,
            "awaiting_method_selection": len(per_column),
        },
    }


def detect_outliers_for_column(
    df: pd.DataFrame,
    schema: dict[str, str],
    column: str,
    method: MethodChoice,
    *,
    column_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Step 4: run detection for one column after user selects method."""
    if column not in df.columns:
        return {"column": column, "candidates": [], "hits": []}
    if not is_numeric_column(schema.get(column), df[column]):
        return {"column": column, "candidates": [], "hits": []}

    series = df[column]
    if method == "Z_SCORE":
        hits = zscore_records(series, column)
        method_conf = float((column_block or {}).get("z_score_confidence") or 70) / 100.0
    else:
        hits = iqr_records(series, column)
        method_conf = float((column_block or {}).get("iqr_confidence") or 70) / 100.0

    candidates: list[dict[str, Any]] = []
    for hit in hits:
        conf = anomaly_row_confidence(method_conf, hit.get("severity"))
        explain: dict[str, Any] = {
            "primary_method": method,
            "method_used": method,
            "severity_band": hit.get("severity"),
            "metric": hit.get("z_abs") if method == "Z_SCORE" else hit.get("iqr_excess"),
            "reason": hit.get("reason"),
        }
        if method == "Z_SCORE":
            explain["z_abs"] = hit.get("z_abs")
            explain["thresholds"] = hit.get("thresholds")
        else:
            explain["iqr_excess"] = hit.get("iqr_excess")
            explain["fence_multiplier"] = hit.get("fence_multiplier")

        candidates.append(
            {
                "row": int(hit["row"]),
                "column": column,
                "value": hit.get("value"),
                "method": method,
                "confidence": conf,
                "severity": hit.get("severity"),
                "candidate_action": "REVIEW",
                "alternate_actions": ["KEEP", "NORMALIZE", "DELETE_VALUE", "DELETE_ROW", "EDIT_VALUE"],
                "explain": explain,
            }
        )

    return {
        "column": column,
        "method": method,
        "hits": hits,
        "candidates": candidates,
    }


def merge_column_detection(
    anomaly_results: list[dict[str, Any]],
    anomaly_candidates: list[dict[str, Any]],
    column: str,
    method: MethodChoice,
    detection: dict[str, Any],
    *,
    column_aliases: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Update stored results after user-triggered detection."""
    aliases = column_aliases or {column}
    updated_results = []
    for block in anomaly_results:
        bcol = str(block.get("column") or "")
        borig = str(block.get("original_column") or "")
        if bcol in aliases or borig in aliases:
            block = dict(block)
            block["method_selected"] = method
            block["detection_run"] = True
            if method == "Z_SCORE":
                block["z_score_hits"] = detection.get("hits") or []
                block["iqr_hits"] = []
            else:
                block["iqr_hits"] = detection.get("hits") or []
                block["z_score_hits"] = []
        updated_results.append(block)

    filtered = [c for c in anomaly_candidates if str(c.get("column") or "") not in aliases]
    filtered.extend(detection.get("candidates") or [])
    return updated_results, filtered


# Backward-compatible alias used by smoke tests
def build_anomaly_intelligence(df: pd.DataFrame, schema: dict[str, str]) -> dict[str, Any]:
    return build_outlier_method_analysis(df, schema)
