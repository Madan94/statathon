from pipelines.model_path import ensure_paths

ensure_paths()

from core.ingestion import dataframe_for_uploaded_dataset, infer_schema, health_summary
from core.rule_validator import normalize_schema
from core.outlier_engine import zscore_outliers, iqr_outliers
from core.imputation_engine import knn_impute_numeric
from reports.ingestion_reporter import write_ingestion_report
from reports.math_vault import write_math_vault
from reports.narrative_generator import narrative_from_stats
from reports.tamper_proof import write_tamper_proof_pdf
from pipelines.semantic_runner import run_semantic_pipeline
from pipelines.semantic_adapter import build_analysis_state
from graph.neo4j_sync import try_sync_analysis_to_neo4j
from profiling import (
    build_dataset_intelligence_profiles,
    column_profile_embedding_snippet,
    load_default_ontology,
)
from services.semantic_persistence_service import SemanticPersistenceService
from repositories.dataset_repository import DatasetRepository
from database.models import Analysis

import os

import pandas as pd
from sqlalchemy.orm import Session


def run_pipeline(
    *,
    storage_path: str | None,
    filename: str,
    object_key: str | None,
    report_dir: str,
    analysis_id: int,
    dataset_id: int,
    db: Session,
    object_store=None,
) -> dict:
    df = dataframe_for_uploaded_dataset(
        storage_path, object_key, filename, object_store
    )
    schema = infer_schema(df)
    health = health_summary(df)

    DatasetRepository(db).update_dimensions(dataset_id, len(df), len(df.columns), health)

    ontology = load_default_ontology()
    ontology_dict = ontology if isinstance(ontology, dict) else {}
    column_profiles, dataset_profile = build_dataset_intelligence_profiles(
        df, ontology_dict if ontology_dict else None
    )

    enrichment: dict[str, str] = {}
    for c in df.columns:
        snippet = column_profile_embedding_snippet(column_profiles.get(str(c)))
        if snippet:
            enrichment[str(c)] = snippet

    semantic_bundle = run_semantic_pipeline(
        list(df.columns),
        column_enrichment=enrichment or None,
    )
    state = build_analysis_state(
        dataset_id=dataset_id,
        analysis_id=analysis_id,
        pipeline_out=semantic_bundle,
        profiling_summary={"health": health, "schema": schema},
        column_profiles=column_profiles,
        dataset_profile=dataset_profile,
        static_domains=ontology_dict,
        dataset_metadata={
            "storage_path": storage_path,
            "object_key": object_key,
            "filename": filename,
            "columns": list(df.columns),
        },
    )
    try_sync_analysis_to_neo4j(state)
    if isinstance(state.schema_blueprint, dict) and state.knowledge_graph:
        state.schema_blueprint = {
            **state.schema_blueprint,
            "neo4j_sync_summary": dict(state.knowledge_graph),
        }

    SemanticPersistenceService(db).persist_state(state)

    analysis_row = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if analysis_row:
        analysis_row.checkpoint = state.to_api_payload()

    db.flush()

    semantic_labels = {}
    for col in df.columns:
        meta = semantic_bundle.get("semantic_mapping", {}).get(col)
        if isinstance(meta, dict):
            semantic_labels[col] = meta.get("domain")

    df2 = normalize_schema(df, schema)
    outliers = {}
    for c in df2.columns:
        if schema.get(c) == "numeric":
            outliers[c] = {"zscore": zscore_outliers(df2[c]), "iqr": iqr_outliers(df2[c])}
    df3 = knn_impute_numeric(df2, list(df2.columns))
    stats = {c: float(df3[c].mean()) for c in df3.columns if pd.api.types.is_numeric_dtype(df3[c])}
    os.makedirs(report_dir, exist_ok=True)
    write_ingestion_report(os.path.join(report_dir, f"ingestion_{analysis_id}.json"), health, schema)
    write_math_vault(os.path.join(report_dir, f"vault_{analysis_id}.json"), stats)
    narrative = narrative_from_stats(stats)
    h = write_tamper_proof_pdf(
        os.path.join(report_dir, f"report_{analysis_id}.pdf"),
        f"Analysis {analysis_id}",
        narrative.split("; "),
        {"analysis_id": analysis_id},
    )
    return {
        "health": health,
        "semantic": semantic_labels,
        "semantic_intelligence": state.to_api_payload(),
        "outliers": outliers,
        "content_hash": h,
    }
