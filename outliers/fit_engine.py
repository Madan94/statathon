"""Choose Z-score vs IQR from distributional shape (Phase 3B)."""

from __future__ import annotations

from outliers.distribution_engine import distribution_snippet


def method_recommendation(series) -> dict:
    sn = distribution_snippet(series)
    norm = float(sn.get("normality_score") or 0.5)
    var_stab = float(sn.get("variance_stability") or 0.8)
    skew = abs(float(sn.get("skewness") or 0))
    iqr = float(sn.get("iqr") or 1e-9)
    mad = float(sn.get("median_abs_dev_approx") or 1e-9)
    robust_ratio = min(1.2, iqr / mad)
    skew_factor = 1.0 / (1.0 + 0.22 * skew)

    z_score_confidence = round(max(0.0, min(1.0, norm * var_stab)), 4)
    iqr_confidence = round(max(0.0, min(1.0, skew_factor * robust_ratio)), 4)
    recommended = "IQR" if iqr_confidence > z_score_confidence + 0.05 else "Z_SCORE"
    return {
        "recommended": recommended,
        "z_score_confidence": z_score_confidence,
        "iqr_confidence": iqr_confidence,
        "distribution_hint": {
            "skewness": sn.get("skewness"),
            "kurtosis_excess": sn.get("kurtosis_excess"),
            "normality_score": norm,
        },
    }
