"""IQR outlier detection with percentage-beyond-boundary severity.

LOW:      0–50% beyond boundary
MEDIUM:   50–100% beyond boundary
EXTREME:  100%+ beyond boundary
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _severity_pct_beyond(pct: float) -> str | None:
    if pct <= 0:
        return None
    if pct <= 0.50:
        return "LOW"
    if pct <= 1.0:
        return "MEDIUM"
    return "EXTREME"


def iqr_records(series: pd.Series, column_name: str, multiplier: float = 1.5) -> list[dict[str, Any]]:
    s = pd.to_numeric(series, errors="coerce").reset_index(drop=True)
    valid = s.dropna()
    if valid.size < 4:
        return []

    q1, q3 = float(valid.quantile(0.25)), float(valid.quantile(0.75))
    iqr = q3 - q1
    eiqr = max(iqr, 1e-12)
    lo = q1 - multiplier * eiqr
    hi = q3 + multiplier * eiqr
    fence_width = multiplier * eiqr

    rows: list[dict[str, Any]] = []
    for pos in range(len(s)):
        v = s.iloc[pos]
        if pd.isna(v):
            continue
        vf = float(v)
        if lo <= vf <= hi:
            continue
        if vf < lo:
            distance = lo - vf
            boundary = lo
        else:
            distance = vf - hi
            boundary = hi
        pct_beyond = distance / max(fence_width, 1e-12)
        sev = _severity_pct_beyond(pct_beyond)
        if sev is None:
            continue
        rows.append(
            {
                "row": int(pos),
                "column": column_name,
                "value": vf,
                "method": "IQR",
                "iqr_excess": float(pct_beyond),
                "severity": sev,
                "reason": f"{pct_beyond * 100:.0f}% beyond IQR fence ({sev})",
                "fence_multiplier": multiplier,
                "q1": q1,
                "q3": q3,
                "iqr": float(iqr),
                "boundary": boundary,
            }
        )
    return rows
