"""Confidence score engine for Z-Score vs IQR method recommendation.

Uses Shapiro-Wilk as the primary normality signal. Does NOT auto-run detection;
returns confidence percentages and human-readable reasons only.
"""
from __future__ import annotations

from typing import Any

from outliers.distribution_engine import distribution_snippet


def _pct(value: float) -> int:
    return int(round(max(0.0, min(100.0, value * 100.0))))


def method_recommendation(series) -> dict[str, Any]:
    sn = distribution_snippet(series)

    shapiro_p = sn.get("shapiro_p")
    skewness = abs(float(sn.get("skewness") or 0.0))
    kurtosis = abs(float(sn.get("kurtosis_excess") or 0.0))
    is_normal = bool(sn.get("is_normal_5pct"))
    heaviness = float(sn.get("heaviness_score") or 0.0)
    sample_size = float(sn.get("n") or 0)

    # --- Shapiro-primary Z-Score confidence ---
    if shapiro_p is not None:
        z_base = float(shapiro_p)
    elif is_normal:
        z_base = 0.75
    else:
        z_base = 0.25

    if skewness < 0.5:
        z_base += 0.10
    elif skewness > 1.0:
        z_base -= 0.20

    if kurtosis < 1.0:
        z_base += 0.05
    elif kurtosis > 3.0:
        z_base -= 0.15

    if sample_size < 30:
        z_base -= 0.10

    z_conf = max(0.05, min(0.95, z_base))

    # --- IQR confidence (inverse of normality + heavy tails) ---
    iqr_base = 0.15
    if shapiro_p is not None and shapiro_p <= 0.05:
        iqr_base += 0.35
    if not is_normal:
        iqr_base += 0.15
    if skewness >= 0.5:
        iqr_base += min(0.25, skewness * 0.15)
    if kurtosis >= 1.0:
        iqr_base += min(0.20, kurtosis * 0.05)
    if heaviness > 0.4:
        iqr_base += heaviness * 0.20

    iqr_conf = max(0.05, min(0.95, iqr_base))

    # Normalize to percentages summing ~100
    total = z_conf + iqr_conf
    z_pct = _pct(z_conf / total)
    iqr_pct = 100 - z_pct

    recommended = "Z_SCORE" if z_pct >= iqr_pct else "IQR"

    reasons: list[str] = []
    if shapiro_p is not None and shapiro_p > 0.05:
        reasons.append("Data passes normality test")
    elif shapiro_p is not None:
        reasons.append("Data fails Shapiro-Wilk normality test")
    if skewness < 0.5:
        reasons.append("Low skewness")
    elif skewness >= 1.0:
        reasons.append("High skewness")
    if kurtosis < 1.0:
        reasons.append("Low kurtosis")
    elif kurtosis >= 3.0:
        reasons.append("Heavy tails (high kurtosis)")
    if heaviness > 0.5:
        reasons.append("Outliers or heavy tails already present")
    if sample_size < 30:
        reasons.append(f"Small sample (n={int(sample_size)})")

    z_pros = [
        "Best for bell-shaped distributions",
        "Interpretable standard-deviation bands",
    ]
    z_cons = [
        "Sensitive to extreme values affecting mean/std",
        "Assumes approximate normality",
    ]
    iqr_pros = [
        "Robust to skew and heavy tails",
        "Not affected by extreme values in spread estimate",
    ]
    iqr_cons = [
        "Less precise for truly normal data",
        "Fence distance harder to interpret than z-scores",
    ]

    return {
        "recommended": recommended,
        "z_score_confidence": z_pct,
        "iqr_confidence": iqr_pct,
        "reason": reasons or ["Default recommendation from confidence margin"],
        "rationale": "; ".join(reasons) if reasons else "Default recommendation from confidence margin",
        "z_score_pros": z_pros,
        "z_score_cons": z_cons,
        "iqr_pros": iqr_pros,
        "iqr_cons": iqr_cons,
        "distribution_hint": {
            "skewness": sn.get("skewness"),
            "kurtosis_excess": sn.get("kurtosis_excess"),
            "shapiro_p": shapiro_p,
            "shapiro_w_statistic": sn.get("shapiro_w_statistic"),
            "is_normal_5pct": is_normal,
            "n": int(sample_size),
        },
    }
