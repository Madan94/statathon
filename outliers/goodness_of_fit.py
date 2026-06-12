"""Step 1 — Goodness-of-Fit analysis for numeric columns before outlier detection."""
from __future__ import annotations

from typing import Any

import pandas as pd

from analytics.distribution import profile_column
from outliers.column_types import is_numeric_column


def analyze_column_goodness_of_fit(series: pd.Series, column_name: str) -> dict[str, Any]:
    """Compute distributional statistics and normality tests for one column."""
    profile = profile_column(series)
    return {
        "column": column_name,
        "mean": profile.mean,
        "median": profile.median,
        "standard_deviation": profile.std,
        "skewness": profile.skew,
        "kurtosis": profile.kurtosis,
        "shapiro_w_statistic": profile.shapiro_stat,
        "p_value": profile.shapiro_p,
        "sample_size": profile.count,
        "is_normal_5pct": profile.is_normal_5pct,
    }


def build_goodness_of_fit_bundle(
    df: pd.DataFrame,
    schema: dict[str, str],
) -> list[dict[str, Any]]:
    """Run goodness-of-fit for every numeric column."""
    results: list[dict[str, Any]] = []
    for col in df.columns:
        if not is_numeric_column(schema.get(col), df[col]):
            continue
        results.append(analyze_column_goodness_of_fit(df[col], str(col)))
    return results
