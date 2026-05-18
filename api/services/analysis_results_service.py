"""Reconstruct GET /analysis/{id}/results payload from normalized tables."""
from __future__ import annotations

from sqlalchemy.orm import Session

from database.models import (
    DatasetContextRecord,
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
    if isinstance(semantic_summary, dict):
        profiling_summary = semantic_summary.get("profiling_summary") or {}

    return {
        "dataset_context": dataset_context,
        "semantic_mapping": semantic_mapping,
        "clusters": clusters,
        "schema_graph": schema_graph,
        "priority_dependencies": priority_dependencies,
        "profiling_summary": profiling_summary,
    }
