"""Phase 3C — scoring imputation options per column (no mutation)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from imputation.confidence_engine import imputation_blend
from imputation.knn_engine import knn_graph_support, score_knn
from imputation.mean_engine import score_mean
from imputation.median_engine import score_median
from imputation.mode_engine import score_mode
from outliers.distribution_engine import distribution_snippet
from validation.multi_column.relation_engine import extract_column_edges


def _prefetch_numeric_abs_corr_max(df: pd.DataFrame, schema: dict[str, str]) -> dict[str, float]:
    """One ``DataFrame.corr`` pass for all numeric columns (min_periods=8)."""
    num_cols = [c for c in df.columns if schema.get(c) == "numeric"]
    out: dict[str, float] = {str(c): 0.0 for c in df.columns}
    if len(num_cols) < 2:
        return out
    mat = pd.concat(
        [pd.to_numeric(df[c], errors="coerce") for c in num_cols],
        axis=1,
        keys=[str(c) for c in num_cols],
    )
    corr = mat.corr(min_periods=8)
    abs_corr = corr.abs()
    for c in abs_corr.columns:
        s = abs_corr[c].drop(labels=[c], errors="ignore")
        if s.empty:
            continue
        vmax = s.max(skipna=True)
        if pd.notna(vmax):
            out[str(c)] = float(vmax)
    return out


def _outlier_signal_for_column(anomaly_results: list[dict] | None, col: str, n_rows: int) -> float:
    if not anomaly_results:
        return 0.0
    for block in anomaly_results:
        if block.get("column") != col:
            continue
        zh = len(block.get("z_score_hits") or [])
        ih = len(block.get("iqr_hits") or [])
        return float(min(1.0, (zh + ih) / max(n_rows, 1)))


def imputation_confidence_band(score: float) -> str:
    if score >= 0.8:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def run_imputation_intelligence(
    df: pd.DataFrame,
    schema: dict[str, str],
    semantic_columns: dict[str, Any],
    dependency_graph: dict[str, Any] | None,
    schema_graph: dict[str, Any] | None,
    anomaly_column_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    edges = extract_column_edges(schema_graph or {}, dependency_graph or {})
    corr_max_by_col = _prefetch_numeric_abs_corr_max(df, schema)
    per_column: list[dict[str, Any]] = []
    flat_candidates: list[dict[str, Any]] = []

    n_rows = len(df)
    for col in df.columns:
        series = df[col]
        miss = int(series.isna().sum())
        miss_rate = float(miss / max(n_rows, 1))
        if miss == 0:
            continue

        meta = semantic_columns.get(str(col)) if isinstance(semantic_columns, dict) else {}
        meta = meta if isinstance(meta, dict) else {}
        sem_conf = float(meta.get("confidence") or 0.7)
        is_cat = schema.get(col) not in ("numeric",) and not pd.api.types.is_numeric_dtype(series)

        sn = distribution_snippet(series) if schema.get(col) == "numeric" else {}
        norm_hint = float(sn.get("normality_score") or 0.5) if sn else 0.45
        skew_abs = abs(float(sn.get("skewness") or 0.0)) if sn else 0.0
        osig = _outlier_signal_for_column(anomaly_column_blocks, str(col), n_rows)

        mean_s = score_mean(norm_hint, skew_abs) if not is_cat else 0.15
        med_s = score_median(skew_abs, osig) if not is_cat else 0.25
        mode_s = score_mode(series) if is_cat else min(0.35, 1.0 - norm_hint * 0.6)
        corr_m = 0.0 if is_cat else float(corr_max_by_col.get(str(col), 0.0))
        gs = knn_graph_support(str(col), edges)
        knn_s = 0.25 if is_cat else score_knn(corr_m, gs)

        scores = {"mean": round(mean_s, 4), "median": round(med_s, 4), "mode": round(mode_s, 4), "knn": round(knn_s, 4)}
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        key = ranked[0][0] if ranked else "median"
        rec_map = {"mean": "MEAN", "median": "MEDIAN", "mode": "MODE", "knn": "KNN"}
        recommended = rec_map.get(key, key.upper())

        dist_fit = float(max(scores.values()))
        feat_corr = float(corr_m if not is_cat else gs)
        miss_pat = float(max(0.0, 1.0 - miss_rate))
        dom_sup = sem_conf
        overall = imputation_blend(
            distribution_fit=dist_fit,
            feature_correlation=feat_corr,
            missing_pattern=miss_pat,
            domain_support=dom_sup,
        )
        band = imputation_confidence_band(overall)

        block = {
            "column": str(col),
            "missing_count": miss,
            "missing_rate": round(miss_rate, 4),
            "recommended": recommended,
            "mean": scores["mean"],
            "median": scores["median"],
            "mode": scores["mode"],
            "knn": scores["knn"],
            "confidence": overall,
            "confidence_band": band,
            "explain": {
                "is_categorical": bool(is_cat),
                "normality_hint": norm_hint if sn else None,
                "skewness": sn.get("skewness") if sn else None,
            },
        }
        per_column.append(block)

        flat_candidates.append(
            {
                "column": str(col),
                "missing_count": miss,
                "candidate_action": "IMPUTE",
                "alternate_actions": ["KEEP_MISSING", "REMOVE_COLUMN", "REMOVE_ROW"],
                "recommended_method": recommended,
                "confidence": overall,
                "confidence_band": band,
                "method_scores": scores,
            }
        )

    return {
        "imputation_results": per_column,
        "imputation_candidates": flat_candidates,
        "summary": {
            "columns_with_missing": len(per_column),
            "candidate_entries": len(flat_candidates),
        },
    }

