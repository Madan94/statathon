"""Extract dataset metadata immediately after upload (before analysis pipeline)."""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any

import pandas as pd

from core.ingestion import load_dataframe_from_object_bytes, load_file

_DEBUG_LOG = "/media/akassh/New Volume/MOSPI/statathon/.cursor/debug-e80a72.log"


def _agent_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "e80a72",
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    }
                )
                + "\n"
            )
    except OSError:
        pass
    # #endregion


def _json_safe(value: Any) -> Any:
    """Recursively convert NaN/Inf/pandas NA to None for PostgreSQL JSON columns."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _json_safe(value.item())
        except (ValueError, AttributeError):
            pass
    return value


def _preview_rows_json_safe(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Serialize preview rows with nulls instead of NaN (Postgres JSON rejects NaN)."""
    if df.empty:
        return []
    return json.loads(df.head(10).to_json(orient="records", date_format="iso"))


def _is_numeric_column(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    coerced = pd.to_numeric(series, errors="coerce")
    non_null = series.notna().sum()
    if non_null == 0:
        return False
    return coerced.notna().sum() >= max(3, non_null // 2)


def _build_profile(df: pd.DataFrame, file_size_bytes: int, filename: str) -> dict[str, Any]:
    rows = int(len(df))
    cols = int(len(df.columns))
    missing_cells = int(df.isna().sum().sum())
    total_cells = rows * cols if rows and cols else 0
    duplicate_rows = int(df.duplicated().sum())
    numeric_columns = sum(1 for c in df.columns if _is_numeric_column(df[c]))
    categorical_columns = cols - numeric_columns
    memory_usage_bytes = int(df.memory_usage(deep=True).sum())
    missing_pct = (missing_cells / total_cells * 100.0) if total_cells else 0.0
    completeness_pct = round(100.0 - missing_pct, 2) if total_cells else 100.0
    consistency_pct = round(
        max(0.0, 100.0 - (duplicate_rows / rows * 100.0 if rows else 0.0)),
        2,
    )

    preview_rows = _preview_rows_json_safe(df)
    # #region agent log
    nan_in_preview = sum(
        1
        for row in preview_rows
        for v in row.values()
        if isinstance(v, float) and math.isnan(v)
    )
    _agent_log(
        "A",
        "dataset_profiler.py:_build_profile",
        "preview_rows before json_safe wrap",
        {"row_count": rows, "preview_len": len(preview_rows), "nan_in_preview": nan_in_preview},
    )
    # #endregion

    column_list = [str(c) for c in df.columns]
    dtypes = {str(c): str(df[c].dtype) for c in df.columns}
    missing_per_column = {str(k): int(v) for k, v in df.isna().sum().items()}

    health_summary = _json_safe(
        {
            "rows": rows,
            "columns": cols,
            "missing_cells": missing_cells,
            "duplicate_rows": duplicate_rows,
            "numeric_columns": numeric_columns,
            "categorical_columns": categorical_columns,
            "column_list": column_list,
            "dtypes": dtypes,
            "missing_per_column": missing_per_column,
            "memory_usage_mb": round(memory_usage_bytes / (1024 * 1024), 2),
            "completeness_pct": completeness_pct,
            "consistency_pct": consistency_pct,
            "preview_rows": preview_rows,
        }
    )
    # #region agent log
    _agent_log(
        "A",
        "dataset_profiler.py:_build_profile",
        "health_summary after json_safe",
        {
            "preview_sample_quarter": (
                health_summary.get("preview_rows", [{}])[0].get("quarter")
                if health_summary.get("preview_rows")
                else None
            ),
            "health_summary_json_valid": True,
        },
    )
    # #endregion

    return {
        "rows": rows,
        "columns": cols,
        "row_count": rows,
        "column_count": cols,
        "file_size_bytes": file_size_bytes,
        "file_size_mb": round(file_size_bytes / (1024 * 1024), 2),
        "missing_cells": missing_cells,
        "duplicate_rows": duplicate_rows,
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "column_list": column_list,
        "dtypes": dtypes,
        "memory_usage_mb": health_summary["memory_usage_mb"],
        "completeness_pct": completeness_pct,
        "consistency_pct": consistency_pct,
        "health_summary": health_summary,
        "name": filename,
    }


def profile_dataset(file_path: str, filename: str | None = None) -> dict[str, Any]:
    """Profile a CSV/XLSX file on local disk."""
    name = filename or os.path.basename(file_path)
    file_size_bytes = os.path.getsize(file_path)
    df = load_file(file_path)
    return _build_profile(df, file_size_bytes, name)


def profile_dataset_bytes(body: bytes, filename: str) -> dict[str, Any]:
    """Profile CSV/XLSX content from in-memory bytes (object storage flow)."""
    df = load_dataframe_from_object_bytes(filename, body)
    return _build_profile(df, len(body), filename)
