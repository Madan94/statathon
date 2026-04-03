import pandas as pd
from typing import Any

def single_column_rules(df: pd.DataFrame, col: str) -> list[dict]:
    issues = []
    s = df[col]
    if s.dtype in ("float64", "int64"):
        if s.min() < 0 and "age" in col.lower():
            issues.append({"col": col, "rule": "age_non_negative", "count": int((s < 0).sum())})
    return issues

def multi_column_rules(df: pd.DataFrame) -> list[dict]:
    return []

def normalize_schema(df: pd.DataFrame, schema: dict[str, str]) -> pd.DataFrame:
    out = df.copy()
    for c, t in schema.items():
        if c not in out.columns:
            continue
        if t == "numeric":
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out