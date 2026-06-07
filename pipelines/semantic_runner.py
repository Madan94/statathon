"""Execute semantic mapping — V2 production pipeline (Gemini + Groq fallback)."""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from pipelines.model_path import ensure_paths

ensure_paths()


def run_semantic_pipeline(
    columns: list[str],
    column_enrichment: dict[str, str] | None = None,
    dataset_domain: str | None = None,
    column_profiles: dict | None = None,
    *,
    df: pd.DataFrame | None = None,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    filename: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    """Run SemanticPipelineV2 when a DataFrame is available (default)."""
    _ = column_enrichment, column_profiles
    use_v2 = os.getenv("SEMANTIC_PIPELINE_V2", "1").lower() in ("1", "true", "yes")

    if use_v2 and df is not None:
        from semantic_mapping_v2 import SemanticPipelineV2
        from pipelines.semantic_v2_adapter import v2_to_legacy_bundle

        pipe = SemanticPipelineV2(use_llm=use_llm)
        v2 = pipe.analyze(
            df,
            dataset_id=dataset_id or filename or "dataset",
            dataset_name=dataset_name or filename or "dataset",
            file_name=filename,
            user_usecase=dataset_domain,
        )
        return v2_to_legacy_bundle(v2)

    from semantic_mapping.semantic_pipeline import SemanticPipeline

    pipeline = SemanticPipeline()
    return pipeline.run(
        columns,
        column_enrichment=column_enrichment,
        dataset_domain=dataset_domain,
        column_profiles=column_profiles,
    )
