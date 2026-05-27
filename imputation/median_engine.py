"""Median imputation fitness scoring (Phase 3C)."""


def score_median(skew_abs: float, outlier_signal: float) -> float:
    skew = abs(float(skew_abs))
    outlier = max(0.0, min(1.0, float(outlier_signal)))
    skew_score = min(1.0, skew / (skew + 12.0))
    raw = 0.55 * skew_score + 0.45 * outlier
    return round(max(0.0, min(1.0, raw)), 4)
