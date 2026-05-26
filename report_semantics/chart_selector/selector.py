"""Chart selector — recommends the appropriate chart type for each column/block.

Rules (MoSPI-aligned):
  numeric, low-cardinality   → histogram / bar
  numeric, high values       → box plot
  categorical, ≤12 values    → bar chart
  categorical, >12 values    → horizontal bar
  time series                → line chart
  two numeric columns        → scatter plot
  multiple columns           → grouped bar / heatmap
  missing data               → horizontal bar
  distribution comparison    → box plot
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class ChartRecommendation:
    column: str
    chart_type: str      # bar / line / scatter / histogram / heatmap / box
    title: str
    source: str          # key into facts dict or payload
    x_label: str = ""
    y_label: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "chart_type": self.chart_type,
            "title": self.title,
            "source": self.source,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "notes": self.notes,
        }


def select_charts(
    analysis_payload: dict[str, Any],
    df: pd.DataFrame | None = None,
) -> list[ChartRecommendation]:
    """Build chart recommendations for the dataset."""
    recs: list[ChartRecommendation] = []

    # Missing-values bar chart (always present if any missing data)
    health = (
        analysis_payload.get("health")
        or (analysis_payload.get("profiling_summary") or {}).get("health")
        or {}
    )
    missing_pct = float(health.get("missing_pct") or 0.0)
    if missing_pct > 0:
        recs.append(ChartRecommendation(
            column="__missing__",
            chart_type="bar",
            title="Missing Values by Column",
            source="missing_per_column",
            x_label="Column",
            y_label="Missing Count",
            notes="Highlights columns requiring imputation",
        ))

    if df is not None and not df.empty:
        for col in df.columns:
            series = df[col]
            is_numeric = pd.api.types.is_numeric_dtype(series)
            is_datetime = pd.api.types.is_datetime64_any_dtype(series)
            n_unique = int(series.nunique())
            n_rows = len(df)

            if is_datetime:
                recs.append(ChartRecommendation(
                    column=str(col),
                    chart_type="line",
                    title=f"{col} — Time Series",
                    source=f"column:{col}",
                    x_label=str(col),
                    y_label="Value",
                ))
                continue

            if is_numeric:
                if n_rows > 100:
                    recs.append(ChartRecommendation(
                        column=str(col),
                        chart_type="histogram",
                        title=f"{col} — Distribution",
                        source=f"column:{col}",
                        x_label=str(col),
                        y_label="Frequency",
                    ))
                else:
                    recs.append(ChartRecommendation(
                        column=str(col),
                        chart_type="bar",
                        title=f"{col} — Value Distribution",
                        source=f"column:{col}",
                        x_label="Value",
                        y_label="Count",
                    ))
                continue

            if n_unique <= 12:
                recs.append(ChartRecommendation(
                    column=str(col),
                    chart_type="bar",
                    title=f"{col} — Category Distribution",
                    source=f"column:{col}",
                    x_label=str(col),
                    y_label="Count",
                ))
            else:
                recs.append(ChartRecommendation(
                    column=str(col),
                    chart_type="bar",
                    title=f"{col} — Top 15 Categories",
                    source=f"column:{col}",
                    x_label="Count",
                    y_label=str(col),
                    notes="Top 15 by frequency; horizontal bar recommended",
                ))

        # Correlation heatmap if ≥4 numeric columns
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if len(num_cols) >= 4:
            recs.append(ChartRecommendation(
                column="__correlation__",
                chart_type="heatmap",
                title="Numeric Column Correlation Heatmap",
                source="correlation_matrix",
                notes=f"{len(num_cols)} numeric columns",
            ))

    return recs[:20]  # cap at 20 recommendations
