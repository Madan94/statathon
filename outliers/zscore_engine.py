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
    vals = pd.to_numeric(series, errors="coerce")
    xv = vals.to_numpy(dtype=float)
    finite = np.isfinite(xv)
    if finite.sum() < 3:
        return []

    xv_f = xv[finite]
    mu = float(np.mean(xv_f))
    sd = float(np.std(xv_f, ddof=1))
    if sd <= 1e-12:
        return []

    z_abs = np.abs((xv - mu) / sd)
    hit_indices = np.where(finite & (z_abs >= 1.0))[0]
    if hit_indices.size == 0:
        return []

    rows: list[dict[str, Any]] = []
    thresholds = {"low": 1.0, "medium": 2.0, "high": 3.0, "extreme": 4.0}
    for ix in hit_indices:
        z = float(z_abs[ix])
        sev = _severity_abs_z(z)
        if sev is None:
            continue
        rows.append(
            {
                "row": int(ix),
                "column": column_name,
                "value": float(xv[ix]),
                "method": "Z_SCORE",
                "z_abs": z,
                "score": z,
                "severity": sev,
                "reason": f"|z|={z:.2f} ({sev} severity band)",
                "thresholds": thresholds,
            }
        )
    return rows
