"""Distribution diagnostics for anomaly method selection (Phase 3B)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def distribution_snippet(series: pd.Series, max_samples: int = 4999, rng_seed: int = 42) -> dict[str, float]:
    """Skew/kurtosis + normality heuristics (subsample large columns)."""
    rng = np.random.default_rng(seed=rng_seed)
    vals = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]
    n = int(vals.size)
    out: dict[str, float] = {
        "n": float(n),
        "skewness": 0.0,
        "kurtosis_excess": 0.0,
        "normality_score": 0.55,
        "variance_stability": 1.0,
        "median": float(np.median(vals)) if n else 0.0,
        "iqr": 0.0,
        "median_abs_dev_approx": 0.0,
    }
    if n < 8:
        return out

    out["skewness"] = float(stats.skew(vals))
    out["kurtosis_excess"] = float(stats.kurtosis(vals, fisher=True))
    q25, q75 = np.percentile(vals, [25.0, 75.0])
    iqr = float(q75 - q25)
    out["iqr"] = max(iqr, 1e-12)
    out["median"] = float(np.median(vals))
    mad = float(np.median(np.abs(vals - out["median"])))
    out["median_abs_dev_approx"] = max(mad, 1e-12)

    mu = float(np.mean(vals))
    sigma = float(np.std(vals, ddof=1 if n >= 2 else 0))
    denom = abs(mu) + max(sigma, 1e-12)
    cv = sigma / denom if denom > 1e-12 else 1.0
    out["variance_stability"] = float(1.0 / (1.0 + cv))

    if n <= max_samples:
        sample = vals
    else:
        sample = rng.choice(vals, size=max_samples, replace=False)

    shapiro_ok = False
    if sample.size <= 5000 and np.ptp(sample) > 1e-12:
        try:
            _, p_shapiro = stats.shapiro(sample.astype(float))
            shapiro_ok = True
            out["normality_score"] = float(min(1.0, max(0.05, float(p_shapiro) * 2.5)))
        except ValueError:
            shapiro_ok = False

    if not shapiro_ok and sample.size >= 8:
        try:
            nt_stat = stats.normaltest(sample.astype(float))[1]
            p_nt = float(nt_stat)
            if np.isfinite(p_nt):
                out["normality_score"] = float(
                    min(float(out["normality_score"]), min(1.0, max(0.08, p_nt * 3.5)))
                )
        except ValueError:
            pass

    if abs(float(out["skewness"])) >= 2.5:
        out["normality_score"] = float(min(out["normality_score"], 0.42))

    return out
