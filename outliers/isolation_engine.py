"""Isolation Forest row flags for Phase 3B (numeric columns)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.outlier_engine import isolation_outliers


def isolation_records(series: pd.Series, column_name: str, max_flags: int = 50) -> list[dict]:
    """Return anomaly candidate dicts for isolation-forest outliers on one column."""
    vals = pd.to_numeric(series, errors="coerce")
    finite_mask = vals.notna()
    if finite_mask.sum() < 8:
        return []

    xv = vals[finite_mask].to_numpy(dtype=float).reshape(-1, 1)
    pos = np.where(finite_mask.to_numpy())[0]
    out_idx = isolation_outliers(xv)
    rows: list[dict] = []
    for local_i in out_idx[:max_flags]:
        if local_i >= len(pos):
            continue
        row_ix = int(pos[local_i])
        val = vals.iloc[row_ix]
        rows.append(
            {
                "row": row_ix,
                "column": column_name,
                "value": None if pd.isna(val) else float(val),
                "method": "ISOLATION_FOREST",
                "severity": "MEDIUM",
                "z_abs": None,
                "iqr_excess": None,
            }
        )
    return rows
