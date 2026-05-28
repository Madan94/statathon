"""Missing-data mechanism detection.

Distinguishes:
  * MCAR — Missing Completely At Random
  * MAR  — Missing At Random (missingness depends on observed vars)
  * MNAR — Missing Not At Random (missingness depends on the missing values themselves)

Why this matters:
  * Mean/median imputation is OK under MCAR but biased under MAR/MNAR.
  * KNN imputation excels under MAR (it uses correlated predictors).
  * MNAR requires domain-specific handling and we should warn the user.

The detector uses a simplified Little's MCAR test approach:
  1. For each column with missing values, build a binary `is_missing` indicator.
  2. Test whether `is_missing` is predicted by other columns via point-biserial
     correlation (numeric features) or chi-square (categorical features).
  3. If no other column predicts missingness above threshold => MCAR-ish.
     If some columns predict it => MAR.
     If the *column's own* value predicts it (impossible to test directly,
     but skewed missingness within observed values suggests this) => MNAR-ish.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MissingMechanism:
    column: str
    mechanism: str           # 'MCAR' | 'MAR' | 'MNAR_SUSPECTED' | 'UNDETERMINED'
    confidence: float        # 0..1
    predictors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "mechanism": self.mechanism,
            "confidence": round(self.confidence, 4),
            "predictors": self.predictors,
            "notes": self.notes,
        }


_POINT_BISERIAL_THRESHOLD = 0.20
_CHI2_PVALUE_THRESHOLD = 0.01


def detect_missing_mechanism(
    df: pd.DataFrame,
    column: str,
    schema: dict[str, str] | None = None,
) -> MissingMechanism:
    """Detect whether `column`'s missing pattern is MCAR / MAR / MNAR-suspected."""
    if column not in df.columns:
        return MissingMechanism(column=column, mechanism="UNDETERMINED",
                                confidence=0.0, notes=["column not in dataframe"])

    series = df[column]
    is_missing = series.isna()
    miss_count = int(is_missing.sum())
    n = int(series.size)
    miss_rate = miss_count / max(n, 1)
    schema = schema or {}

    if miss_count == 0:
        return MissingMechanism(column=column, mechanism="MCAR",
                                confidence=1.0, notes=["no missing values"])

    if miss_count >= n - 2:
        return MissingMechanism(column=column, mechanism="UNDETERMINED",
                                confidence=0.0,
                                notes=["almost-fully-missing column"])

    # ---------------- Test each other column as a predictor of missingness ----------------
    predictors: list[dict[str, Any]] = []
    miss_arr = is_missing.to_numpy()

    for other in df.columns:
        if other == column:
            continue
        other_series = df[other]
        is_numeric = (
            schema.get(other) == "numeric"
            or pd.api.types.is_numeric_dtype(other_series)
        )
        try:
            if is_numeric:
                x = pd.to_numeric(other_series, errors="coerce").to_numpy(dtype=float)
                mask = np.isfinite(x)
                if mask.sum() < 8:
                    continue
                r = _point_biserial(miss_arr[mask], x[mask])
                if r is not None and abs(r) >= _POINT_BISERIAL_THRESHOLD:
                    predictors.append({
                        "column": str(other),
                        "signal": "point_biserial",
                        "strength": round(abs(float(r)), 4),
                    })
            else:
                p = _chi_square_pvalue(miss_arr, other_series)
                if p is not None and p <= _CHI2_PVALUE_THRESHOLD:
                    predictors.append({
                        "column": str(other),
                        "signal": "chi_square",
                        "strength": round(1.0 - float(p), 4),
                    })
        except Exception as exc:
            logger.debug("mechanism predictor test failed (%s vs %s): %s",
                         column, other, exc)

    predictors.sort(key=lambda r: r.get("strength", 0.0), reverse=True)
    predictors = predictors[:5]

    # ---------------- Verdict ----------------
    if not predictors:
        mechanism = "MCAR"
        confidence = min(0.95, 0.6 + 0.3 * (1 - miss_rate))
        notes = ["no observed-variable predicts missingness above threshold"]
    else:
        # If a predictor matches a known causal pattern (e.g. very high strength
        # on a single column) treat as MAR with high confidence.
        top_strength = predictors[0].get("strength", 0.0)
        if top_strength > 0.6:
            mechanism = "MAR"
            confidence = min(0.95, top_strength)
            notes = [f"{predictors[0]['column']} strongly predicts missingness"]
        else:
            mechanism = "MAR"
            confidence = max(0.5, top_strength)
            notes = [f"{len(predictors)} columns weakly predict missingness"]

    # MNAR heuristic: very high missing rate (>40%) + heavy concentration
    # of remaining values at one tail suggests the missing values themselves
    # cluster in a region of the variable's range we cannot observe.
    if miss_rate > 0.4 and mechanism == "MCAR":
        mechanism = "MNAR_SUSPECTED"
        confidence = min(confidence, 0.5)
        notes.append(f"high missing rate ({miss_rate:.0%}) without observed predictors")

    return MissingMechanism(
        column=column, mechanism=mechanism, confidence=confidence,
        predictors=predictors, notes=notes,
    )


def _point_biserial(binary: np.ndarray, continuous: np.ndarray) -> float | None:
    """Point-biserial correlation between a binary indicator and a continuous variable."""
    if binary.size != continuous.size:
        return None
    b = binary.astype(bool)
    if b.sum() < 2 or (~b).sum() < 2:
        return None
    try:
        from scipy import stats
        r, _ = stats.pointbiserialr(b.astype(int), continuous)
        if r != r:
            return None
        return float(r)
    except Exception:
        # Manual fallback
        m1 = continuous[b].mean()
        m0 = continuous[~b].mean()
        sd = continuous.std(ddof=1)
        if sd == 0:
            return None
        n1, n0 = b.sum(), (~b).sum()
        n = n1 + n0
        return float((m1 - m0) / sd * np.sqrt((n1 * n0) / (n * n)))


def _chi_square_pvalue(missing: np.ndarray, other: pd.Series) -> float | None:
    """Chi-square p-value of independence between missing-indicator and a categorical."""
    if other.empty:
        return None
    other_arr = other.fillna("__NA__").astype(str).to_numpy()
    if other_arr.size != missing.size:
        return None
    try:
        # Cap categories
        codes, _ = pd.factorize(pd.Series(other_arr), use_na_sentinel=False)
        unique = np.unique(codes)
        if unique.size > 30 or unique.size < 2:
            return None
        ct = pd.crosstab(pd.Series(missing.astype(int)), pd.Series(codes))
        if ct.size == 0:
            return None
        from scipy import stats
        _, p, _, _ = stats.chi2_contingency(ct)
        return float(p)
    except Exception:
        return None


def detect_all(df: pd.DataFrame,
               schema: dict[str, str] | None = None) -> dict[str, MissingMechanism]:
    out: dict[str, MissingMechanism] = {}
    for col in df.columns:
        if df[col].isna().any():
            out[str(col)] = detect_missing_mechanism(df, str(col), schema=schema)
    return out
