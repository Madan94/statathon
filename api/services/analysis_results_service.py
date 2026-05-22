"""Reconstruct GET /analysis/{id}/results payload from normalized tables."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from database.models import (
    Analysis,
    ColumnIntelligenceProfile,
    DatasetContextRecord,
    DatasetIntelligenceRecord,
    PriorityDependency,
    SchemaGraphEdge,
    SemanticCluster,
    SemanticProfile,
)


def build_semantic_results_from_db(db: Session, analysis_id: int) -> dict | None:
    profiles = (
        db.query(SemanticProfile)
        .filter(SemanticProfile.analysis_id == analysis_id)
        .order_by(SemanticProfile.column_name)
        .all()
    )
    if not profiles:
        return None

    semantic_mapping = []
    for p in profiles:
        entry = {
            "column": p.column_name,
            "domain": p.semantic_domain,
            "confidence": p.confidence,
            "cluster_id": p.cluster_id,
        }
        tags = p.contextual_tags or {}
        if isinstance(tags, dict):
            entry.update(tags)
        semantic_mapping.append(entry)

    clusters_db = db.query(SemanticCluster).filter(SemanticCluster.analysis_id == analysis_id).all()
    clusters = []
    for c in clusters_db:
        meta = c.cluster_metadata or {}
        clusters.append(
            {
                "cluster_id": c.cluster_name,
                "domain": c.semantic_domain,
                "support_score": c.support_score,
                "support": (meta or {}).get("support"),
                "columns": (meta or {}).get("columns"),
                "domain_distribution": (meta or {}).get("domain_distribution"),
            }
        )

    edges_db = db.query(SchemaGraphEdge).filter(SchemaGraphEdge.analysis_id == analysis_id).all()
    edge_list = []
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
    schema_graph = {
        "nodes": [{"name": n} for n in sorted(nodes_set)],
        "edges": edge_list,
    }

    prio_db = db.query(PriorityDependency).filter(PriorityDependency.analysis_id == analysis_id).all()
    priority_dependencies: dict[str, list[dict]] = {}
    for row in prio_db:
        priority_dependencies.setdefault(row.dependent_column, []).append(
            {
                "column": row.source_column,
                "score": row.influence_score,
                "dependency_reason": row.dependency_reason,
                **(row.signal_payload or {}),
            }
        )

    ctx_row = db.query(DatasetContextRecord).filter(DatasetContextRecord.analysis_id == analysis_id).first()
    dataset_context = {}
    semantic_summary = {}
    if ctx_row:
        dataset_context = {
            "dataset_type": ctx_row.inferred_context,
            "domain_scores": ctx_row.domain_scores or {},
        }
        semantic_summary = ctx_row.semantic_summary or {}

    profiling_summary = {}
    column_profiles_db: dict[str, Any] | None = None
    dataset_profile_db: dict[str, Any] | None = None
    static_domains_db = None
    schema_blueprint_db = None
    dataset_meta: dict[str, Any] | None = None
    knowledge_graph_db: dict[str, Any] = {}
    intel_ds = (
        db.query(DatasetIntelligenceRecord).filter(DatasetIntelligenceRecord.analysis_id == analysis_id).first()
    )
    intel_col_map = {
        r.column_name: r.profile_json
        for r in db.query(ColumnIntelligenceProfile)
        .filter(ColumnIntelligenceProfile.analysis_id == analysis_id)
        .order_by(ColumnIntelligenceProfile.column_name)
        .all()
    }

    if isinstance(semantic_summary, dict):
        profiling_summary = semantic_summary.get("profiling_summary") or {}
        column_profiles_db = semantic_summary.get("column_profiles") or profiling_summary.get(
            "column_profiles"
        )
        dataset_profile_db = semantic_summary.get("dataset_profile") or profiling_summary.get(
            "dataset_profile"
        )
        static_domains_db = semantic_summary.get("static_domains")
        schema_blueprint_db = semantic_summary.get("schema_blueprint")
        dataset_meta = semantic_summary.get("dataset_metadata")
        ontology_hint = semantic_summary.get("ontology_macro_type_best_hint")
        kg = semantic_summary.get("knowledge_graph")
        if isinstance(kg, dict):
            knowledge_graph_db = kg
        if ontology_hint:
            dataset_context = {
                **(dataset_context or {}),
                "ontology_macro_type_best_hint": ontology_hint,
            }

    if not dataset_profile_db and intel_ds:
        dataset_profile_db = intel_ds.rollup_json
    if not column_profiles_db and intel_col_map:
        column_profiles_db = intel_col_map

    return {
        "dataset_context": dataset_context,
        "semantic_mapping": semantic_mapping,
        "clusters": clusters,
        "schema_graph": schema_graph,
        "priority_dependencies": priority_dependencies,
        "profiling_summary": profiling_summary,
        "column_profiles": column_profiles_db or {},
        "dataset_profile": dataset_profile_db or {},
        "static_domains": static_domains_db or {},
        "schema_blueprint": schema_blueprint_db or {},
        "dataset_metadata": dataset_meta or {},
        "knowledge_graph": knowledge_graph_db,
    }


def resolve_semantic_analysis_payload(db: Session, analysis_id: int) -> dict | None:
    """Prefer JSON checkpoint blob; fallback to reconstructed relational semantics."""
    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        return None
    if isinstance(an.checkpoint, dict) and an.checkpoint:
        return an.checkpoint
    return build_semantic_results_from_db(db, analysis_id)
