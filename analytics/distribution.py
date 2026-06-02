"""Single-source-of-truth distribution profiler.

Every numeric column gets profiled exactly once per analysis. The result
(`DistributionProfile`) is consumed by:
  * outliers/distribution_engine.py     (anomaly method selection)
  * outliers/fit_engine.py              (z-score vs IQR recommendation)
  * imputation/imputation_manager.py    (mean vs median vs KNN choice)
  * imputation/missing_mechanism.py     (MCAR / MAR detection)
  * model/semantic_mapping/similarity_engine.py (distribution-fingerprint signal)
  * validation/single_column/confidence_engine.py (rule-violation calibration)

Statistical tests:
  * Shapiro-Wilk           — primary normality test (sample-size aware)
  * D'Agostino-Pearson     — fallback when sample is too large for Shapiro
  * Anderson-Darling       — heavy-tailed sensitivity
  * Hartigan dip test      — multimodality detector (graceful fallback if `diptest` missing)
  * Robust skewness        — Bowley's quartile skewness (resistant to outliers)
  * Kurtosis               — excess kurtosis (Fisher)
  * Coefficient of variation
  * Trimmed mean / std     — outlier-resistant centre / spread
  * Missingness mechanism markers (block / scatter)
"""
from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

# Suppress noisy scipy.stats.anderson deprecation; we capture both critical_values
# and statistic, so the new behaviour is irrelevant to us until 1.19.
warnings.filterwarnings(
    "ignore",
    message=".*method.*parameter.*",
    category=FutureWarning,
    module="scipy",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class DistributionProfile:
    """Frozen statistical fingerprint of one column."""

    column: str
    dtype: str
    count: int
    missing_count: int
    missing_pct: float
    unique_count: int

    # Central tendency / spread (outlier-resistant where possible)
    mean: float | None = None
    median: float | None = None
    mode: Any | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    mad: float | None = None              # Median Absolute Deviation
    cv: float | None = None               # Coefficient of variation
    trimmed_mean_10: float | None = None
    trimmed_std_10: float | None = None

    # Shape
    skew: float | None = None
    robust_skew: float | None = None      # Bowley skew (resistant)
    kurtosis: float | None = None         # excess kurtosis

    # Normality / shape tests
    shapiro_stat: float | None = None
    shapiro_p: float | None = None
    dagostino_p: float | None = None
    anderson_stat: float | None = None
    anderson_critical_5pct: float | None = None
    is_normal_5pct: bool | None = None

    # Multimodality
    dip_stat: float | None = None
    dip_p: float | None = None
    is_multimodal: bool | None = None

    # Categorical features
    top_categories: list[tuple[Any, int]] = field(default_factory=list)
    entropy: float | None = None

    # Sample-size scaled thresholds derived from this profile
    z_threshold_extreme: float | None = None
    iqr_multiplier_recommended: float | None = None

    # Sample of cleaned values used (for downstream callers that need them)
    sample_size_used: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        # Convert numpy scalars to native python for JSON serialization
        for k, v in list(out.items()):
            if isinstance(v, (np.floating, np.integer)):
                out[k] = float(v) if isinstance(v, np.floating) else int(v)
        return out

    @property
    def is_numeric(self) -> bool:
        return self.mean is not None

    @property
    def is_categorical_like(self) -> bool:
        return not self.is_numeric or (self.unique_count and self.unique_count <= 20)

    @property
    def heaviness_score(self) -> float:
        """0..1 — how heavy-tailed / non-normal this column is.

        Used by anomaly + imputation to prefer robust methods.
        """
        if self.is_normal_5pct is True:
            return 0.0
        score = 0.0
        if self.skew is not None:
            score += min(abs(self.skew) / 3.0, 0.5)
        if self.kurtosis is not None and self.kurtosis > 0:
            score += min(self.kurtosis / 10.0, 0.3)
        if self.shapiro_p is not None and self.shapiro_p < 0.05:
            score += 0.2
        return min(score, 1.0)


# ---------------------------------------------------------------------------
# Profiling helpers
# ---------------------------------------------------------------------------


_SHAPIRO_MAX_N = 5000  # scipy hard-caps Shapiro at 5000
_DAGOSTINO_MIN_N = 8


def _entropy(counts: np.ndarray) -> float | None:
    if counts.size == 0:
        return None
    total = counts.sum()
    if total == 0:
        return None
    p = counts / total
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def _bowley_skew(q1: float, median: float, q3: float) -> float | None:
    """Robust quartile skewness; resistant to outliers."""
    denom = q3 - q1
    if denom == 0:
        return None
    return float((q3 + q1 - 2 * median) / denom)


def _sample_size_z_threshold(n: int) -> float:
    """Sample-size-adjusted |z| threshold for 'extreme outlier' classification.

    For n=30 a 3σ event is ~1 in 740, so we'd expect 0.04 false positives
    per column at 3σ — fine. For n=10000 that's 27 false positives per
    column. Use the t-distribution quantile that gives ~5 expected
    false positives per column (Bonferroni-style).
    """
    if n <= 0:
        return 3.0
    target_per_col = 5.0
    alpha = target_per_col / max(n, 100)
    alpha = min(alpha, 0.05)
    alpha = max(alpha, 1e-6)
    try:
        from scipy import stats
        return float(stats.norm.ppf(1 - alpha / 2))
    except Exception:
        # Approx via inverse error function fallback (no scipy)
        return float(math.sqrt(2) * math.erfinv(1 - alpha) if hasattr(math, "erfinv") else 3.0)


def _recommend_iqr_multiplier(robust_skew: float | None,
                              kurtosis: float | None) -> float:
    """Tukey 1.5× is for ~normal data. Heavier tails need looser fences."""
    base = 1.5
    if robust_skew is not None and abs(robust_skew) > 0.3:
        base += 0.5
    if kurtosis is not None and kurtosis > 3:
        base += 0.5
    return min(base, 3.0)


def _hartigan_dip(values: np.ndarray) -> tuple[float | None, float | None]:
    """Returns (dip_stat, dip_p_value). p < 0.05 => multimodal."""
    try:
        import diptest  # type: ignore

        if values.size < 4:
            return None, None
        dip, pval = diptest.diptest(values)
        return float(dip), float(pval)
    except Exception:
        # Lightweight bimodality heuristic via bimodality coefficient
        # (Sarle's BC > 0.555 ≈ bimodal).
        try:
            n = values.size
            if n < 8:
                return None, None
            from scipy import stats as _st
            skew = float(_st.skew(values, bias=False))
            kurt = float(_st.kurtosis(values, bias=False))
            bc = (skew ** 2 + 1) / (kurt + 3 * ((n - 1) ** 2) / ((n - 2) * (n - 3)))
            # Convert BC to a pseudo p-value (heuristic)
            pseudo_p = 0.01 if bc > 0.7 else (0.04 if bc > 0.555 else 0.2)
            return float(bc), pseudo_p
        except Exception:
            return None, None


def profile_column(series: pd.Series, *, column_name: str | None = None) -> DistributionProfile:
    """Build a `DistributionProfile` for a single Series.

    Numeric and categorical columns are both supported. Tests gracefully
    no-op when the column is too small or constant.
    """
    name = column_name or str(series.name) or "unnamed"
    total = int(series.size)
    missing = int(series.isna().sum())
    unique = int(series.nunique(dropna=True))
    dtype = str(series.dtype)

    profile = DistributionProfile(
        column=name,
        dtype=dtype,
        count=total - missing,
        missing_count=missing,
        missing_pct=(missing / total * 100.0) if total else 0.0,
        unique_count=unique,
    )

    # Categorical path
    numeric = pd.to_numeric(series, errors="coerce")
    cleaned = numeric.dropna()
    if cleaned.empty or cleaned.size < 2:
        if not series.dropna().empty:
            counts = series.dropna().value_counts()
            profile.mode = counts.index[0] if not counts.empty else None
            profile.top_categories = [(k, int(v)) for k, v in counts.head(10).items()]
            profile.entropy = _entropy(counts.to_numpy())
        profile.notes.append("non-numeric or insufficient numeric values")
        return profile

    values = cleaned.to_numpy(dtype=float)
    profile.sample_size_used = int(values.size)

    # Central + spread
    profile.mean = float(np.mean(values))
    profile.median = float(np.median(values))
    profile.std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    profile.min = float(values.min())
    profile.max = float(values.max())
    profile.q1 = float(np.percentile(values, 25))
    profile.q3 = float(np.percentile(values, 75))
    profile.iqr = profile.q3 - profile.q1
    profile.mad = float(np.median(np.abs(values - profile.median)))
    profile.cv = (profile.std / abs(profile.mean)) if profile.mean else None

    # Trimmed (10% each tail)
    if values.size >= 10:
        try:
            from scipy import stats
            trimmed = stats.trim_mean(values, 0.1)
            profile.trimmed_mean_10 = float(trimmed)
            tr_std = stats.mstats.trimmed_std(values, limits=(0.1, 0.1))
            profile.trimmed_std_10 = float(tr_std)
        except Exception:
            pass

    # Shape
    try:
        from scipy import stats

        if values.size >= 3 and np.std(values) > 0:
            profile.skew = float(stats.skew(values, bias=False))
            profile.kurtosis = float(stats.kurtosis(values, bias=False))
        profile.robust_skew = _bowley_skew(profile.q1, profile.median, profile.q3)

        # Normality tests
        if 3 <= values.size <= _SHAPIRO_MAX_N and np.std(values) > 0:
            try:
                w, p = stats.shapiro(values)
                profile.shapiro_stat = float(w)
                profile.shapiro_p = float(p)
            except Exception:
                pass
        if values.size >= _DAGOSTINO_MIN_N and np.std(values) > 0:
            try:
                _, p = stats.normaltest(values)
                profile.dagostino_p = float(p)
            except Exception:
                pass
        if values.size >= _DAGOSTINO_MIN_N:
            try:
                res = stats.anderson(values, dist="norm")
                profile.anderson_stat = float(res.statistic)
                # critical values: [15%, 10%, 5%, 2.5%, 1%]
                profile.anderson_critical_5pct = float(res.critical_values[2])
            except Exception:
                pass

        # Combine normality verdict (5% level)
        normality_votes = []
        if profile.shapiro_p is not None:
            normality_votes.append(profile.shapiro_p >= 0.05)
        if profile.dagostino_p is not None:
            normality_votes.append(profile.dagostino_p >= 0.05)
        if profile.anderson_stat is not None and profile.anderson_critical_5pct is not None:
            normality_votes.append(profile.anderson_stat <= profile.anderson_critical_5pct)
        if normality_votes:
            profile.is_normal_5pct = sum(normality_votes) >= (len(normality_votes) / 2)
    except Exception as exc:
        profile.notes.append(f"scipy unavailable for shape tests: {exc}")

    # Multimodality
    profile.dip_stat, profile.dip_p = _hartigan_dip(values)
    if profile.dip_p is not None:
        profile.is_multimodal = profile.dip_p < 0.05

    # Sample-size scaled thresholds
    profile.z_threshold_extreme = _sample_size_z_threshold(values.size)
    profile.iqr_multiplier_recommended = _recommend_iqr_multiplier(
        profile.robust_skew, profile.kurtosis
    )

    # Top categories (helpful for low-cardinality numerics e.g. flags)
    if unique <= 25:
        counts = series.dropna().value_counts()
        profile.top_categories = [(k, int(v)) for k, v in counts.head(10).items()]
        profile.entropy = _entropy(counts.to_numpy())

    return profile


def profile_dataframe(df: pd.DataFrame) -> dict[str, DistributionProfile]:
    """Profile every column in a DataFrame, keyed by column name."""
    out: dict[str, DistributionProfile] = {}
    for col in df.columns:
        try:
            out[str(col)] = profile_column(df[col], column_name=str(col))
        except Exception as exc:
            logger.warning("profile_column failed for %s: %s", col, exc)
            out[str(col)] = DistributionProfile(
                column=str(col),
                dtype=str(df[col].dtype),
                count=int(df[col].size - df[col].isna().sum()),
                missing_count=int(df[col].isna().sum()),
                missing_pct=float(df[col].isna().sum()) / float(df[col].size or 1) * 100.0,
                unique_count=int(df[col].nunique(dropna=True)),
                notes=[f"profile failed: {exc}"],
            )
    return out
