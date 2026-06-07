"""Fast, table-scoped reads for wizard step endpoints (no full checkpoint / phase3 rebuild)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, load_only

from analysis_state.cluster_utils import normalize_domain_distribution
from database.models import (
    DatasetContextRecord,
    DatasetIntelligenceRecord,
    PriorityDependency,
    SchemaGraphEdge,
    SemanticCluster,
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

    static_domains = summary.get("static_domains") or {}
    if not domain_registry and static_domains:
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
        clusters.append(
            {
                "cluster_id": c.cluster_name,
                "domain": c.semantic_domain,
                "support_score": c.support_score,
                "support": meta.get("support"),
                "columns": meta.get("columns"),
                "domain_distribution": normalize_domain_distribution(
                    meta.get("domain_distribution"),
                    fallback_domain=c.semantic_domain,
                    column_count=len(meta.get("columns") or []),
                ),
            }
        )
    return {"meta": {"analysis_id": analysis_id}, "clusters": clusters}


def build_graph_response(db: Session, analysis_id: int) -> dict[str, Any]:
    edges_db = (
        db.query(SchemaGraphEdge)
        .options(
            load_only(
                SchemaGraphEdge.source_column,
                SchemaGraphEdge.target_column,
                SchemaGraphEdge.edge_weight,
                SchemaGraphEdge.relationship_type,
                SchemaGraphEdge.semantic_reason,
            )
        )
        .filter(SchemaGraphEdge.analysis_id == analysis_id)
        .all()
    )
    edge_list: list[dict[str, Any]] = []
    nodes_set: set[str] = set()
    for e in edges_db:
        nodes_set.add(e.source_column)
        nodes_set.add(e.target_column)
        edge_list.append(
            {
                "source": e.source_column,
                "target": e.target_column,
                "weight": e.edge_weight,
                "relationship_type": e.relationship_type,
                "semantic_reason": e.semantic_reason,
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
        "nodes": [{"name": n} for n in sorted(nodes_set)],
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
