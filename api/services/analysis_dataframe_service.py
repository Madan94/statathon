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


def load_snapshot_dataframe(db: Session, analysis_id: int, stage: str | None = None) -> pd.DataFrame | None:
    """Load the latest parquet snapshot for an analysis stage."""
    from database.models import DatasetLineageSnapshot

    stage_priority = ("imputed", "anomaly_reviewed", "validated", "original")
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


def load_analysis_dataframe(db: Session, analysis_id: int) -> tuple[pd.DataFrame, dict[str, str]]:
    an = get_analysis_meta(db, analysis_id)
    if not an:
        raise ValueError("Analysis not found")
    ds = db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")

    snap_df = load_snapshot_dataframe(db, analysis_id)
    if snap_df is not None:
        schema = infer_schema(snap_df)
        checkpoint = load_analysis_checkpoint(db, analysis_id) or {}
        rename_map = semantic_column_rename_map(checkpoint)
        applicable = {k: v for k, v in rename_map.items() if k in snap_df.columns}
        if applicable:
            snap_df = snap_df.rename(columns=applicable)
            schema = {rename_map.get(str(k), str(k)): v for k, v in schema.items()}
        return normalize_schema(snap_df, schema), schema

    store = try_build_default_store() if ds.object_key else None
    import os

    try:
        df = dataframe_for_uploaded_dataset(ds.storage_path, ds.object_key, ds.filename, store)
    except (FileNotFoundError, OSError):
        if ds.object_key and store:
            df = dataframe_for_uploaded_dataset(None, ds.object_key, ds.filename, store)
        else:
            raise
    schema = infer_schema(df)

    checkpoint = load_analysis_checkpoint(db, analysis_id) or {}
    rename_map = semantic_column_rename_map(checkpoint)
    applicable = {k: v for k, v in rename_map.items() if k in df.columns}
    if applicable:
        df = df.rename(columns=applicable)
        schema = {rename_map.get(str(k), str(k)): v for k, v in schema.items()}

    return normalize_schema(df, schema), schema
