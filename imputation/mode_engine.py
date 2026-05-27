"""Mode imputation fitness for categoricals (Phase 3C)."""

import pandas as pd


def score_mode(series: pd.Series) -> float:
    nn = int(series.dropna().size)
    if nn == 0:
        return 0.0
    u = int(series.dropna().nunique())
    if u <= 0:
        return 0.0
    distinct_ratio = u / max(nn, 1)
    if pd.api.types.is_numeric_dtype(series) and distinct_ratio > 0.35:
        return round(max(0.0, 1.0 - distinct_ratio * 0.9), 4)
    return round(max(0.0, min(1.0, 1.0 - (distinct_ratio - 0.05) * 1.2)), 4)