"""Execute `SemanticPipeline` with repo-root resolved embedding cache."""
from __future__ import annotations

from pipelines.model_path import ensure_paths, repo_root

ensure_paths()


def run_semantic_pipeline(
    columns: list[str],
    column_enrichment: dict[str, str] | None = None,
    dataset_domain: str | None = None,
    column_profiles: dict | None = None,
) -> dict:
    from semantic_mapping.semantic_pipeline import SemanticPipeline

    pipeline = SemanticPipeline()
    return pipeline.run(
        columns,
        column_enrichment=column_enrichment,
        dataset_domain=dataset_domain,
        column_profiles=column_profiles,
    )
