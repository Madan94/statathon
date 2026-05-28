"""Imputation execution + cross-validated method selection.

Three execution methods:
  * impute_mean(series)              — column mean
  * impute_median(series)            — column median
  * impute_mode(series)              — most frequent category / value
  * impute_knn(series, df, donors)   — KNN regression over donor numeric columns
  * impute_quantile_match(series)    — random draws from observed distribution
                                       (preserves skew + range)
  * impute_group_conditional(series, df, by_col) — group-wise method (MAR)

Cross-validation evaluator:
  * evaluate_methods(series, df, candidate_methods)
      Holds out 10% of observed values, imputes via each candidate, returns
      ranked RMSE / MAE per method. Used to select the empirically best
      method instead of relying solely on distributional heuristics.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Imputation methods
# ---------------------------------------------------------------------------


def impute_mean(series: pd.Series) -> pd.Series:
    out = series.copy()
    numeric = pd.to_numeric(out, errors="coerce")
    fill = numeric.dropna().mean()
    if pd.isna(fill):
        return out
    return out.fillna(fill)


def impute_median(series: pd.Series) -> pd.Series:
    out = series.copy()
    numeric = pd.to_numeric(out, errors="coerce")
    fill = numeric.dropna().median()
    if pd.isna(fill):
        return out
    return out.fillna(fill)


def impute_mode(series: pd.Series) -> pd.Series:
    out = series.copy()
    observed = out.dropna()
    if observed.empty:
        return out
    fill = observed.mode().iloc[0]
    return out.fillna(fill)


def impute_quantile_match(series: pd.Series,
                           rng: np.random.Generator | None = None) -> pd.Series:
    """Random draws from the observed empirical distribution.

    Preserves skew, range, and modal structure — useful when the column
    is heavily skewed or multimodal and mean/median would create an
    unrealistic point mass at the centre.
    """
    rng = rng or np.random.default_rng(2026)
    out = series.copy()
    observed = pd.to_numeric(out, errors="coerce").dropna()
    if observed.empty:
        return out
    missing_mask = out.isna()
    n_missing = int(missing_mask.sum())
    if n_missing == 0:
        return out
    draws = rng.choice(observed.to_numpy(), size=n_missing, replace=True)
    out_arr = out.to_numpy()
    miss_positions = np.where(missing_mask.to_numpy())[0]
    out_arr = out_arr.astype(object)
    for pos, val in zip(miss_positions, draws):
        out_arr[pos] = float(val)
    try:
        return pd.Series(out_arr.astype(float), index=out.index, name=out.name)
    except Exception:
        return pd.Series(out_arr, index=out.index, name=out.name)


def impute_knn(
    series: pd.Series,
    df: pd.DataFrame,
    *,
    donor_columns: list[str] | None = None,
    k: int = 5,
) -> pd.Series:
    """Light-weight KNN regression imputation against donor numeric columns."""
    out = series.copy()
    target = pd.to_numeric(out, errors="coerce")
    missing_mask = target.isna()
    if missing_mask.sum() == 0:
        return out

    # Pick donor columns: top-correlated numeric columns
    numeric_df = df.select_dtypes(include="number")
    if donor_columns is None:
        if numeric_df.shape[1] < 2:
            return impute_median(series)
        if str(series.name) in numeric_df.columns:
            abs_corr = numeric_df.corr().abs().get(series.name)
            if abs_corr is not None:
                donor_columns = (abs_corr.drop(series.name, errors="ignore")
                                          .sort_values(ascending=False)
                                          .head(8).index.tolist())
    if not donor_columns:
        return impute_median(series)

    # Standardise donors, train KNN on observed rows. Use the (potentially
    # masked) target series passed in — NOT df's copy — so cross-validation
    # holdouts stay hidden during imputation.
    try:
        from sklearn.impute import KNNImputer

        cols = [c for c in donor_columns if c in df.columns and c != str(series.name)]
        if not cols:
            return impute_median(series)
        X = df[cols].copy()
        target_col_name = str(series.name) if series.name is not None else "__target__"
        X[target_col_name] = pd.to_numeric(series, errors="coerce").values
        imputer = KNNImputer(n_neighbors=k, weights="distance")
        arr = imputer.fit_transform(X.to_numpy(dtype=float))
        target_idx = list(X.columns).index(target_col_name)
        out = pd.Series(arr[:, target_idx], index=series.index, name=series.name)
        return out
    except Exception as exc:
        logger.info("KNN imputation fallback to median: %s", exc)
        return impute_median(series)


def impute_group_conditional(
    series: pd.Series,
    df: pd.DataFrame,
    *,
    by_column: str,
    stat: str = "median",
) -> pd.Series:
    """Impute missing values with the within-group median/mean.

    Use when MAR mechanism is identified with a strong categorical predictor.
    """
    out = series.copy()
    if by_column not in df.columns:
        return impute_median(series) if stat == "median" else impute_mean(series)
    numeric = pd.to_numeric(out, errors="coerce")
    groups = df[by_column].astype(str)
    if stat == "median":
        fill = numeric.groupby(groups).transform("median")
    else:
        fill = numeric.groupby(groups).transform("mean")
    overall_fill = numeric.dropna().median()
    fill = fill.fillna(overall_fill)
    return out.fillna(fill)


# ---------------------------------------------------------------------------
# Cross-validation evaluator
# ---------------------------------------------------------------------------


MethodFn = Callable[[pd.Series], pd.Series]


def evaluate_methods(
    series: pd.Series,
    df: pd.DataFrame,
    *,
    candidate_methods: dict[str, MethodFn] | None = None,
    holdout_fraction: float = 0.10,
    rng_seed: int = 2026,
    min_observed: int = 20,
) -> dict[str, Any]:
    """Hold-out cross-validation for imputation methods.

    Hides `holdout_fraction` of currently-observed values, runs each candidate
    method to fill the holdouts, then measures RMSE + MAE. Returns ranked
    results.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    observed = numeric.dropna()
    if observed.size < min_observed:
        return {"method_scores": [], "reason": "insufficient observed values"}

    rng = np.random.default_rng(rng_seed)
    holdout_n = max(3, int(observed.size * holdout_fraction))
    holdout_idx = rng.choice(observed.index, size=holdout_n, replace=False)
    true_values = observed.loc[holdout_idx]

    if candidate_methods is None:
        candidate_methods = {
            "mean": impute_mean,
            "median": impute_median,
            "quantile_match": impute_quantile_match,
            "knn": lambda s: impute_knn(s, df),
        }

    results: list[dict[str, Any]] = []
    for name, fn in candidate_methods.items():
        masked = numeric.copy()
        masked.loc[holdout_idx] = np.nan
        try:
            imputed = fn(masked)
            preds = pd.to_numeric(imputed.loc[holdout_idx], errors="coerce")
            if preds.isna().any():
                continue
            err = preds.to_numpy() - true_values.to_numpy()
            rmse = float(np.sqrt(np.mean(err ** 2)))
            mae = float(np.mean(np.abs(err)))
            results.append({
                "method": name,
                "rmse": rmse,
                "mae": mae,
                "n_holdout": holdout_n,
            })
        except Exception as exc:
            logger.info("evaluate_methods(%s) failed: %s", name, exc)

    results.sort(key=lambda r: r["rmse"])
    return {
        "method_scores": results,
        "holdout_n": holdout_n,
        "winner": results[0]["method"] if results else None,
        "rmse_range": {
            "best": results[0]["rmse"] if results else None,
            "worst": results[-1]["rmse"] if results else None,
        },
    }


# ---------------------------------------------------------------------------
# High-level dispatcher
# ---------------------------------------------------------------------------


def impute(series: pd.Series, df: pd.DataFrame, method: str,
            *, group_by: str | None = None) -> pd.Series:
    method = method.lower()
    if method == "mean":
        return impute_mean(series)
    if method == "median":
        return impute_median(series)
    if method == "mode":
        return impute_mode(series)
    if method == "quantile_match":
        return impute_quantile_match(series)
    if method == "knn":
        return impute_knn(series, df)
    if method == "group_conditional" and group_by:
        return impute_group_conditional(series, df, by_column=group_by)
    raise ValueError(f"Unknown imputation method: {method}")
