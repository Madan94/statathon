"""Apply weight selection to the statistical layer without mutating raw values."""
from __future__ import annotations

from typing import Any

import pandas as pd

from core.json_safe import make_json_safe


def apply_weight_to_dataset(
    df: pd.DataFrame,
    weight_column: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Produce working weighted dataset snapshot metadata.

    Raw cell values are preserved; weight application is recorded in metadata for
    downstream weighted statistics and dataset review.
    """
    if weight_column not in df.columns:
        raise ValueError(f"Weight column not found: {weight_column}")

    out = df.copy()
    meta = make_json_safe(
        {
            "weight_column": weight_column,
            "applied": True,
            "working_dataset_weighted": True,
            "row_count": len(out),
            "column_count": len(out.columns),
        }
    )
    return out, meta
