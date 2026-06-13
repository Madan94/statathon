import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_SKLEARN_ISOLATION: type | None = None
_SKLEARN_ISOLATION_FAILED = False


def _get_isolation_forest():
    """Lazy import — Windows Application Control may block sklearn C extensions."""
    global _SKLEARN_ISOLATION, _SKLEARN_ISOLATION_FAILED
    if _SKLEARN_ISOLATION_FAILED:
        return None
    if _SKLEARN_ISOLATION is not None:
        return _SKLEARN_ISOLATION
    try:
        from sklearn.ensemble import IsolationForest

        _SKLEARN_ISOLATION = IsolationForest
        return _SKLEARN_ISOLATION
    except (ImportError, OSError) as exc:
        _SKLEARN_ISOLATION_FAILED = True
        logger.warning(
            "IsolationForest unavailable (%s); using IQR fallback for isolation outliers",
            exc,
        )
        return None


def zscore_outliers(series: pd.Series, thresh: float = 3.0) -> np.ndarray:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 3:
        return np.array([], dtype=int)
    z = np.abs((s - s.mean()) / (s.std() + 1e-9))
    return s.index[z > thresh].tolist()

def iqr_outliers(series: pd.Series) -> list:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 4:
        return []
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return s.index[(s < lo) | (s > hi)].tolist()

def _iqr_outlier_indices(flat: np.ndarray) -> np.ndarray:
    if len(flat) < 4:
        return np.array([], dtype=int)
    q1, q3 = np.percentile(flat, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return np.array([], dtype=int)
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return np.where((flat < lo) | (flat > hi))[0]


def isolation_outliers(X: np.ndarray) -> np.ndarray:
    if len(X) < 5:
        return np.array([], dtype=int)
    IsolationForest = _get_isolation_forest()
    if IsolationForest is None:
        return _iqr_outlier_indices(X.ravel())
    clf = IsolationForest(random_state=42, contamination="auto")
    pred = clf.fit_predict(X)
    return np.where(pred == -1)[0]

def risk_bucket(confidence: float) -> str:
    if confidence >= 0.7:
        return "low"
    if confidence >= 0.4:
        return "medium"
    return "high"