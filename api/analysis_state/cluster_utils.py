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


def unify_cluster_record(cl: dict[str, Any]) -> dict[str, Any]:
    """Map V2 and V1 cluster payloads to a unified dashboard/API shape."""
    domain = str(cl.get("domain") or cl.get("dominant_domain") or "")
    purity = cl.get("domain_purity")
    if purity is None:
        purity = cl.get("purity")
    if purity is None:
        purity = cl.get("support")
    support_score = cl.get("support_score")
    if support_score is None:
        support_score = cl.get("cluster_confidence")
    embedding_coherence = cl.get("embedding_coherence")
    avg_domain_confidence = cl.get("avg_domain_confidence")

    return {
        "cluster_id": cl.get("cluster_id") or cl.get("cluster_name"),
        "cluster_name": cl.get("cluster_name") or cl.get("cluster_id"),
        "domain": domain,
        "support_score": float(support_score or 0),
        "support": float(purity) if purity is not None else cl.get("support"),
        "domain_purity": float(purity or 0),
        "embedding_coherence": float(embedding_coherence) if embedding_coherence is not None else None,
        "avg_domain_confidence": float(avg_domain_confidence) if avg_domain_confidence is not None else None,
        "columns": list(cl.get("columns") or []),
        "domain_distribution": dict(cl.get("domain_distribution") or {}),
        "dominant_domain": cl.get("dominant_domain") or domain,
        "purity": purity,
        "cluster_confidence": support_score,
        "explainability": cl.get("explainability"),
    }


def cluster_from_db_row(
    cluster_name: str | None,
    semantic_domain: str | None,
    support_score: float | None,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Rebuild unified cluster dict from SemanticCluster DB row."""
    meta = meta or {}
    return unify_cluster_record(
        {
            "cluster_id": cluster_name,
            "domain": semantic_domain or meta.get("dominant_domain"),
            "support_score": support_score or meta.get("cluster_confidence"),
            "support": meta.get("support") or meta.get("purity") or meta.get("domain_purity"),
            "domain_purity": meta.get("domain_purity") or meta.get("purity"),
            "embedding_coherence": meta.get("embedding_coherence"),
            "avg_domain_confidence": meta.get("avg_domain_confidence"),
            "columns": meta.get("columns"),
            "domain_distribution": meta.get("domain_distribution"),
            "dominant_domain": meta.get("dominant_domain"),
            "purity": meta.get("purity"),
            "cluster_confidence": meta.get("cluster_confidence"),
            "explainability": meta.get("explainability"),
        }
    )


def normalize_clusters_payload(clusters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cluster in clusters or []:
        if not isinstance(cluster, dict):
            continue
        item = unify_cluster_record(cluster)
        cols = item.get("columns") or []
        col_count = len(cols) if isinstance(cols, list) else None
        item["domain_distribution"] = normalize_domain_distribution(
            item.get("domain_distribution"),
            fallback_domain=item.get("domain"),
            column_count=col_count,
        )
        out.append(item)
    return out
