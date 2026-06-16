"""Validate a candidate weight column."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MISSING_THRESHOLD = 0.10
EXTREME_INFLATION_RATIO = 1000.0


def validate_weight_column(df: pd.DataFrame, column: str) -> dict[str, Any]:
    """Run weight quality checks and return validation payload."""
    if column not in df.columns:
        return {
            "column": column,
            "quality_score": 0.0,
            "coverage": 0.0,
            "valid": False,
            "checks": {"present": False},
        }

    series = pd.to_numeric(df[column], errors="coerce")
    total = len(series)
    valid = series.dropna()
    coverage = float(len(valid) / total) if total else 0.0
    missing_pct = 1.0 - coverage

    positive = valid[valid > 0]
    negative_count = int((valid < 0).sum())
    zero_count = int((valid == 0).sum())

    checks: dict[str, Any] = {
        "positive_values": len(positive) > 0,
        "no_negative_weights": negative_count == 0,
        "missing_below_threshold": missing_pct <= MISSING_THRESHOLD,
        "reasonable_variance": False,
        "no_extreme_inflation": True,
    }

    variance_score = 0.0
    if len(positive) >= 2:
        cv = float(positive.std() / (positive.mean() + 1e-12))
        checks["reasonable_variance"] = cv >= 0.01
        variance_score = min(1.0, cv * 2.0)
        max_w = float(positive.max())
        min_w = float(positive.min())
        if min_w > 0 and max_w / min_w > EXTREME_INFLATION_RATIO:
            checks["no_extreme_inflation"] = False

    rule_scores = [
        1.0 if checks["positive_values"] else 0.0,
        1.0 if checks["no_negative_weights"] else 0.0,
        1.0 if checks["missing_below_threshold"] else max(0.0, 1.0 - missing_pct),
        min(1.0, variance_score) if len(positive) >= 2 else 0.5,
        1.0 if checks["no_extreme_inflation"] else 0.0,
    ]
    quality_score = round(float(np.mean(rule_scores)), 4)
    valid_flag = all(
        [
            checks["positive_values"],
            checks["no_negative_weights"],
            checks["missing_below_threshold"],
            checks["no_extreme_inflation"],
        ]
    )

    return {
        "column": column,
        "quality_score": quality_score,
        "coverage": round(coverage, 4),
        "missing_pct": round(missing_pct, 4),
        "variance": round(float(valid.var()), 6) if len(valid) >= 2 else 0.0,
        "valid": valid_flag,
        "checks": checks,
        "negative_count": negative_count,
        "zero_count": zero_count,
    }
