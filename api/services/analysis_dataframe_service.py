"""Load analysis datasets with the same column identity as the ingestion pipeline."""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import dataframe_for_uploaded_dataset, infer_schema
from core.rule_validator import normalize_schema
from database.models import Dataset
from object_storage.object_store import try_build_default_store
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint


def semantic_column_rename_map(checkpoint: dict[str, Any]) -> dict[str, str]:
    """Map raw upload headers → canonical names used during phase-3 analysis."""
    rename: dict[str, str] = {}
    for row in checkpoint.get("column_normalization") or []:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("original_name") or "")
        canon = str(row.get("canonical_name") or row.get("normalized_name") or "")
        if raw and canon and raw != canon:
            rename[raw] = canon
    return rename


def column_identity_aliases(checkpoint: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, set[str]]:
    """Build alias groups for every column identity (raw, canonical, display)."""
    groups: dict[str, set[str]] = {}

    def _add(*names: str | None) -> None:
        clean = {str(n) for n in names if n}
        if not clean:
            return
        merged: set[str] = set()
        for name in clean:
            merged |= groups.get(name, {name})
        for name in merged:
            groups[name] = merged

    for row in checkpoint.get("column_normalization") or []:
        if not isinstance(row, dict):
            continue
        _add(
            row.get("original_name"),
            row.get("canonical_name"),
            row.get("normalized_name"),
        )

    cfg = config if isinstance(config, dict) else {}
    for row in cfg.get("user_normalization") or []:
        if not isinstance(row, dict):
            continue
        _add(row.get("original_name"), row.get("normalized_name"))

    return groups


def resolve_column_alias(
    column: str,
    alias_groups: dict[str, set[str]],
    df_columns: set[str] | None = None,
) -> str | None:
    """Pick the dataframe column name for a UI / canonical / display label."""
    candidates = alias_groups.get(column, {column})
    if df_columns:
        for name in candidates:
            if name in df_columns:
                return name
    return None


WORKING_STAGE_BY_PHASE: dict[str, str] = {
    "normalization": "original",
    "validation": "normalized",
    "anomaly": "validated",
    "imputation": "anomaly_reviewed",
    "review": "imputed",
}

_STAGE_FALLBACKS: dict[str, tuple[str, ...]] = {
    "normalized": ("original",),
    "validated": ("normalized", "original"),
    "anomaly_reviewed": ("validated", "normalized", "original"),
    "imputed": ("anomaly_reviewed", "validated", "normalized", "original"),
}


def load_snapshot_dataframe(db: Session, analysis_id: int, stage: str | None = None) -> pd.DataFrame | None:
    """Load the latest parquet snapshot for an analysis stage."""
    from database.models import DatasetLineageSnapshot

    stage_priority = ("imputed", "anomaly_reviewed", "validated", "normalized", "original", "final")
    stages = [stage] if stage else list(stage_priority)
    for st in stages:
        snap = (
            db.query(DatasetLineageSnapshot)
            .filter(
                DatasetLineageSnapshot.analysis_id == analysis_id,
                DatasetLineageSnapshot.stage == st,
            )
            .order_by(DatasetLineageSnapshot.version.desc())
            .first()
        )
        if snap and snap.storage_path:
            try:
                return pd.read_parquet(snap.storage_path)
            except Exception:
                if snap.object_key:
                    store = try_build_default_store()
                    if store:
                        try:
                            import io

                            body = store.download_object_body(snap.object_key)
                            return pd.read_parquet(io.BytesIO(body))
                        except Exception:
                            pass
    return None


def load_phase_dataframe(
    db: Session,
    analysis_id: int,
    phase: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the working dataset input for a pipeline phase (never a later stage)."""
    stage = WORKING_STAGE_BY_PHASE.get(phase, "imputed")
    snap_df = load_snapshot_dataframe(db, analysis_id, stage)
    if snap_df is None:
        for fallback in _STAGE_FALLBACKS.get(stage, ()):
            snap_df = load_snapshot_dataframe(db, analysis_id, fallback)
            if snap_df is not None:
                break
    if snap_df is None:
        from services.normalization_transform_service import load_working_dataframe as build_working

        snap_df, _, _ = build_working(db, analysis_id, apply_user_norm=True)
    schema = infer_schema(snap_df)
    return normalize_schema(snap_df, schema), schema


def load_analysis_dataframe(db: Session, analysis_id: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the canonical approved processed dataset for reporting when available."""
    from review.dataset_snapshot_service import resolve_processed_stage

    stage = resolve_processed_stage(db, analysis_id)
    snap_df = load_snapshot_dataframe(db, analysis_id, stage)
    if snap_df is None:
        snap_df = load_snapshot_dataframe(db, analysis_id, None)
    if snap_df is None:
        from services.normalization_transform_service import load_working_dataframe as build_working

        snap_df, _, _ = build_working(db, analysis_id, apply_user_norm=True)
    schema = infer_schema(snap_df)
    return normalize_schema(snap_df, schema), schema
