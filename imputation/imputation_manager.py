"""Phase 3C — scoring imputation options per column (no mutation).

V2 improvements:
  * Missing-mechanism detection (MCAR / MAR / MNAR_SUSPECTED) per column.
  * KNN scoring validated via KS-test between donor and target column.
  * Ranked recommendation with per-method `reason` and full audit trail.
  * Calibrated confidence via `analytics.default_calibrator`.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from analytics import default_calibrator
from imputation.confidence_engine import imputation_blend
from imputation.knn_engine import knn_graph_support, score_knn, validate_knn_donors
from imputation.mean_engine import score_mean
from imputation.median_engine import score_median
from imputation.missing_mechanism import detect_missing_mechanism
from imputation.mode_engine import score_mode
from outliers.distribution_engine import distribution_snippet
from validation.multi_column.relation_engine import extract_column_edges


def _prefetch_numeric_abs_corr_max(
    df: pd.DataFrame, schema: dict[str, str]
) -> tuple[dict[str, float], pd.DataFrame | None]:
    """One ``DataFrame.corr`` pass for all numeric columns.

    Returns (max-abs-corr per column, the full numeric matrix for downstream
    KS-test donor validation).
    """
    num_cols = [c for c in df.columns if schema.get(c) == "numeric"]
    out: dict[str, float] = {str(c): 0.0 for c in df.columns}
    if len(num_cols) < 2:
        return out, None
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
    return out, mat


def _outlier_signal_for_column(
    anomaly_results: list[dict] | None, col: str, n_rows: int
) -> float:
    if not anomaly_results:
        return 0.0
    for block in anomaly_results:
        if block.get("column") != col:
            continue
        zh = len(block.get("z_score_hits") or [])
        ih = len(block.get("iqr_hits") or [])
        return float(min(1.0, (zh + ih) / max(n_rows, 1)))
    return 0.0


def imputation_confidence_band(score: float) -> str:
    if score >= 0.8:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def _build_method_reasons(
    *,
    is_cat: bool,
    norm_hint: float,
    skew_abs: float,
    osig: float,
    miss_rate: float,
    mechanism: str,
    knn_donor_quality: float,
    scores: dict[str, float],
) -> dict[str, str]:
    """One-line plain-English reason per method (shown in UI)."""
    reasons: dict[str, str] = {}
    if is_cat:
        reasons["mode"] = "categorical column: mode is the natural choice"
        reasons["mean"] = "categorical column: mean not applicable"
        reasons["median"] = "categorical column: median not applicable"
    else:
        if norm_hint >= 0.6 and skew_abs <= 0.5:
            reasons["mean"] = (
                f"near-normal distribution (skew={skew_abs:.2f}); "
                f"mean is unbiased under MCAR"
            )
        else:
            reasons["mean"] = (
                f"non-normal distribution (skew={skew_abs:.2f}); "
                f"mean would be pulled by tails"
            )
        if skew_abs > 0.5 or osig > 0.02:
            reasons["median"] = (
                f"skewed/outlier-influenced (skew={skew_abs:.2f}, outlier_signal={osig:.2f}); "
                f"median is robust"
            )
        else:
            reasons["median"] = "median works but mean is more efficient on symmetric data"
        reasons["mode"] = (
            "use mode only for low-cardinality numerics (e.g. flags)"
            if scores.get("mode", 0) < 0.4 else "low cardinality detected; mode plausible"
        )
    if mechanism == "MAR":
        reasons["knn"] = (
            f"MAR mechanism + donor quality {knn_donor_quality:.2f}: KNN leverages predictors"
        )
    elif mechanism == "MCAR":
        reasons["knn"] = (
            "MCAR mechanism: KNN is acceptable but offers no edge over simple methods"
        )
    elif mechanism == "MNAR_SUSPECTED":
        reasons["knn"] = (
            "MNAR suspected: KNN may still bias because observed values miss the relevant range"
        )
    else:
        reasons["knn"] = f"donor quality {knn_donor_quality:.2f}"
    if miss_rate > 0.4:
        for k in reasons:
            reasons[k] += f" | high missing rate ({miss_rate:.0%}) increases uncertainty"
    return reasons


def run_imputation_intelligence(
    df: pd.DataFrame,
    schema: dict[str, str],
    semantic_columns: dict[str, Any],
    dependency_graph: dict[str, Any] | None,
    schema_graph: dict[str, Any] | None,
    anomaly_column_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    edges = extract_column_edges(schema_graph or {}, dependency_graph or {})
    corr_max_by_col, numeric_matrix = _prefetch_numeric_abs_corr_max(df, schema)
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

        # ---------------- distributional fingerprint ----------------
        sn = distribution_snippet(series) if schema.get(col) == "numeric" else {}
        norm_hint = float(sn.get("normality_score") or 0.5) if sn else 0.45
        skew_abs = abs(float(sn.get("skewness") or 0.0)) if sn else 0.0
        osig = _outlier_signal_for_column(anomaly_column_blocks, str(col), n_rows)

        # ---------------- missing-mechanism ----------------
        mech = detect_missing_mechanism(df, str(col), schema=schema)

        # ---------------- per-method scores ----------------
        mean_s = score_mean(norm_hint, skew_abs) if not is_cat else 0.15
        med_s = score_median(skew_abs, osig) if not is_cat else 0.25
        mode_s = score_mode(series) if is_cat else min(0.35, 1.0 - norm_hint * 0.6)
        corr_m = 0.0 if is_cat else float(corr_max_by_col.get(str(col), 0.0))
        gs = knn_graph_support(str(col), edges)

        # KNN gets boosted when mechanism is MAR; penalised when MNAR
        donor_quality = 0.5
        if not is_cat and numeric_matrix is not None:
            donor_quality = validate_knn_donors(numeric_matrix, str(col))
        knn_s = (
            0.25 if is_cat
            else score_knn(corr_m, gs, donor_quality=donor_quality, mechanism=mech.mechanism)
        )

        scores = {
            "mean": round(mean_s, 4),
            "median": round(med_s, 4),
            "mode": round(mode_s, 4),
            "knn": round(knn_s, 4),
        }
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        key = ranked[0][0] if ranked else "median"
        rec_map = {"mean": "MEAN", "median": "MEDIAN", "mode": "MODE", "knn": "KNN"}
        recommended = rec_map.get(key, key.upper())

        # ---------------- calibrated overall confidence ----------------
        calibrated = default_calibrator.combine(
            "imputation_method",
            {
                "distribution_fit": float(max(scores.values())),
                "correlation_support": float(corr_m if not is_cat else gs),
                "missing_mechanism": mech.confidence if mech.mechanism != "MNAR_SUSPECTED" else 0.3,
                "domain_prior": sem_conf,
                "stability": float(max(0.0, 1.0 - miss_rate)),
            },
            notes=[f"mechanism={mech.mechanism}"],
        )
        overall = round(calibrated.value, 4)
        band = imputation_confidence_band(overall)
        # Also keep legacy blend for backwards-compat
        legacy_overall = imputation_blend(
            distribution_fit=float(max(scores.values())),
            feature_correlation=float(corr_m if not is_cat else gs),
            missing_pattern=float(max(0.0, 1.0 - miss_rate)),
            domain_support=sem_conf,
        )

        reasons = _build_method_reasons(
            is_cat=is_cat, norm_hint=norm_hint, skew_abs=skew_abs, osig=osig,
            miss_rate=miss_rate, mechanism=mech.mechanism,
            knn_donor_quality=donor_quality, scores=scores,
        )

        ranked_payload = [
            {"method": rec_map.get(k, k.upper()), "score": v, "reason": reasons.get(k, "")}
            for k, v in ranked
        ]

        block = {
            "column": str(col),
            "missing_count": miss,
            "missing_rate": round(miss_rate, 4),
            "recommended": recommended,
            "ranked_methods": ranked_payload,
            "mean": scores["mean"],
            "median": scores["median"],
            "mode": scores["mode"],
            "knn": scores["knn"],
            "confidence": overall,
            "confidence_band": band,
            "legacy_confidence": legacy_overall,
            "mechanism": mech.to_dict(),
            "donor_quality": round(donor_quality, 4),
            "explain": {
                "is_categorical": bool(is_cat),
                "normality_hint": norm_hint if sn else None,
                "skewness": sn.get("skewness") if sn else None,
                "outlier_signal": osig,
                "calibration": calibrated.to_dict(),
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
                "ranked_methods": ranked_payload,
                "confidence": overall,
                "confidence_band": band,
                "method_scores": scores,
                "mechanism": mech.mechanism,
            }
        )

    return {
        "imputation_results": per_column,
        "imputation_candidates": flat_candidates,
        "summary": {
            "columns_with_missing": len(per_column),
            "candidate_entries": len(flat_candidates),
            "mechanism_breakdown": _count_mechanisms(per_column),
            "method_breakdown": _count_methods(flat_candidates),
        },
    }


def _count_mechanisms(per_column: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in per_column:
        m = (c.get("mechanism") or {}).get("mechanism", "UNDETERMINED")
        out[m] = out.get(m, 0) + 1
    return out


def _count_methods(flat: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in flat:
        m = str(c.get("recommended_method") or "UNKNOWN")
        out[m] = out.get(m, 0) + 1
    return out
