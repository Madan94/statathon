"""Translate SemanticPipeline JSON bundle into AnalysisState."""
from __future__ import annotations

from typing import Any

from core.state import AnalysisState
from pipelines.schema_blueprint import build_schema_blueprint


def build_analysis_state(
    dataset_id: int,
    analysis_id: int,
    pipeline_out: dict[str, Any],
    profiling_summary: dict[str, Any],
    dataset_metadata: dict[str, Any],
    column_profiles: dict[str, Any] | None = None,
    dataset_profile: dict[str, Any] | None = None,
    static_domains: dict[str, Any] | None = None,
    schema_blueprint: dict[str, Any] | None = None,
    embedding_cache_refs: dict[str, Any] | None = None,
) -> AnalysisState:
    semantic_mapping = pipeline_out.get("semantic_mapping") or {}
    cluster_map = pipeline_out.get("column_cluster_map") or {}
    columns_payload: dict[str, Any] = {}
    for col, meta in semantic_mapping.items():
        entry = dict(meta) if isinstance(meta, dict) else {"value": meta}
        entry["cluster_id"] = cluster_map.get(col)
        columns_payload[col] = entry

    inferred_ctx = pipeline_out.get("dataset_context") or {}
    cmap = dict(inferred_ctx) if isinstance(inferred_ctx, dict) else {}

    rollup = dataset_profile or {}
    best_static = rollup.get("static_macro_type_best_hint") if rollup else None
    if isinstance(cmap, dict) and best_static and isinstance(best_static, str):
        cmap.setdefault("ontology_macro_type_best_hint", best_static)

    flat_mapping = [{"column": col, **(v if isinstance(v, dict) else {"value": v})} for col, v in columns_payload.items()]
    prio_raw = pipeline_out.get("priority_dependencies") or {}
    flat_prio: list[dict[str, Any]] = []
    if isinstance(prio_raw, dict):
        for dependent_column, influencers in prio_raw.items():
            if not isinstance(influencers, list):
                continue
            for inf in influencers:
                if not isinstance(inf, dict):
                    continue
                src = inf.get("column") or inf.get("source_column")
                if not src:
                    continue
                flat_prio.append(
                    {
                        "source_column": src,
                        "dependent_column": dependent_column,
                        "influence_score": inf.get("score") or inf.get("influence_score"),
                        "dependency_reason": inf.get("dependency_reason"),
                    }
                )

    blueprint = schema_blueprint
    if blueprint is None:
        blueprint = build_schema_blueprint(
            dataset_metadata=dataset_metadata,
            inferred_dataset_context=cmap,
            profiling_dataset_profile=rollup,
            column_profiles=column_profiles or {},
            static_domains=static_domains or {},
            semantic_mapping=flat_mapping,
            clusters=pipeline_out.get("clusters") or [],
            schema_graph=pipeline_out.get("schema_graph") or {},
            priority_dependencies=flat_prio,
        )

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
        column_profiles=column_profiles or {},
        dataset_profile=rollup,
        static_domains=static_domains or {},
        schema_blueprint=blueprint,
        inferred_dataset_context=cmap,
        embedding_cache_refs=embedding_cache_refs or {"vector_store": "model/storage/vector_cache"},
    )
