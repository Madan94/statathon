"""Shared numeric-column detection for outlier workflow."""
from __future__ import annotations

import pandas as pd

_NUMERIC_SCHEMA_TYPES = frozenset(
    {"numeric", "float", "int", "integer", "number", "decimal", "double", "long"}
)
_NON_NUMERIC_SCHEMA_TYPES = frozenset(
    {"string", "categorical", "category", "object", "bool", "boolean", "datetime", "date", "text"}
)


def is_numeric_schema_type(dtype: str | None) -> bool:
    if not dtype:
        return False
    key = str(dtype).strip().lower()
    if key in _NUMERIC_SCHEMA_TYPES:
        return True
    if key in _NON_NUMERIC_SCHEMA_TYPES:
        return False
    return any(token in key for token in ("int", "float", "num", "decimal", "double"))


def is_numeric_column(schema_type: str | None, series: pd.Series | None = None) -> bool:
    if is_numeric_schema_type(schema_type):
        return True
    if series is not None and pd.api.types.is_numeric_dtype(series):
        return True
    if series is not None:
        coerced = pd.to_numeric(series, errors="coerce")
        valid = coerced.notna().sum()
        if valid >= max(3, int(len(series) * 0.5)):
            return True
    return False
