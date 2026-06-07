"""Z-score outlier detection with four severity bands per Phase 3 spec.

Low:      1 <= |z| < 2
Medium:   2 <= |z| < 3
High:     3 <= |z| < 4
Extreme:  |z| >= 4
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _severity_abs_z(abs_z: float) -> str | None:
    if abs_z < 1.0:
        return None
    if abs_z < 2.0:
        return "LOW"
    if abs_z < 3.0:
        return "MEDIUM"
    if abs_z < 4.0:
        return "HIGH"
    return "EXTREME"


def zscore_records(series: pd.Series, column_name: str) -> list[dict[str, Any]]:
    vals = pd.to_numeric(series, errors="coerce").reset_index(drop=True)
    finite = vals.notna()
    xv = vals.to_numpy(dtype=float)
    xv_f = xv[finite.to_numpy()]
    if xv_f.size < 3:
        return []

    mu = float(np.nanmean(xv_f))
    sd = float(np.nanstd(xv_f, ddof=1))
    if sd <= 1e-12:
        return []

    rows: list[dict[str, Any]] = []
    pos = np.where(finite.to_numpy())[0]
    for ix in pos:
        v = xv[ix]
        if np.isnan(v):
            continue
        z_abs = abs((float(v) - mu) / sd)
        sev = _severity_abs_z(z_abs)
        if sev is None:
            continue
        rows.append(
            {
                "row": int(ix),
                "column": column_name,
                "value": float(v),
                "method": "Z_SCORE",
                "z_abs": float(z_abs),
                "score": float(z_abs),
                "severity": sev,
                "reason": f"|z|={z_abs:.2f} ({sev} severity band)",
                "thresholds": {"low": 1.0, "medium": 2.0, "high": 3.0, "extreme": 4.0},
            }
        )
    return rows
