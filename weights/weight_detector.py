"""Detect candidate survey / sampling weight columns."""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

_WEIGHT_NAME_RE = re.compile(
    r"(^weight$|^weights$|^wt$|^wgt$|weightage|sample[_\s]?weight|hh[_\s]?weight|"
    r"person[_\s]?weight|survey[_\s]?weight|expansion[_\s]?factor|multiplier|"
    r"final[_\s]?wt|population[_\s]?weight|wt[_\s]?hh|expansion|_factor$|^factor$|"
    r"survey[_\s]?wt|design[_\s]?weight|rep[_\s]?weight)",
    re.I,
)

_WEIGHT_DOMAIN_HINTS = frozenset(
    {
        "survey_metadata",
        "survey_design",
        "sampling",
        "population_representation",
        "expansion_factors",
        "household",
        "demographic",
    }
)


def _name_score(column: str) -> float:
    normalized = str(column).replace(" ", "_")
    if _WEIGHT_NAME_RE.search(normalized):
        return 0.98
    if "weight" in normalized.lower() or "multiplier" in normalized.lower():
        return 0.72
    return 0.0


def _semantic_score(column: str, semantic_mapping: dict[str, Any] | None) -> float:
    if not semantic_mapping:
        return 0.0
    meta = semantic_mapping.get(column)
    if not isinstance(meta, dict):
        return 0.0
    domain = str(meta.get("domain") or meta.get("semantic_domain") or "").lower()
    subdomain = str(meta.get("subdomain") or meta.get("sub_domain") or "").lower()
    text = f"{domain} {subdomain}"
    if any(h in text for h in _WEIGHT_DOMAIN_HINTS):
        return 0.91
    if "weight" in text or "sample" in text:
        return 0.65
    return 0.0


def _statistics_score(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if len(valid) < 2:
        return 0.0
    if (valid <= 0).any():
        return 0.15
    if valid.nunique() <= 1:
        return 0.2
    cv = float(valid.std() / (valid.mean() + 1e-12))
    if cv < 0.01:
        return 0.35
    missing_ratio = 1.0 - (len(valid) / max(len(series), 1))
    if missing_ratio > 0.2:
        return 0.25
    score = 0.55
    if cv >= 0.05:
        score += 0.15
    if cv >= 0.2:
        score += 0.1
    if missing_ratio <= 0.05:
        score += 0.08
    return min(score, 0.95)


def detect_weight_columns(
    df: pd.DataFrame,
    schema: dict[str, str] | None = None,
    *,
    semantic_mapping: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return ranked weight column candidates with confidence and signal breakdown."""
    schema = schema or {}
    candidates: list[dict[str, Any]] = []
    for col in df.columns:
        col_name = str(col)
        nunique = df[col_name].nunique(dropna=True)
        name = _name_score(col_name)
        if schema.get(col_name) == "categorical" and nunique <= 5 and name <= 0:
            continue
        semantic = _semantic_score(col_name, semantic_mapping)
        stats = _statistics_score(df[col_name])
        if name <= 0 and semantic <= 0 and stats < 0.4:
            continue
        confidence = round(0.45 * name + 0.30 * semantic + 0.25 * stats, 4)
        if confidence < 0.35:
            continue
        candidates.append(
            {
                "column": col_name,
                "confidence": confidence,
                "signals": {
                    "name": round(name, 4),
                    "semantic": round(semantic, 4),
                    "statistics": round(stats, 4),
                },
            }
        )
    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    return candidates
