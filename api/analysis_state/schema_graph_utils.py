"""Helpers for schema graph edge OWL typing and API serialization."""
from __future__ import annotations

import re
from typing import Any

_SIMILARITY_RE = re.compile(r"similarity\s*(?:[=(:]\s*)?([0-9.]+)", re.IGNORECASE)
_CROSS_DOMAIN_RE = re.compile(
    r"Cross-domain linkage\s+([^\s<]+)\s+<->\s+([^\s;.]+)",
    re.IGNORECASE,
)


def edge_pair_key(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((source, target)))


def parse_domains_from_reason(semantic_reason: str | None) -> tuple[str | None, str | None]:
    if not semantic_reason:
        return None, None
    match = _CROSS_DOMAIN_RE.search(semantic_reason)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def parse_embedding_similarity(semantic_reason: str | None) -> float | None:
    if not semantic_reason:
        return None
    match = _SIMILARITY_RE.search(semantic_reason)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def infer_owl_type(
    relationship_type: str | None,
    *,
    source_domain: str | None = None,
    target_domain: str | None = None,
    semantic_reason: str | None = None,
) -> str:
    rel = (relationship_type or "").strip().lower()
    sd = (source_domain or "").strip()
    td = (target_domain or "").strip()
    if not sd or not td:
        parsed_sd, parsed_td = parse_domains_from_reason(semantic_reason)
        sd = sd or (parsed_sd or "").strip()
        td = td or (parsed_td or "").strip()

    if rel == "cross_domain_linkage":
        return "owl:ObjectProperty"
    if rel == "co_cluster_semantic":
        if sd and td and sd == td:
            return "owl:equivalentProperty"
        return "owl:ObjectProperty"
    if rel == "intra_domain_association":
        sim = parse_embedding_similarity(semantic_reason)
        if sim is not None and sim >= 0.55:
            return "rdfs:subPropertyOf"
        return "rdfs:seeAlso"
    if rel in ("semantic", "related", ""):
        return "owl:ObjectProperty"
    return "owl:ObjectProperty"


def serialize_schema_graph_edge(
    *,
    source: str,
    target: str,
    weight: float,
    relationship_type: str | None = None,
    semantic_reason: str | None = None,
    owl_type: str | None = None,
    owl_label: str | None = None,
    source_domain: str | None = None,
    target_domain: str | None = None,
) -> dict[str, Any]:
    resolved_owl = owl_type or infer_owl_type(
        relationship_type,
        source_domain=source_domain,
        target_domain=target_domain,
        semantic_reason=semantic_reason,
    )
    payload: dict[str, Any] = {
        "source": source,
        "target": target,
        "weight": weight,
        "relationship_type": relationship_type,
        "semantic_reason": semantic_reason,
        "owl_type": resolved_owl,
    }
    if owl_label:
        payload["owl_label"] = owl_label
    if source_domain:
        payload["source_domain"] = source_domain
    if target_domain:
        payload["target_domain"] = target_domain
    return payload


def merge_checkpoint_schema_graph_edges(
    edges: list[dict[str, Any]],
    checkpoint_edges: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not checkpoint_edges:
        return edges

    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in checkpoint_edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        if not src or not tgt:
            continue
        by_pair[edge_pair_key(str(src), str(tgt))] = edge

    merged: list[dict[str, Any]] = []
    for edge in edges:
        cp = by_pair.get(edge_pair_key(str(edge["source"]), str(edge["target"])))
        if not cp:
            merged.append(edge)
            continue
        enriched = dict(edge)
        for field in (
            "owl_type",
            "owl_label",
            "source_domain",
            "target_domain",
            "embedding_similarity",
            "cluster_adjacency",
        ):
            if cp.get(field) is not None and enriched.get(field) in (None, "", 0):
                enriched[field] = cp[field]
        if cp.get("owl_type"):
            enriched["owl_type"] = cp["owl_type"]
        merged.append(enriched)
    return merged


def enrich_schema_graph_edges(
    edges: list[dict[str, Any]],
    *,
    domain_map: dict[str, str] | None = None,
    checkpoint_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    domain_lookup = domain_map or {}
    serialized: list[dict[str, Any]] = []
    for edge in edges:
        src = str(edge.get("source") or edge.get("source_column") or "")
        tgt = str(edge.get("target") or edge.get("target_column") or "")
        if not src or not tgt:
            continue
        sd = edge.get("source_domain") or domain_lookup.get(src)
        td = edge.get("target_domain") or domain_lookup.get(tgt)
        if not sd or not td:
            parsed_sd, parsed_td = parse_domains_from_reason(edge.get("semantic_reason"))
            sd = sd or parsed_sd
            td = td or parsed_td
        weight = edge.get("weight", edge.get("edge_weight", 0.0))
        serialized.append(
            serialize_schema_graph_edge(
                source=src,
                target=tgt,
                weight=float(weight or 0.0),
                relationship_type=edge.get("relationship_type"),
                semantic_reason=edge.get("semantic_reason"),
                owl_type=edge.get("owl_type"),
                owl_label=edge.get("owl_label"),
                source_domain=sd,
                target_domain=td,
            )
        )
    return merge_checkpoint_schema_graph_edges(serialized, checkpoint_edges)
