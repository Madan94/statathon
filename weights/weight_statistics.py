"""Weighted vs unweighted descriptive statistics."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.json_safe import make_json_safe


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float | None:
    mask = values.notna() & weights.notna() & (weights > 0)
    if mask.sum() < 1:
        return None
    w = weights[mask]
    v = values[mask]
    return float(np.average(v, weights=w))


def _rate(values: pd.Series, weights: pd.Series | None = None) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce")
    mask = numeric.notna()
    if mask.sum() < 1:
        return None
    if weights is None:
        return float(numeric[mask].mean())
    w = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    wm = _weighted_mean(numeric, w)
    return wm


def compare_weighted_unweighted(
    df: pd.DataFrame,
    weight_column: str,
    schema: dict[str, str] | None = None,
    *,
    max_metrics: int = 12,
) -> dict[str, Any]:
    """Build side-by-side metric comparison for numeric and rate-like columns."""
    schema = schema or {}
    if weight_column not in df.columns:
        return {"metrics": [], "weight_column": weight_column}

    weights = pd.to_numeric(df[weight_column], errors="coerce").fillna(0.0).clip(lower=0.0)
    if float(weights.sum()) <= 0:
        return {"metrics": [], "weight_column": weight_column, "error": "weights_sum_zero"}

    metrics: list[dict[str, Any]] = []
    for col in df.columns:
        if col == weight_column:
            continue
        if schema.get(col) not in (None, "numeric") and not pd.api.types.is_numeric_dtype(df[col]):
            if df[col].nunique(dropna=True) > 10:
                continue
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().sum() < 1 and df[col].dtype == object:
            continue
        if series.notna().sum() < 1:
            series = df[col]

        unweighted = _rate(series)
        weighted = _rate(series, weights)
        if unweighted is None and weighted is None:
            continue

        label = str(col).replace("_", " ").title()
        metric_type = "mean"
        if 0 <= (unweighted or 0) <= 1 and 0 <= (weighted or 0) <= 1:
            metric_type = "rate"

        metrics.append(
            {
                "column": str(col),
                "label": label,
                "type": metric_type,
                "unweighted": round(unweighted, 4) if unweighted is not None else None,
                "weighted": round(weighted, 4) if weighted is not None else None,
                "delta": round((weighted or 0) - (unweighted or 0), 4)
                if weighted is not None and unweighted is not None
                else None,
            }
        )
        if len(metrics) >= max_metrics:
            break

    return make_json_safe({"weight_column": weight_column, "metrics": metrics})
