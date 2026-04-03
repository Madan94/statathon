import pandas as pd
import numpy as np
from sklearn.impute import KNNImputer

def knn_impute_numeric(df: pd.DataFrame, cols: list[str], n_neighbors: int = 5) -> pd.DataFrame:
    out = df.copy()
    numeric = [c for c in cols if c in out.columns and pd.api.types.is_numeric_dtype(out[c])]
    if not numeric:
        return out
    imputer = KNNImputer(n_neighbors=min(n_neighbors, len(out)))
    out[numeric] = imputer.fit_transform(out[numeric])
    return out

def bias_delta(before: pd.Series, after: pd.Series) -> float:
    b = pd.to_numeric(before, errors="coerce")
    a = pd.to_numeric(after, errors="coerce")
    return float(abs(b.mean() - a.mean()) / (abs(b.mean()) + 1e-9))