"""IQR outlier probes — distance beyond 1.5×IQR fences (Phase 3B; no mutation)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _severity_iqr_excess(excess_in_iqr_units: float) -> str | None:
    """excess beyond inner 1.5×IQR fence, expressed in IQR multiples."""
    if excess_in_iqr_units <= 0:
        return None
    if excess_in_iqr_units <= 0.5:
        return "LOW"
    if excess_in_iqr_units <= 1.5:
        return "MEDIUM"
    return "EXTREME"


def iqr_records(series: pd.Series, column_name: str) -> list[dict]:
    s = pd.to_numeric(series, errors="coerce").reset_index(drop=True)
    valid = s.dropna()
    if valid.size < 4:
        return []
    q1, q3 = float(valid.quantile(0.25)), float(valid.quantile(0.75))
    iqr = q3 - q1
    eiqr = max(iqr, 1e-12)
    lo = q1 - 1.5 * eiqr
    hi = q3 + 1.5 * eiqr
    rows: list[dict] = []
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
        sev = _severity_iqr_excess(excess)
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
            }
        )
    return rows
