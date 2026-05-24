"""Blend per-method scoring into headline imputation confidence (Phase 3C)."""


def imputation_blend(
    *,
    distribution_fit: float,
    feature_correlation: float,
    missing_pattern: float,
    domain_support: float,
) -> float:
    """Weights from Phase 3C architecture doc."""
    d = max(0.0, min(1.0, distribution_fit))
    f = max(0.0, min(1.0, feature_correlation))
    m = max(0.0, min(1.0, missing_pattern))
    dom = max(0.0, min(1.0, domain_support))
    raw = 0.35 * d + 0.30 * f + 0.20 * m + 0.15 * dom
    return round(max(0.0, min(1.0, raw)), 4)

