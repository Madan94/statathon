"""Apply weight selection to the statistical layer without mutating raw values."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from core.ingestion import infer_schema
from core.json_safe import make_json_safe

_ID_PATTERN = re.compile(r"(^id$|_id$|^row[_]?index$|^index$|^serial$|^uuid$)", re.I)
_WEIGHT_SUFFIX = "_weighted"


def _exclude_from_semantic(column: str, semantic_mapping: dict[str, Any] | None) -> bool:
    if not semantic_mapping:
        return False
    meta = semantic_mapping.get(column)
    if not isinstance(meta, dict):
        return False
    role = str(meta.get("role") or meta.get("column_role") or "").lower()
    domain = str(meta.get("domain") or meta.get("semantic_domain") or "").lower()
    if role in {"identifier", "id", "key", "primary_key"}:
        return True
    if domain in {"identifier", "metadata", "survey_metadata"} and "weight" not in column.lower():
        return True
    return False


def _is_measure_column(
    column: str,
    series: pd.Series,
    schema: dict[str, str],
    weight_column: str,
    exclude: set[str],
    semantic_mapping: dict[str, Any] | None,
) -> bool:
    if column == weight_column or column in exclude:
        return False
    if column.endswith(_WEIGHT_SUFFIX):
        return False
    if _ID_PATTERN.search(column):
        return False
    if _exclude_from_semantic(column, semantic_mapping):
        return False
    nunique = series.nunique(dropna=True)
    if schema.get(column) == "categorical" and nunique <= 20:
        return False
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() < 1:
        return False
    return True


def apply_weight_to_dataset(
    df: pd.DataFrame,
    weight_column: str,
    *,
    exclude_columns: set[str] | list[str] | None = None,
    suffix: str = _WEIGHT_SUFFIX,
    semantic_mapping: dict[str, Any] | None = None,
    schema: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Produce working weighted dataset snapshot with parallel weighted columns.

    Raw cell values are preserved; numeric measures receive companion columns
    ``{column}{suffix}`` using normalized weight expansion (value * weight / mean(weight)).
    """
    if weight_column not in df.columns:
        raise ValueError(f"Weight column not found: {weight_column}")

    out = df.copy()
    schema = schema or infer_schema(df)
    exclude = set(exclude_columns or [])
    weights = pd.to_numeric(out[weight_column], errors="coerce").fillna(0.0)
    positive = weights[weights > 0]
    if len(positive) < 1:
        raise ValueError(f"Weight column has no positive values: {weight_column}")
    w_mean = float(positive.mean())

    weighted_columns: list[str] = []
    for col in out.columns:
        if not _is_measure_column(
            str(col),
            out[col],
            schema,
            weight_column,
            exclude,
            semantic_mapping,
        ):
            continue
        numeric = pd.to_numeric(out[col], errors="coerce")
        target = f"{col}{suffix}"
        out[target] = numeric * weights / w_mean
        weighted_columns.append(target)

    meta = make_json_safe(
        {
            "weight_column": weight_column,
            "applied": True,
            "working_dataset_weighted": True,
            "row_count": len(out),
            "column_count": len(out.columns),
            "weighted_columns": weighted_columns,
            "suffix": suffix,
            "transform_mode": "parallel_columns",
            "weight_normalization": "divide_by_mean",
        }
    )
    return out, meta
