"""Bayesian-style anomaly method selection.

Decides per-column whether **Z-score**, **IQR**, or both are appropriate,
using all distributional evidence from the shared profile (normality
tests, robust skew, kurtosis, multimodality, sample size).

The output schema is backward-compatible with the legacy snippet:
    {
      "recommended":         "Z_SCORE" | "IQR" | "ROBUST_ENSEMBLE",
      "z_score_confidence":  float 0..1,
      "iqr_confidence":      float 0..1,
      "distribution_hint":   {skewness, kurtosis_excess, normality_score, ...},
    }

Adds:
    "rationale":     human-readable explanation (string)
    "signals":       dict of every signal used (for audit)
    "score_breakdown": calibrated confidence per method
"""
from __future__ import annotations

from typing import Any

from analytics import default_calibrator
from outliers.distribution_engine import distribution_snippet


def method_recommendation(series) -> dict[str, Any]:
    sn = distribution_snippet(series)

    # ---------------- signals supporting Z-SCORE (normality) ----------------
    normality = float(sn.get("normality_score") or 0.55)
    var_stab = float(sn.get("variance_stability") or 0.8)
    sample_size = float(sn.get("n") or 0)
    multimodal_penalty = 0.5 if sn.get("is_multimodal") else 1.0
    sample_adequacy = min(1.0, sample_size / 30.0)

    z_signals = {
        "normality": normality * multimodal_penalty,
        "variance_stability": var_stab,
        "sample_size_adequacy": sample_adequacy,
        # robustness_need is the *opposite* signal for Z-score
        "robustness_need": max(0.0, 1.0 - float(sn.get("heaviness_score") or 0.0)),
    }
    z_calibrated = default_calibrator.combine("anomaly_method", z_signals)

    # ---------------- signals supporting IQR (robust) ----------------
    heaviness = float(sn.get("heaviness_score") or 0.0)
    robust_skew = abs(float(sn.get("robust_skew") or 0.0))
    iqr = float(sn.get("iqr") or 1e-9)
    mad = float(sn.get("median_abs_dev_approx") or 1e-9)
    robust_ratio = min(1.5, iqr / max(mad, 1e-12)) / 1.5  # normalised 0..1

    iqr_signals = {
        # IQR wants the *inverse* of normality
        "normality": max(0.0, 1.0 - normality),
        "robustness_need": min(1.0, heaviness + 0.6 * robust_skew),
        "variance_stability": min(1.0, robust_ratio),
        "sample_size_adequacy": min(1.0, sample_size / 20.0),
    }
    iqr_calibrated = default_calibrator.combine("anomaly_method", iqr_signals)

    z_conf = round(z_calibrated.value, 4)
    iqr_conf = round(iqr_calibrated.value, 4)

    # ---------------- Recommendation decision ----------------
    multimodal = bool(sn.get("is_multimodal"))
    is_normal = bool(sn.get("is_normal_5pct"))
    rationale_bits: list[str] = []

    if multimodal:
        rationale_bits.append("multimodality detected -> robust ensemble recommended")
    if is_normal:
        rationale_bits.append("data approximately normal at 5%")
    if heaviness > 0.5:
        rationale_bits.append(f"heavy-tailed (heaviness={heaviness:.2f})")
    if robust_skew > 0.3:
        rationale_bits.append(f"asymmetric (robust_skew={robust_skew:.2f})")
    if sample_size < 30:
        rationale_bits.append(f"small sample (n={int(sample_size)})")

    if multimodal or heaviness > 0.6:
        recommended = "ROBUST_ENSEMBLE"
    elif iqr_conf > z_conf + 0.05:
        recommended = "IQR"
    else:
        recommended = "Z_SCORE"

    return {
        "recommended": recommended,
        "z_score_confidence": z_conf,
        "iqr_confidence": iqr_conf,
        "distribution_hint": {
            "skewness": sn.get("skewness"),
            "kurtosis_excess": sn.get("kurtosis_excess"),
            "normality_score": normality,
            "robust_skew": sn.get("robust_skew"),
            "is_normal_5pct": sn.get("is_normal_5pct"),
            "is_multimodal": sn.get("is_multimodal"),
            "heaviness_score": heaviness,
            "z_threshold_extreme": sn.get("z_threshold_extreme"),
            "iqr_multiplier_recommended": sn.get("iqr_multiplier_recommended"),
            "n": int(sample_size),
        },
        "rationale": "; ".join(rationale_bits) or "default selection by confidence margin",
        "signals": {
            "z_score": z_signals,
            "iqr": iqr_signals,
        },
        "score_breakdown": {
            "z_score": z_calibrated.to_dict(),
            "iqr": iqr_calibrated.to_dict(),
        },
    }
