"""Z-score outlier probes (Phase 3B; no dataframe mutation)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _severity_abs_z(abs_z: float) -> str | None:
    if abs_z < 2.0:
        return None
    if abs_z < 3.0:
        return "LOW"
    if abs_z < 4.0:
        return "MEDIUM"
    return "EXTREME"


def zscore_flags(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Return positional indices where |z| >= 2 for finite numeric values."""
    vals = pd.to_numeric(series, errors="coerce")
    finite = vals.notna().to_numpy()
    xv = vals.to_numpy(dtype=float)
    xv_f = xv[finite]
    if xv_f.size < 3:
        return np.array([], dtype=int), np.array([], dtype=float)
    mu = float(np.nanmean(xv_f))
    sd = float(np.nanstd(xv_f, ddof=1))
    sd = sd if sd > 1e-12 else float("nan")
    if np.isnan(sd):
        return np.array([], dtype=int), np.array([], dtype=float)
    z = np.abs((xv_f - mu) / sd)
    pos = np.where(finite)[0]
    good = np.where(z >= 2.0)[0]
    return pos[good].astype(int), z[good]


def zscore_records(series: pd.Series, column_name: str) -> list[dict]:
    indices, zs = zscore_flags(series)
    rows: list[dict] = []
    raw = pd.to_numeric(series, errors="coerce").reset_index(drop=True)
    for ix, tz in zip(indices.tolist(), zs.tolist()):
        sev = _severity_abs_z(float(tz))
        if sev is None:
            continue
        val = raw.iloc[int(ix)]
        rows.append(
            {
                "row": int(ix),
                "column": column_name,
                "value": None if pd.isna(val) else float(val) if isinstance(val, (int, float, np.floating)) else val,
                "method": "Z_SCORE",
                "z_abs": float(tz),
                "severity": sev,
            }
        )
    return rows
