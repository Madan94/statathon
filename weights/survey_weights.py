"""Phase 7 — survey / sampling weight application (descriptive weighted stats)."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from core.json_safe import make_json_safe

_WEIGHT_NAME_RE = re.compile(
    r"(^weight$|^weights$|^wt$|^wgt$|survey[_\s]?weight|sample[_\s]?weight|final[_\s]?wt)",
    re.I,
)


def detect_weight_column(df: pd.DataFrame, explicit: str | None = None) -> str | None:
    if explicit and explicit in df.columns:
        return explicit
    for col in df.columns:
        if _WEIGHT_NAME_RE.search(str(col).replace(" ", "_")):
            s = pd.to_numeric(df[col], errors="coerce")
            if s.notna().sum() >= max(2, min(3, len(df))):
                return str(col)
    return None


def compute_survey_weight_profile(
    df: pd.DataFrame,
    schema: dict[str, str],
    *,
    weight_column: str | None = None,
) -> dict[str, Any]:
    """
    Compute weighted column means for numeric fields using a survey weight column.
    Does not mutate the input DataFrame.
    """
    col = detect_weight_column(df, weight_column)
    if not col:
        return {
            "applied": False,
            "reason": "no_weight_column_detected",
            "weight_column": None,
            "weighted_numeric_means": {},
            "summary": {},
        }

    w = pd.to_numeric(df[col], errors="coerce").fillna(0.0).clip(lower=0.0)
    if float(w.sum()) <= 0:
        return {
            "applied": False,
            "reason": "weights_sum_zero",
            "weight_column": col,
            "weighted_numeric_means": {},
            "summary": {},
        }

    w_norm = w / w.sum()
    weighted_means: dict[str, float] = {}
    for c in df.columns:
        if c == col:
            continue
        if schema.get(c) != "numeric" and not pd.api.types.is_numeric_dtype(df[c]):
            continue
        vals = pd.to_numeric(df[c], errors="coerce")
        mask = vals.notna() & w_norm.notna()
        if mask.sum() < 1:
            continue
        wm = float(np.average(vals[mask], weights=w_norm[mask]))
        weighted_means[str(c)] = round(wm, 6)

    return make_json_safe(
        {
            "applied": True,
            "weight_column": col,
            "weight_sum": float(w.sum()),
            "effective_sample_size": float((w.sum() ** 2) / (np.square(w).sum() + 1e-12)),
            "weighted_numeric_means": weighted_means,
            "summary": {
                "numeric_columns_weighted": len(weighted_means),
                "n_rows": len(df),
            },
        }
    )
