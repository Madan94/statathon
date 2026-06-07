"""Distribution diagnostics for anomaly method selection.

Backed by the shared `analytics.distribution.DistributionProfile`. The
returned dict keeps backward-compatible field names so existing callers
(fit_engine, downstream phase3) work unchanged, but is now enriched with:

  * anderson_stat / anderson_critical_5pct  (heavy-tail sensitivity)
  * robust_skew                              (Bowley quartile skew)
  * is_multimodal / dip_p                    (Hartigan)
  * z_threshold_extreme                       (sample-size-adapted)
  * iqr_multiplier_recommended                (skew/kurtosis-adapted)
  * heaviness_score                           (0..1 — supports robust methods)
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from analytics.distribution import profile_column


def distribution_snippet(series: pd.Series,
                         max_samples: int = 4999,
                         rng_seed: int = 42) -> dict[str, Any]:
    """Return distributional fingerprint of a column.

    Backward-compatible with the legacy snippet keys
    (`skewness`, `kurtosis_excess`, `normality_score`, `variance_stability`,
    `median`, `iqr`, `median_abs_dev_approx`, `n`) and adds new fields.
    """
    profile = profile_column(series)

    # Map shared profile to legacy snippet shape
    snippet: dict[str, Any] = {
        "n": float(profile.sample_size_used or profile.count or 0),
        "skewness": float(profile.skew or 0.0),
        "kurtosis_excess": float(profile.kurtosis or 0.0),
        "median": float(profile.median or 0.0),
        "iqr": float(profile.iqr or 1e-12),
        "median_abs_dev_approx": float(profile.mad or 1e-12),

        # Normality score in [0,1] (higher = more normal). Blend Shapiro/Anderson/Dagostino.
        "normality_score": _compose_normality_score(profile),
        "variance_stability": _variance_stability(profile),

        # Enriched fields
        "robust_skew": profile.robust_skew,
        "shapiro_p": profile.shapiro_p,
        "shapiro_w_statistic": profile.shapiro_stat,
        "dagostino_p": profile.dagostino_p,
        "anderson_stat": profile.anderson_stat,
        "anderson_critical_5pct": profile.anderson_critical_5pct,
        "is_normal_5pct": profile.is_normal_5pct,
        "is_multimodal": profile.is_multimodal,
        "dip_p": profile.dip_p,
        "z_threshold_extreme": profile.z_threshold_extreme,
        "iqr_multiplier_recommended": profile.iqr_multiplier_recommended,
        "heaviness_score": profile.heaviness_score,
        "cv": profile.cv,
    }

    # Defensive: legacy callers expect non-None for these.
    snippet["iqr"] = float(snippet["iqr"] or 1e-12)
    snippet["median_abs_dev_approx"] = float(snippet["median_abs_dev_approx"] or 1e-12)
    return snippet


def _compose_normality_score(profile) -> float:
    """0..1 blended normality score across the three tests."""
    scores: list[float] = []
    if profile.shapiro_p is not None:
        # Shapiro: high p => normal
        scores.append(min(1.0, max(0.0, profile.shapiro_p * 2.0)))
    if profile.dagostino_p is not None:
        scores.append(min(1.0, max(0.0, profile.dagostino_p * 2.0)))
    if profile.anderson_stat is not None and profile.anderson_critical_5pct:
        # Anderson: stat below critical => normal
        ratio = profile.anderson_stat / max(profile.anderson_critical_5pct, 1e-12)
        scores.append(max(0.0, min(1.0, 1.0 - (ratio - 1.0))))
    if not scores:
        return 0.55
    score = sum(scores) / len(scores)
    # Penalty for high skew or multimodality
    if profile.skew is not None and abs(profile.skew) >= 2.0:
        score = min(score, 0.35)
    if profile.is_multimodal:
        score = min(score, 0.30)
    return float(max(0.05, min(1.0, score)))


def _variance_stability(profile) -> float:
    cv = profile.cv
    if cv is None or cv != cv:  # None or NaN
        return 1.0
    return float(1.0 / (1.0 + abs(cv)))
