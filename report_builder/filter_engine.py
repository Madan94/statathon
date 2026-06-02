"""Apply user-defined data filters before report generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class DataFilterSpec:
    include_columns: list[str] | None = None
    exclude_columns: list[str] | None = None
    max_rows: int | None = None
    min_complete_row_pct: float | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> DataFilterSpec | None:
        if not raw or not isinstance(raw, dict):
            return None
        return cls(
            include_columns=raw.get("include_columns"),
            exclude_columns=raw.get("exclude_columns"),
            max_rows=raw.get("max_rows"),
            min_complete_row_pct=raw.get("min_complete_row_pct"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_columns": self.include_columns,
            "exclude_columns": self.exclude_columns,
            "max_rows": self.max_rows,
            "min_complete_row_pct": self.min_complete_row_pct,
        }


def apply_filters(df: pd.DataFrame, spec: DataFilterSpec | None) -> pd.DataFrame:
    if df is None or df.empty or spec is None:
        return df

    out = df.copy()

    if spec.include_columns:
        cols = [c for c in spec.include_columns if c in out.columns]
        if cols:
            out = out[cols]

    if spec.exclude_columns:
        drop = [c for c in spec.exclude_columns if c in out.columns]
        if drop:
            out = out.drop(columns=drop, errors="ignore")

    if spec.min_complete_row_pct is not None and len(out) > 0:
        threshold = float(spec.min_complete_row_pct) / 100.0
        complete = out.notna().all(axis=1)
        min_required = int(len(out.columns) * threshold)
        if min_required > 0:
            row_complete = out.notna().sum(axis=1) >= min_required
            out = out.loc[row_complete]

    if spec.max_rows is not None and spec.max_rows > 0:
        out = out.head(int(spec.max_rows))

    return out
