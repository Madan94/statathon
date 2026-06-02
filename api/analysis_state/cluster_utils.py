"""Normalize cluster domain_distribution to fractions summing to 1.0."""
from __future__ import annotations

from typing import Any


def normalize_domain_distribution(
    dist: dict[str, Any] | None,
    *,
    fallback_domain: str | None = None,
    column_count: int | None = None,
) -> dict[str, float]:
    raw: dict[str, Any] | None = dist if isinstance(dist, dict) and dist else None
    if not raw and fallback_domain:
        raw = {fallback_domain: column_count or 1}
    if not raw:
        return {}

    total = sum(float(v) for v in raw.values() if v is not None)
    if total <= 0:
        return {}

    return {str(k): round(float(v) / total, 4) for k, v in raw.items()}


def normalize_clusters_payload(clusters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cluster in clusters or []:
        if not isinstance(cluster, dict):
            continue
        item = dict(cluster)
        cols = item.get("columns") or []
        col_count = len(cols) if isinstance(cols, list) else None
        item["domain_distribution"] = normalize_domain_distribution(
            item.get("domain_distribution"),
            fallback_domain=item.get("domain"),
            column_count=col_count,
        )
        out.append(item)
    return out
