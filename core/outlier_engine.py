import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

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

def isolation_outliers(X: np.ndarray) -> np.ndarray:
    if len(X) < 5:
        return np.array([], dtype=int)
    clf = IsolationForest(random_state=42, contamination="auto")
    pred = clf.fit_predict(X)
    return np.where(pred == -1)[0]

def risk_bucket(confidence: float) -> str:
    if confidence >= 0.7:
        return "low"
    if confidence >= 0.4:
        return "medium"
    return "high"