"""Dataset summarizer — computes the canonical Dataset Summary Object.

Input:  analysis payload (dict from AnalysisState.to_api_payload())
        raw DataFrame (optional, for live recomputation)

Output: DatasetSummary object with health_score, key_patterns, important_metrics

The summary object drives:
  - Scribe agent (facts source)
  - Verifier agent (ground truth)
  - Chart selector (distribution signals)
  - Narrative planner (section planning)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DatasetSummary — canonical output
# ---------------------------------------------------------------------------

@dataclass
class DatasetSummary:
    """Comprehensive dataset intelligence summary."""

    # Core dimensions
    row_count: int = 0
    column_count: int = 0
    numeric_column_count: int = 0
    categorical_column_count: int = 0
    datetime_column_count: int = 0

    # Quality indicators
    missing_pct: float = 0.0
    duplicate_rows: int = 0
    complete_rows: int = 0
    complete_row_pct: float = 0.0

    # Anomaly / imputation
    anomaly_count: int = 0
    anomaly_columns: list[str] = field(default_factory=list)
    imputation_count: int = 0
    imputation_columns: list[str] = field(default_factory=list)

    # Semantic
    dataset_type: str = "unknown"
    mapped_column_count: int = 0
    domain_distribution: dict[str, int] = field(default_factory=dict)
    cluster_count: int = 0

    # Statistical profiles
    skewed_columns: list[str] = field(default_factory=list)
    high_cardinality_columns: list[str] = field(default_factory=list)
    low_variance_columns: list[str] = field(default_factory=list)
    highly_correlated_pairs: list[dict[str, Any]] = field(default_factory=list)

    # Health
    health_score: float = 0.0
    health_band: str = "unknown"    # excellent/good/fair/poor/critical
    health_flags: list[str] = field(default_factory=list)

    # Patterns
    key_patterns: list[str] = field(default_factory=list)
    important_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "numeric_column_count": self.numeric_column_count,
            "categorical_column_count": self.categorical_column_count,
            "datetime_column_count": self.datetime_column_count,
            "missing_pct": round(self.missing_pct, 2),
            "duplicate_rows": self.duplicate_rows,
            "complete_rows": self.complete_rows,
            "complete_row_pct": round(self.complete_row_pct, 2),
            "anomaly_count": self.anomaly_count,
            "anomaly_columns": self.anomaly_columns,
            "imputation_count": self.imputation_count,
            "imputation_columns": self.imputation_columns,
            "dataset_type": self.dataset_type,
            "mapped_column_count": self.mapped_column_count,
            "domain_distribution": self.domain_distribution,
            "cluster_count": self.cluster_count,
            "skewed_columns": self.skewed_columns,
            "high_cardinality_columns": self.high_cardinality_columns,
            "low_variance_columns": self.low_variance_columns,
            "highly_correlated_pairs": self.highly_correlated_pairs[:10],
            "health_score": round(self.health_score, 1),
            "health_band": self.health_band,
            "health_flags": self.health_flags,
            "key_patterns": self.key_patterns,
            "important_metrics": self.important_metrics,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_dataset_summary(
    analysis_payload: dict[str, Any],
    df: pd.DataFrame | None = None,
) -> DatasetSummary:
    """Build the canonical DatasetSummary from analysis payload + optional DataFrame."""
    s = DatasetSummary()

    # ---- Dimensions from payload health ----
    health = (
        analysis_payload.get("health")
        or (analysis_payload.get("profiling_summary") or {}).get("health")
        or {}
    )
    s.row_count = int(health.get("row_count") or 0)
    s.column_count = int(health.get("column_count") or 0)
    s.missing_pct = float(health.get("missing_pct") or 0.0)
    s.duplicate_rows = int(health.get("duplicate_rows") or 0)

    # ---- Live recomputation from DataFrame ----
    if df is not None and not df.empty:
        s.row_count = len(df)
        s.column_count = len(df.columns)
        total = float(df.size) or 1.0
        s.missing_pct = float(df.isna().sum().sum()) / total * 100.0
        s.duplicate_rows = int(df.duplicated().sum())
        s.complete_rows = int(df.dropna().shape[0])
        s.complete_row_pct = s.complete_rows / max(s.row_count, 1) * 100.0

        # Type breakdown
        for col in df.columns:
            dtype = df[col].dtype
            if pd.api.types.is_numeric_dtype(dtype):
                s.numeric_column_count += 1
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                s.datetime_column_count += 1
            else:
                s.categorical_column_count += 1

        # Skewness
        for col in df.select_dtypes(include="number").columns:
            series = df[col].dropna()
            if len(series) < 10:
                continue
            try:
                sk = float(series.skew())
                if abs(sk) > 1.5:
                    s.skewed_columns.append(str(col))
            except Exception:
                pass

        # High cardinality
        for col in df.select_dtypes(exclude="number").columns:
            n_unique = int(df[col].nunique())
            n_rows = len(df)
            if n_unique > 0.8 * n_rows and n_rows > 50:
                s.high_cardinality_columns.append(str(col))

        # Low variance
        for col in df.select_dtypes(include="number").columns:
            series = df[col].dropna()
            if len(series) < 5:
                continue
            try:
                cv = float(series.std(ddof=0)) / (abs(float(series.mean())) + 1e-9)
                if cv < 0.01:
                    s.low_variance_columns.append(str(col))
            except Exception:
                pass

        # Top correlations
        try:
            num_df = df.select_dtypes(include="number")
            if len(num_df.columns) >= 2:
                corr_mat = num_df.corr(method="pearson")
                pairs: list[dict[str, Any]] = []
                visited: set[frozenset] = set()
                for col_a in corr_mat.columns:
                    for col_b in corr_mat.columns:
                        if col_a == col_b:
                            continue
                        key = frozenset([col_a, col_b])
                        if key in visited:
                            continue
                        visited.add(key)
                        r = corr_mat.loc[col_a, col_b]
                        if math.isnan(r):
                            continue
                        if abs(r) >= 0.7:
                            pairs.append({
                                "col_a": col_a,
                                "col_b": col_b,
                                "r": round(float(r), 3),
                                "strength": "strong" if abs(r) >= 0.85 else "moderate",
                            })
                s.highly_correlated_pairs = sorted(pairs, key=lambda p: -abs(p["r"]))[:10]
        except Exception:
            pass
    else:
        # From payload column_profiles
        col_profiles = analysis_payload.get("column_profiles") or {}
        for col, profile in (col_profiles if isinstance(col_profiles, dict) else {}).items():
            dtype = str(profile.get("dtype") or "")
            if "int" in dtype or "float" in dtype:
                s.numeric_column_count += 1
            elif "datetime" in dtype:
                s.datetime_column_count += 1
            else:
                s.categorical_column_count += 1

    # ---- Phase 3 anomaly / imputation ----
    phase3 = analysis_payload.get("phase3") or {}
    if isinstance(phase3, dict):
        anomalies = phase3.get("anomaly_candidates") or []
        if isinstance(anomalies, list):
            s.anomaly_count = len(anomalies)
            s.anomaly_columns = sorted(
                {c.get("column") for c in anomalies if isinstance(c, dict) and c.get("column")}
            )
        imputations = phase3.get("imputation_candidates") or []
        if isinstance(imputations, list):
            s.imputation_count = len(imputations)
            s.imputation_columns = sorted(
                {c.get("column") for c in imputations if isinstance(c, dict) and c.get("column")}
            )

    # ---- Semantic ----
    ctx = analysis_payload.get("dataset_context") or {}
    s.dataset_type = str(ctx.get("dataset_type") or ctx.get("ontology_macro_type_best_hint") or "unknown")

    mapping = analysis_payload.get("semantic_mapping") or []
    if isinstance(mapping, list):
        s.mapped_column_count = sum(
            1 for r in mapping if isinstance(r, dict) and r.get("domain")
        )
        for row in mapping:
            if isinstance(row, dict) and row.get("domain"):
                dom = str(row["domain"])
                s.domain_distribution[dom] = s.domain_distribution.get(dom, 0) + 1

    clusters = analysis_payload.get("clusters") or []
    s.cluster_count = len(clusters) if isinstance(clusters, list) else 0

    # ---- Health score ----
    s.health_score, s.health_band, s.health_flags = _compute_health(s)

    # ---- Key patterns ----
    s.key_patterns = _extract_patterns(s, analysis_payload)

    # ---- Important metrics ----
    s.important_metrics = _extract_important_metrics(s, analysis_payload, df)

    return s


def _compute_health(s: DatasetSummary) -> tuple[float, str, list[str]]:
    """Compute 0-100 health score from quality signals."""
    score = 100.0
    flags: list[str] = []

    if s.missing_pct > 30:
        score -= 25
        flags.append(f"high missing rate ({s.missing_pct:.1f}%)")
    elif s.missing_pct > 10:
        score -= 12
        flags.append(f"elevated missing rate ({s.missing_pct:.1f}%)")
    elif s.missing_pct > 5:
        score -= 5

    if s.anomaly_count > 0:
        penalty = min(20, s.anomaly_count * 0.5)
        score -= penalty
        flags.append(f"{s.anomaly_count} anomaly candidates detected")

    if s.duplicate_rows > 0:
        dup_pct = s.duplicate_rows / max(s.row_count, 1) * 100
        if dup_pct > 5:
            score -= 15
            flags.append(f"{s.duplicate_rows} duplicate rows ({dup_pct:.1f}%)")
        elif dup_pct > 1:
            score -= 5
            flags.append(f"{s.duplicate_rows} duplicate rows")

    if s.mapped_column_count < s.column_count * 0.5 and s.column_count > 0:
        score -= 8
        flags.append("low semantic mapping coverage")

    if s.column_count == 0:
        return 0.0, "critical", ["no columns detected"]

    score = max(0.0, min(100.0, score))
    band = "excellent" if score >= 90 else "good" if score >= 75 else "fair" if score >= 55 else "poor" if score >= 35 else "critical"
    return score, band, flags


def _extract_patterns(s: DatasetSummary, payload: dict[str, Any]) -> list[str]:
    patterns: list[str] = []

    if s.highly_correlated_pairs:
        pair = s.highly_correlated_pairs[0]
        patterns.append(
            f"Strong correlation (r={pair['r']}) between '{pair['col_a']}' and '{pair['col_b']}'"
        )

    if s.skewed_columns:
        n = len(s.skewed_columns)
        patterns.append(
            f"{n} column{'s' if n > 1 else ''} exhibit{'s' if n == 1 else ''} high skewness"
        )

    if s.domain_distribution:
        top_domain = max(s.domain_distribution, key=lambda d: s.domain_distribution[d])
        top_count = s.domain_distribution[top_domain]
        patterns.append(f"Most columns ({top_count}) map to domain '{top_domain}'")

    if s.imputation_columns:
        patterns.append(
            f"{len(s.imputation_columns)} column(s) recommended for imputation"
        )

    return patterns[:6]


def _extract_important_metrics(
    s: DatasetSummary,
    payload: dict[str, Any],
    df: pd.DataFrame | None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "row_count": s.row_count,
        "column_count": s.column_count,
        "missing_pct": f"{s.missing_pct:.2f}%",
        "health_score": f"{s.health_score:.0f}/100 ({s.health_band})",
        "anomaly_count": s.anomaly_count,
        "imputation_targets": s.imputation_count,
        "semantic_coverage": f"{s.mapped_column_count}/{s.column_count}",
        "dataset_type": s.dataset_type,
        "cluster_count": s.cluster_count,
        "numeric_columns": s.numeric_column_count,
        "categorical_columns": s.categorical_column_count,
    }

    if df is not None and not df.empty:
        num_cols = df.select_dtypes(include="number")
        if not num_cols.empty:
            for col in list(num_cols.columns)[:3]:
                series = num_cols[col].dropna()
                if not series.empty:
                    metrics[f"{col}_mean"] = round(float(series.mean()), 3)
                    metrics[f"{col}_std"] = round(float(series.std(ddof=0)), 3)

    return metrics
