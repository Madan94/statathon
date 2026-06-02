"""Z-score outlier probes with sample-size-adaptive thresholds.

Severity bands are derived from the column's `z_threshold_extreme` (the
two-sided quantile that produces ~5 expected false positives per column,
Bonferroni-style). Hard fallbacks remain (2/3/4) when the profile is
unavailable for any reason.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from analytics.distribution import profile_column

_LOW_FLOOR = 2.0   # below this, ignore entirely


def _severity_bands(extreme_z: float) -> tuple[float, float, float]:
    """Return (low_floor, medium_floor, extreme_floor) tuned to this column."""
    low = max(_LOW_FLOOR, extreme_z - 1.5)
    medium = max(low + 0.5, extreme_z - 0.5)
    extreme = max(medium + 0.5, extreme_z)
    return low, medium, extreme


def _severity_abs_z(abs_z: float, bands: tuple[float, float, float]) -> str | None:
    low, medium, extreme = bands
    if abs_z < low:
        return None
    if abs_z < medium:
        return "LOW"
    if abs_z < extreme:
        return "MEDIUM"
    return "EXTREME"


def zscore_flags(series: pd.Series) -> tuple[np.ndarray, np.ndarray, tuple[float, float, float]]:
    """Return positional indices where |z| >= low band, plus the bands used."""
    vals = pd.to_numeric(series, errors="coerce")
    finite = vals.notna().to_numpy()
    xv = vals.to_numpy(dtype=float)
    xv_f = xv[finite]
    if xv_f.size < 3:
        return np.array([], dtype=int), np.array([], dtype=float), (2.0, 3.0, 4.0)

    profile = profile_column(series)
    extreme_z = float(profile.z_threshold_extreme or 3.5)
    bands = _severity_bands(extreme_z)

    mu = float(np.nanmean(xv_f))
    sd = float(np.nanstd(xv_f, ddof=1))
    sd = sd if sd > 1e-12 else float("nan")
    if np.isnan(sd):
        return np.array([], dtype=int), np.array([], dtype=float), bands

    z = np.abs((xv_f - mu) / sd)
    pos = np.where(finite)[0]
    keep = np.where(z >= bands[0])[0]
    return pos[keep].astype(int), z[keep], bands


def zscore_records(series: pd.Series, column_name: str) -> list[dict[str, Any]]:
    indices, zs, bands = zscore_flags(series)
    rows: list[dict[str, Any]] = []
    raw = pd.to_numeric(series, errors="coerce").reset_index(drop=True)
    for ix, tz in zip(indices.tolist(), zs.tolist()):
        sev = _severity_abs_z(float(tz), bands)
        if sev is None:
            continue
        val = raw.iloc[int(ix)]
        rows.append(
            {
                "row": int(ix),
                "column": column_name,
                "value": (
                    None if pd.isna(val)
                    else float(val) if isinstance(val, (int, float, np.floating))
                    else val
                ),
                "method": "Z_SCORE",
                "z_abs": float(tz),
                "severity": sev,
                "thresholds": {"low": bands[0], "medium": bands[1], "extreme": bands[2]},
            }
        )
    return rows
