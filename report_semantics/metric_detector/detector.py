"""Metric detector — identifies the key statistical metrics for a report section.

Given an analysis payload + DatasetSummary, it builds a prioritized metric
map grouped by section. The Scribe agent uses this to select which figures to
cite in each narrative block.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from report_semantics.summarizer.dataset_summarizer import DatasetSummary


_SECTION_METRIC_PRIORITY: dict[str, list[str]] = {
    "executive_summary": [
        "row_count", "column_count", "missing_pct", "health_score",
        "anomaly_count", "dataset_type", "cluster_count",
    ],
    "data_overview": [
        "column_count", "numeric_columns", "categorical_columns",
        "semantic_coverage", "cluster_count", "dataset_type",
    ],
    "data_quality": [
        "missing_pct", "duplicate_rows", "anomaly_count",
        "imputation_targets", "complete_row_pct",
    ],
    "findings": [
        "row_count", "missing_pct", "anomaly_count",
        "health_score", "semantic_coverage",
    ],
    "recommendations": [
        "missing_pct", "anomaly_count", "imputation_targets",
        "health_band", "health_flags",
    ],
}


def detect_key_metrics(
    summary: DatasetSummary,
    analysis_payload: dict[str, Any],
    df: pd.DataFrame | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    """Return section-specific metric dict from the DatasetSummary + payload.

    If `section` is provided, returns only the metrics relevant to that section.
    Otherwise returns the full metric map.
    """
    full = summary.important_metrics.copy()

    # Enrich from payload
    health = (
        analysis_payload.get("health")
        or (analysis_payload.get("profiling_summary") or {}).get("health")
        or {}
    )
    if isinstance(health, dict):
        for k, v in health.items():
            full.setdefault(k, v)

    full["health_band"] = summary.health_band
    full["health_flags"] = "; ".join(summary.health_flags) if summary.health_flags else "none"
    full["domain_distribution"] = summary.domain_distribution
    full["key_patterns"] = summary.key_patterns
    full["highly_correlated_pairs"] = [
        f"{p['col_a']}↔{p['col_b']} (r={p['r']})"
        for p in summary.highly_correlated_pairs[:5]
    ]

    # Per-column stats from DataFrame
    if df is not None and not df.empty:
        num = df.select_dtypes(include="number")
        col_stats: dict[str, dict] = {}
        for col in num.columns:
            series = num[col].dropna()
            if series.empty:
                continue
            col_stats[str(col)] = {
                "mean": round(float(series.mean()), 3),
                "median": round(float(series.median()), 3),
                "std": round(float(series.std(ddof=0)), 3),
                "min": round(float(series.min()), 3),
                "max": round(float(series.max()), 3),
                "missing": int(df[col].isna().sum()),
            }
        if col_stats:
            full["column_statistics"] = col_stats

    if section is None:
        return full

    priority_keys = _SECTION_METRIC_PRIORITY.get(section, list(full.keys()))
    return {k: full[k] for k in priority_keys if k in full}
