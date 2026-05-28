"""IQR outlier probes with skew/kurtosis-adapted fence multiplier.

Tukey's classic 1.5×IQR fence assumes near-normal data. For heavy-tailed
or asymmetric columns the shared profiler recommends 2.0× or 2.5× to keep
false-positive rates sane. We honour that recommendation when available
and fall back to 1.5× otherwise.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from analytics.distribution import profile_column


def _severity_iqr_excess(excess_in_iqr_units: float,
                         bands: tuple[float, float]) -> str | None:
    """excess beyond the inner fence, expressed in IQR multiples."""
    medium_floor, extreme_floor = bands
    if excess_in_iqr_units <= 0:
        return None
    if excess_in_iqr_units <= medium_floor:
        return "LOW"
    if excess_in_iqr_units <= extreme_floor:
        return "MEDIUM"
    return "EXTREME"


def iqr_records(series: pd.Series, column_name: str) -> list[dict[str, Any]]:
    s = pd.to_numeric(series, errors="coerce").reset_index(drop=True)
    valid = s.dropna()
    if valid.size < 4:
        return []

    profile = profile_column(series)
    multiplier = float(profile.iqr_multiplier_recommended or 1.5)
    # Severity bands derived from the chosen multiplier
    medium_floor = max(0.3, multiplier - 1.0)   # how far past fence = MEDIUM
    extreme_floor = max(medium_floor + 0.5, multiplier - 0.0)
    bands = (medium_floor, extreme_floor)

    q1, q3 = float(valid.quantile(0.25)), float(valid.quantile(0.75))
    iqr = q3 - q1
    eiqr = max(iqr, 1e-12)
    lo = q1 - multiplier * eiqr
    hi = q3 + multiplier * eiqr
    rows: list[dict[str, Any]] = []
    for pos in range(len(s)):
        v = s.iloc[pos]
        if pd.isna(v):
            continue
        vf = float(v)
        if vf < lo:
            excess = (lo - vf) / eiqr
        elif vf > hi:
            excess = (vf - hi) / eiqr
        else:
            continue
        sev = _severity_iqr_excess(excess, bands)
        if sev is None:
            continue
        rows.append(
            {
                "row": int(pos),
                "column": column_name,
                "value": vf,
                "method": "IQR",
                "iqr_excess": float(excess),
                "severity": sev,
                "fence_multiplier": multiplier,
                "q1": q1,
                "q3": q3,
                "iqr": float(iqr),
            }
        )
    return rows
