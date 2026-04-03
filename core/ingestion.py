import os
import pandas as pd
from typing import Any

def load_file(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, engine="openpyxl")
    raise ValueError(f"Unsupported format: {ext}")

def infer_schema(df: pd.DataFrame) -> dict[str, str]:
    out = {}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            out[c] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(s):
            out[c] = "datetime"
        else:
            out[c] = "categorical"
    return out

def health_summary(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": len(df),
        "columns": len(df.columns),
        "missing_per_column": df.isna().sum().astype(int).to_dict(),
        "duplicate_rows": int(df.duplicated().sum()),
    }