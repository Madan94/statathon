"""Phase 7 — assemble a semantic schema blueprint from pipeline outputs (Neo4j-agnostic JSON)."""
from __future__ import annotations

from typing import Any


# Embedding prototype keys from DatasetContextInferencer → static ontology slug in mospi_ontology.json.
PIPELINE_DATASET_CTX_TO_STATIC: dict[str, str] = {
    "census": "census",
    "health_survey": "health",
    "labor": "labor",
    "education_statistics": "education",
    "agriculture": "agriculture",
    "economic_survey": "labor",
    "infrastructure": "census",
    "socioeconomic": "census",
    "survey_metadata": "census",
}


def build_schema_blueprint(
    *,
    dataset_metadata: dict[str, Any],
    inferred_dataset_context: dict[str, Any],
    profiling_dataset_profile: dict[str, Any],
    column_profiles: dict[str, Any],
    static_domains: dict[str, Any],
    semantic_mapping: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    schema_graph: dict[str, Any],
    priority_dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Single JSON blob suited for frontend graph/cluster/domain views."""
    instype = inferred_dataset_context or {}
    raw_type = str(instype.get("dataset_type") or "").strip()
    fused_static = PIPELINE_DATASET_CTX_TO_STATIC.get(raw_type)

    rollup_scores = profiling_dataset_profile.get("static_macro_type_scores") or {}
    rollup_best = profiling_dataset_profile.get("static_macro_type_best_hint")

    return {
        "dataset": {
            "filename": dataset_metadata.get("filename"),
            "object_key": dataset_metadata.get("object_key"),
            "storage_path_present": bool(dataset_metadata.get("storage_path")),
            "column_names": dataset_metadata.get("columns"),
            "embedding_inferred_dataset_type": raw_type or None,
            "static_macro_type_aligned": fused_static,
            "static_macro_type_rollup_best": rollup_best,
            "static_macro_type_rollup_scores": rollup_scores,
        },
        "rollups": {
            "dataset_profile": profiling_dataset_profile,
        },
        "domains": list((instype.get("domain_scores") or {}).keys()),
        "subdomains_notice": (
            "subdomains keyed by ontology; see static_domains_taxonomy.snapshot keys"
            if static_domains
            else None
        ),
        "columns": semantic_mapping,
        "column_profiles": column_profiles,
        "clusters": clusters,
        "graph_edges": schema_graph.get("edges") or [],
        "graph_nodes": schema_graph.get("nodes") or [],
        "relationships": priority_dependencies,
        "ontology": {
            "version": static_domains.get("version") if isinstance(static_domains, dict) else None,
            "dataset_types": list((static_domains or {}).get("dataset_types", {}).keys())
            if isinstance(static_domains, dict)
            else [],
        },
    }
