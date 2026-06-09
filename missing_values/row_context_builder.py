"""Build row-level context for missing-value review decisions."""
from __future__ import annotations

from typing import Any

import pandas as pd


def build_missing_row_context(
    df: pd.DataFrame,
    *,
    row_index: int,
    missing_column: str,
    context_columns: list[str] | None = None,
    max_context_cols: int = 8,
) -> dict[str, Any]:
    """Return neighboring column values for one missing row."""
    if row_index < 0 or row_index >= len(df):
        return {"row_index": row_index, "missing_column": missing_column, "context": {}}

    if context_columns:
        cols = [c for c in context_columns if c in df.columns and c != missing_column]
    else:
        cols = [c for c in df.columns if c != missing_column][:max_context_cols]

    row = df.iloc[row_index]
    context: dict[str, Any] = {}
    for col in cols[:max_context_cols]:
        val = row[col]
        if pd.isna(val):
            context[col] = None
        else:
            context[col] = val.item() if hasattr(val, "item") else val

    current = row[missing_column] if missing_column in df.columns else None
    return {
        "row_index": row_index,
        "missing_column": missing_column,
        "current_value": None if pd.isna(current) else current,
        "context": context,
    }


def build_missing_rows_payload(
    df: pd.DataFrame,
    column: str,
    *,
    method: str,
    imputed_series: pd.Series | None = None,
    recommended_value: Any = None,
    confidence: float = 0.0,
    reason: str = "",
    offset: int = 0,
    limit: int = 100,
    context_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Paginated missing rows with imputation preview + context."""
    if column not in df.columns:
        return {"total_missing": 0, "rows": []}

    series = df[column]
    missing_positions = [int(i) for i in range(len(df)) if pd.isna(series.iloc[i])]
    total = len(missing_positions)
    page = missing_positions[offset : offset + limit]
    rows: list[dict[str, Any]] = []

    for pos in page:
        preview_val = recommended_value
        if imputed_series is not None and pos < len(imputed_series):
            preview_val = imputed_series.iloc[pos]
        ctx = build_missing_row_context(
            df,
            row_index=pos,
            missing_column=column,
            context_columns=context_columns,
        )
        rows.append(
            {
                "row_index": pos,
                "missing_column": column,
                "original_value": None,
                "recommended_value": None if pd.isna(preview_val) else preview_val,
                "confidence": confidence,
                "method": method,
                "reason": reason,
                "context": ctx.get("context") or {},
            }
        )

    return {
        "total_missing": total,
        "offset": offset,
        "limit": limit,
        "rows": rows,
    }
