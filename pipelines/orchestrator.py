from pipelines.model_path import ensure_paths

ensure_paths()

from core.ingestion import dataframe_for_uploaded_dataset, infer_schema, health_summary
from core.json_safe import make_json_safe
from services.analysis_query import slim_checkpoint_payload
from core.rule_validator import normalize_schema
from reports.ingestion_reporter import write_ingestion_report
from reports.math_vault import write_math_vault
from reports.narrative_generator import narrative_from_stats
from reports.tamper_proof import write_tamper_proof_pdf
from pipelines.semantic_runner import run_semantic_pipeline
from pipelines.semantic_adapter import build_analysis_state
from pipelines.phase3_pipeline import run_phase3_intel
from graph.neo4j_sync import try_sync_analysis_to_neo4j
from profiling import (
    build_dataset_intelligence_profiles,
    column_profile_embedding_snippet,
    load_default_ontology,
)
from repositories.dataset_repository import DatasetRepository
from services.phase3_persistence_service import Phase3PersistenceService
from services.semantic_persistence_service import SemanticPersistenceService
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
        column_profiles=column_profiles,
        df=df,
        dataset_id=str(dataset_id),
        dataset_name=filename,
        filename=filename,
        dataset_domain=None,
    )

    # --- Adopt the normalized identity for the rest of the pipeline ----------
    # The semantic pipeline corrected/expanded every header into a canonical
    # name. Rename the DataFrame (and the schema/health/profiles derived from
    # it) so phase-3 (validation, z-score, IQR, missing) and persistence all
    # run on the normalized columns instead of the raw/cryptic ones. The raw
    # headers are preserved in semantic_bundle['column_normalization'].
    rename_map: dict[str, str] = {}
    for row in semantic_bundle.get("column_normalization") or []:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("original_name") or "")
        canon = str(row.get("canonical_name") or row.get("normalized_name") or "")
        if raw and canon and raw in df.columns and raw != canon:
            rename_map[raw] = canon
    if rename_map:
        df = df.rename(columns=rename_map)
        schema = {rename_map.get(str(k), str(k)): v for k, v in schema.items()}
        if isinstance(health, dict):
            for _hk in ("missing_per_column", "dtypes"):
                sub = health.get(_hk)
                if isinstance(sub, dict):
                    health[_hk] = {rename_map.get(str(k), str(k)): v for k, v in sub.items()}
        column_profiles = {
            rename_map.get(str(k), str(k)): v for k, v in (column_profiles or {}).items()
        }

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

    run_phase3_intel(df, schema, state)
    SemanticPersistenceService(db).persist_state(state)
    db.commit()
    Phase3PersistenceService(db).persist_state(state)
    db.commit()

    analysis_row = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if analysis_row:
        cp = slim_checkpoint_payload(make_json_safe(state.to_api_payload()))
        cp["raw_schema"] = [str(c) for c in df.columns]
        analysis_row.checkpoint = cp

    from services.normalization_service import NormalizationService

    NormalizationService(db).seed_from_analysis_payload(
        dataset_id=dataset_id,
        analysis_id=analysis_id,
        raw_columns=[str(c) for c in df.columns],
        payload=analysis_row.checkpoint if analysis_row and isinstance(analysis_row.checkpoint, dict) else state.to_api_payload(),
    )

    db.commit()

    semantic_labels = {}
    for col in df.columns:
        meta = semantic_bundle.get("semantic_mapping", {}).get(col)
        if isinstance(meta, dict):
            semantic_labels[col] = meta.get("domain")

    df2 = normalize_schema(df, schema)
    stats = {}
    for c in df2.columns:
        if pd.api.types.is_numeric_dtype(df2[c]):
            s = df2[c].dropna()
            if not s.empty:
                stats[c] = float(s.astype(float).mean())
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
        "content_hash": h,
    }
