"""Fast, table-scoped reads for wizard step endpoints (no full checkpoint / phase3 rebuild)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, load_only

from analysis_state.cluster_utils import cluster_from_db_row, normalize_domain_distribution
from analysis_state.schema_graph_utils import enrich_schema_graph_edges
from database.models import (
    DatasetContextRecord,
    DatasetIntelligenceRecord,
    PriorityDependency,
    SchemaGraphEdge,
    SemanticCluster,
    SemanticProfile,
)
from services.analysis_query import get_analysis_meta, load_checkpoint_json_key


def _context_row(db: Session, analysis_id: int) -> DatasetContextRecord | None:
    return (
        db.query(DatasetContextRecord)
        .options(
            load_only(
                DatasetContextRecord.inferred_context,
                DatasetContextRecord.domain_scores,
                DatasetContextRecord.semantic_summary,
            )
        )
        .filter(DatasetContextRecord.analysis_id == analysis_id)
        .first()
    )


def _semantic_summary(ctx: DatasetContextRecord | None) -> dict[str, Any]:
    if not ctx:
        return {}
    summary = ctx.semantic_summary
    return summary if isinstance(summary, dict) else {}


def _dataset_context(ctx: DatasetContextRecord | None) -> dict[str, Any]:
    if not ctx:
        return {}
    out: dict[str, Any] = {
        "dataset_type": ctx.inferred_context,
        "domain_scores": ctx.domain_scores or {},
    }
    hint = _semantic_summary(ctx).get("ontology_macro_type_best_hint")
    if hint:
        out["ontology_macro_type_best_hint"] = hint
    return out


def _effective_schema(db: Session, analysis_id: int) -> dict[str, Any] | list[str] | None:
    meta = get_analysis_meta(db, analysis_id)
    if meta and isinstance(meta.config, dict):
        schema = meta.config.get("normalized_schema")
        if schema:
            return schema
    return load_checkpoint_json_key(db, analysis_id, "effective_schema")


_UNIVERSAL_DOMAIN_DEFAULTS = [
    "identifier",
    "survey_metadata",
    "geography",
    "demographic",
    "household",
    "uncorrelated_metadata",
]


def _coerce_domain_registry_for_ui(raw: dict[str, Any], archetype: str) -> dict[str, Any]:
    """Normalize V2 unified ``domains`` map or legacy registry into step-3 UI shape."""
    if raw.get("static_ontology") or raw.get("dynamic_domains") is not None:
        if not raw.get("active_archetype"):
            raw = {**raw, "active_archetype": archetype}
        return raw

    static_names: list[str] = []
    dynamic_domains: dict[str, Any] = {}
    universal: list[str] = []

    for name, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        domain_type = str(meta.get("domain_type") or "static").lower()
        if domain_type == "dynamic":
            dynamic_domains[name] = {
                "members": meta.get("members") or meta.get("columns") or [],
                "cohesion": meta.get("cohesion"),
                "description": meta.get("description") or meta.get("definition") or "",
            }
        elif domain_type == "universal":
            universal.append(name)
        else:
            static_names.append(name)

    if not static_names and not dynamic_domains and not universal:
        return {}

    return {
        "active_archetype": archetype,
        "universal_domains": universal or list(_UNIVERSAL_DOMAIN_DEFAULTS),
        "static_ontology": {
            archetype: {
                "label": archetype.replace("_", " ").title(),
                "domains": static_names,
                "keywords_sample": {},
            }
        },
        "dynamic_domains": dynamic_domains,
    }


def build_domains_response(db: Session, analysis_id: int) -> dict[str, Any]:
    ctx = _context_row(db, analysis_id)
    summary = _semantic_summary(ctx)
    ctx_payload = _dataset_context(ctx)

    archetype = (
        ctx_payload.get("dataset_type")
        or ctx_payload.get("ontology_macro_type_best_hint")
        or "unknown"
    )
    ontology_macro = ctx_payload.get("ontology_macro_type_best_hint")

    domain_registry = load_checkpoint_json_key(db, analysis_id, "domain_registry") or {}
    if not isinstance(domain_registry, dict):
        domain_registry = {}

    coerced = _coerce_domain_registry_for_ui(domain_registry, archetype)
    if coerced:
        domain_registry = coerced

    static_domains = summary.get("static_domains") or {}
    if not domain_registry.get("static_ontology") and static_domains:
        archetype_entry = static_domains.get(archetype) or static_domains.get("dataset_types", {}).get(
            archetype, {}
        )
        subdomains: dict[str, dict[str, Any]] = {}
        for k, v in (archetype_entry.get("subdomains") or {}).items():
            subdomains[k] = {"description": f"{k} domain for {archetype}", "keywords": list(v or [])[:8]}
        domain_registry = {
            "active_archetype": archetype,
            "universal_domains": [
                "identifier",
                "survey_metadata",
                "geography",
                "demographic",
                "household",
                "uncorrelated_metadata",
            ],
            "static_ontology": {
                archetype: {
                    "label": archetype_entry.get("label", archetype),
                    "domains": list(subdomains.keys()),
                    "keywords_sample": {k: v["keywords"] for k, v in subdomains.items()},
                }
            },
            "dynamic_domains": {},
        }

    static_taxonomy: dict[str, Any] = {}
    for tier_name, tier_data in (domain_registry.get("static_ontology") or {}).items():
        for dom in tier_data.get("domains") or []:
            kws = (tier_data.get("keywords_sample") or {}).get(dom, [])
            static_taxonomy[dom] = {"description": f"{dom} — {tier_name} dataset domain", "keywords": kws}
    for dom in domain_registry.get("universal_domains") or []:
        static_taxonomy[dom] = {"description": f"Universal: {dom}", "keywords": []}

    return {
        "meta": {"analysis_id": analysis_id},
        "dataset_context": ctx_payload,
        "domain_registry": domain_registry,
        "static_domains_taxonomy": static_taxonomy,
        "ontology_macro_type_best_hint": ontology_macro or archetype,
        "effective_schema": _effective_schema(db, analysis_id),
    }


def build_clusters_response(db: Session, analysis_id: int) -> dict[str, Any]:
    rows = (
        db.query(SemanticCluster)
        .options(
            load_only(
                SemanticCluster.cluster_name,
                SemanticCluster.semantic_domain,
                SemanticCluster.support_score,
                SemanticCluster.cluster_metadata,
            )
        )
        .filter(SemanticCluster.analysis_id == analysis_id)
        .all()
    )
    clusters = []
    for c in rows:
        meta = c.cluster_metadata or {}
        unified = cluster_from_db_row(
            c.cluster_name,
            c.semantic_domain,
            c.support_score,
            meta if isinstance(meta, dict) else {},
        )
        unified["domain_distribution"] = normalize_domain_distribution(
            unified.get("domain_distribution"),
            fallback_domain=unified.get("domain"),
            column_count=len(unified.get("columns") or []),
        )
        clusters.append(unified)
    return {"meta": {"analysis_id": analysis_id}, "clusters": clusters}


def build_graph_response(db: Session, analysis_id: int) -> dict[str, Any]:
    profiles = (
        db.query(SemanticProfile)
        .options(load_only(SemanticProfile.column_name, SemanticProfile.semantic_domain))
        .filter(SemanticProfile.analysis_id == analysis_id)
        .all()
    )
    domain_map = {str(p.column_name): str(p.semantic_domain) for p in profiles if p.column_name and p.semantic_domain}

    checkpoint_graph = load_checkpoint_json_key(db, analysis_id, "schema_graph")
    checkpoint_edges = (
        checkpoint_graph.get("edges")
        if isinstance(checkpoint_graph, dict) and isinstance(checkpoint_graph.get("edges"), list)
        else None
    )

    edges_db = (
        db.query(SchemaGraphEdge)
        .options(
            load_only(
                SchemaGraphEdge.source_column,
                SchemaGraphEdge.target_column,
                SchemaGraphEdge.edge_weight,
                SchemaGraphEdge.relationship_type,
                SchemaGraphEdge.owl_type,
                SchemaGraphEdge.source_domain,
                SchemaGraphEdge.target_domain,
                SchemaGraphEdge.semantic_reason,
            )
        )
        .filter(SchemaGraphEdge.analysis_id == analysis_id)
        .all()
    )
    edge_list: list[dict[str, Any]] = []
    nodes_set: set[str] = set()
    raw_edges: list[dict[str, Any]] = []
    for e in edges_db:
        nodes_set.add(e.source_column)
        nodes_set.add(e.target_column)
        raw_edges.append(
            {
                "source": e.source_column,
                "target": e.target_column,
                "weight": e.edge_weight,
                "relationship_type": e.relationship_type,
                "semantic_reason": e.semantic_reason,
                "owl_type": e.owl_type,
                "source_domain": e.source_domain,
                "target_domain": e.target_domain,
            }
        )
    edge_list = enrich_schema_graph_edges(
        raw_edges,
        domain_map=domain_map,
        checkpoint_edges=checkpoint_edges,
    )

    checkpoint_nodes_by_name: dict[str, dict[str, Any]] = {}
    if isinstance(checkpoint_graph, dict):
        for node in checkpoint_graph.get("nodes") or []:
            if isinstance(node, dict) and node.get("name"):
                checkpoint_nodes_by_name[str(node["name"])] = node

    graph_nodes = []
    for name in sorted(nodes_set):
        cp = checkpoint_nodes_by_name.get(name, {})
        graph_nodes.append(
            {
                "name": name,
                "domain": cp.get("domain") or domain_map.get(name),
                "cluster": cp.get("cluster"),
            }
        )

    prio_db = (
        db.query(PriorityDependency)
        .options(
            load_only(
                PriorityDependency.source_column,
                PriorityDependency.dependent_column,
                PriorityDependency.influence_score,
                PriorityDependency.dependency_reason,
                PriorityDependency.signal_payload,
            )
        )
        .filter(PriorityDependency.analysis_id == analysis_id)
        .all()
    )
    priority_flat: list[dict[str, Any]] = []
    for row in prio_db:
        priority_flat.append(
            {
                "source_column": row.source_column,
                "dependent_column": row.dependent_column,
                "influence_score": row.influence_score,
                "dependency_reason": row.dependency_reason,
                **(row.signal_payload or {}),
            }
        )

    summary = _semantic_summary(_context_row(db, analysis_id))
    return {
        "meta": {"analysis_id": analysis_id},
        "nodes": graph_nodes,
        "edges": edge_list,
        "priority_dependencies": priority_flat,
        "dataset_metadata": summary.get("dataset_metadata") or {},
    }


def build_knowledge_graph_response(db: Session, analysis_id: int) -> dict[str, Any]:
    summary = _semantic_summary(_context_row(db, analysis_id))
    kg = summary.get("knowledge_graph")
    return {
        "meta": {"analysis_id": analysis_id},
        "knowledge_graph": kg if isinstance(kg, dict) else {},
    }


def build_summary_response(db: Session, analysis_id: int) -> dict[str, Any]:
    ctx = _context_row(db, analysis_id)
    summary = _semantic_summary(ctx)
    profiling = summary.get("profiling_summary") or {}
    column_profiles = summary.get("column_profiles") or profiling.get("column_profiles") or {}
    dataset_profile = summary.get("dataset_profile") or profiling.get("dataset_profile")

    if not dataset_profile:
        intel = (
            db.query(DatasetIntelligenceRecord)
            .options(load_only(DatasetIntelligenceRecord.rollup_json))
            .filter(DatasetIntelligenceRecord.analysis_id == analysis_id)
            .first()
        )
        if intel:
            dataset_profile = intel.rollup_json

    meta = summary.get("dataset_metadata") or {}
    return {
        "meta": {"analysis_id": analysis_id},
        "dataset_context": _dataset_context(ctx),
        "dataset_profile": dataset_profile or {},
        "dataset_name": meta.get("filename") if isinstance(meta, dict) else None,
        "column_profiles_keys": sorted(column_profiles.keys()) if isinstance(column_profiles, dict) else [],
        "profiling_summary": profiling,
        "embedding_cache_refs": load_checkpoint_json_key(db, analysis_id, "embedding_cache_refs"),
    }
