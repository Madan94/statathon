"""Mean imputation fitness score (Phase 3C; scoring only — no mutate)."""


def score_mean(normality_hint: float, skew_abs: float) -> float:
    """Higher when symmetric / near-normal tails."""
    n = max(0.0, min(1.0, normality_hint))
    skew_pen = max(0.0, min(1.0, 1.0 - 0.18 * skew_abs))
    raw = max(0.0, min(1.0, n * skew_pen))
    return round(raw, 4)
