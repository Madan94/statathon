"""Translate SemanticPipeline JSON bundle into AnalysisState."""
from __future__ import annotations

from typing import Any

from core.state import AnalysisState


def build_analysis_state(
    dataset_id: int,
    analysis_id: int,
    pipeline_out: dict[str, Any],
    profiling_summary: dict[str, Any],
    dataset_metadata: dict[str, Any],
    embedding_cache_refs: dict[str, Any] | None = None,
) -> AnalysisState:
    semantic_mapping = pipeline_out.get("semantic_mapping") or {}
    cluster_map = pipeline_out.get("column_cluster_map") or {}
    columns_payload: dict[str, Any] = {}
    for col, meta in semantic_mapping.items():
        entry = dict(meta) if isinstance(meta, dict) else {"value": meta}
        entry["cluster_id"] = cluster_map.get(col)
        columns_payload[col] = entry

    return AnalysisState(
        dataset_id=dataset_id,
        analysis_id=analysis_id,
        dataset_metadata=dataset_metadata,
        semantic_profile={"columns": columns_payload},
        semantic_clusters=pipeline_out.get("clusters") or [],
        schema_graph=pipeline_out.get("schema_graph") or {},
        dependency_graph=pipeline_out.get("priority_dependencies") or {},
        audit_logs=pipeline_out.get("audit_records") or [],
        profiling_summary=profiling_summary,
        inferred_dataset_context=pipeline_out.get("dataset_context") or {},
        embedding_cache_refs=embedding_cache_refs or {"vector_store": "model/storage/vector_cache"},
    )
