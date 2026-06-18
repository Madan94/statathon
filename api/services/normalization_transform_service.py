"""Apply user-approved normalization to working dataframes and persist snapshots."""
from __future__ import annotations

import hashlib
import os
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import dataframe_for_uploaded_dataset, infer_schema
from core.multiplier_column import (
    detach_multiplier_columns,
    filter_rename_map,
    find_multiplier_columns,
    is_multiplier_column,
)
from core.rule_validator import normalize_schema
from database.models import Dataset
from object_storage.object_store import try_build_default_store
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint


def dataframe_checksum(df: pd.DataFrame) -> str:
    """Stable checksum for lineage snapshot metadata."""
    payload = df.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_raw_upload_dataframe(db: Session, analysis_id: int) -> tuple[pd.DataFrame, Dataset, Any]:
    an = get_analysis_meta(db, analysis_id)
    if not an:
        raise ValueError("Analysis not found")
    ds = db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")
    store = try_build_default_store() if ds.object_key else None
    try:
        df = dataframe_for_uploaded_dataset(ds.storage_path, ds.object_key, ds.filename, store)
    except (FileNotFoundError, OSError):
        if ds.object_key and store:
            df = dataframe_for_uploaded_dataset(None, ds.object_key, ds.filename, store)
        else:
            raise
    schema = infer_schema(df)
    mult_cols = set(find_multiplier_columns(df))
    work_schema = {k: v for k, v in schema.items() if k not in mult_cols}
    return normalize_schema(df, work_schema), ds, store


def apply_pipeline_column_rename(df: pd.DataFrame, checkpoint: dict[str, Any]) -> pd.DataFrame:
    """Rename upload headers to pipeline canonical names (pre-user normalization)."""
    rename: dict[str, str] = {}
    for row in checkpoint.get("column_normalization") or []:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("original_name") or "")
        canon = str(row.get("canonical_name") or row.get("normalized_name") or "")
        if raw and canon and raw != canon and raw in df.columns:
            rename[raw] = canon
    rename = filter_rename_map(rename)
    if rename:
        return df.rename(columns=rename)
    return df


def apply_user_normalization(
    df: pd.DataFrame,
    column_records: list[Any],
) -> pd.DataFrame:
    """Rename, drop deleted, and drop excluded columns from the working dataframe."""
    out = df.copy()
    rename_map: dict[str, str] = {}
    drop_cols: set[str] = set()

    for col in column_records:
        physical = str(getattr(col, "name", "") or "")
        display = str(getattr(col, "normalized_name", None) or physical)
        is_deleted = bool(getattr(col, "is_deleted", False))
        is_excluded = bool(getattr(col, "is_excluded", False))
        is_active = getattr(col, "is_active", True)
        if not physical:
            continue
        if is_multiplier_column(physical):
            continue
        if is_deleted or is_excluded or is_active is False:
            if physical in out.columns:
                drop_cols.add(physical)
            continue
        if display and display != physical and physical in out.columns:
            rename_map[physical] = display

    if rename_map:
        out = out.rename(columns=rename_map)
        drop_cols = {rename_map.get(c, c) for c in drop_cols}

    if drop_cols:
        out = out.drop(columns=[c for c in drop_cols if c in out.columns], errors="ignore")
    return out


def build_column_resolver(
    df: pd.DataFrame,
    ui_to_physical: dict[str, str],
) -> Any:
    """Return callable mapping UI/canonical column labels to dataframe column names."""

    def resolve(name: str) -> str | None:
        if not name:
            return None
        physical = ui_to_physical.get(name, name)
        if physical in df.columns:
            return physical
        if name in df.columns:
            return name
        for candidate in ui_to_physical.get(name, {name}):
            if isinstance(candidate, str) and candidate in df.columns:
                return candidate
        return None

    return resolve


def build_ui_to_physical_maps(column_records: list[Any]) -> tuple[dict[str, str], dict[str, str]]:
    ui_to_physical: dict[str, str] = {}
    physical_to_ui: dict[str, str] = {}
    for col in column_records:
        physical = str(getattr(col, "name", "") or "")
        display = str(getattr(col, "normalized_name", None) or physical)
        if not physical:
            continue
        ui_to_physical[display] = physical
        ui_to_physical[physical] = physical
        physical_to_ui[physical] = display
    return ui_to_physical, physical_to_ui


def load_working_dataframe(
    db: Session,
    analysis_id: int,
    *,
    apply_user_norm: bool = True,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    """Load upload + pipeline rename + optional user normalization."""
    from services.normalization_service import NormalizationService

    df, _, _ = load_raw_upload_dataframe(db, analysis_id)
    checkpoint = load_analysis_checkpoint(db, analysis_id) or {}
    df, _ = detach_multiplier_columns(df)
    df = apply_pipeline_column_rename(df, checkpoint)

    norm = NormalizationService(db)
    records = norm._ensure_columns_seeded(analysis_id)
    ui_to_physical, physical_to_ui = build_ui_to_physical_maps(records)
    if apply_user_norm and records:
        df = apply_user_normalization(df, records)
        ui_to_physical, physical_to_ui = build_ui_to_physical_maps(records)
    return df, ui_to_physical, physical_to_ui


def ensure_original_snapshot(db: Session, analysis_id: int) -> dict[str, Any] | None:
    """Persist immutable upload snapshot once; return metadata if newly written."""
    from services.apply_service import _snapshot_exists

    if _snapshot_exists(db, analysis_id, "original"):
        return None
    return persist_original_snapshot(db, analysis_id)


def persist_original_snapshot(db: Session, analysis_id: int) -> dict[str, Any]:
    from services.apply_service import _persist_snapshot

    df, ds, store = load_raw_upload_dataframe(db, analysis_id)
    return _persist_snapshot(
        db,
        analysis_id=analysis_id,
        dataset_id=ds.id,
        stage="original",
        df=df,
        store=store,
        meta={"source": ds.filename, "checksum": dataframe_checksum(df), "phase": "v1_upload"},
    )


def persist_normalized_snapshot(db: Session, analysis_id: int) -> dict[str, Any]:
    from services.apply_service import _persist_snapshot
    from services.analysis_dataframe_service import load_snapshot_dataframe
    from services.normalization_service import NormalizationService

    ensure_original_snapshot(db, analysis_id)
    df = load_snapshot_dataframe(db, analysis_id, "original")
    if df is not None:
        an = get_analysis_meta(db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        ds = db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
        if not ds:
            raise ValueError("Dataset not found")
        store = try_build_default_store() if ds.object_key else None
    else:
        df, ds, store = load_raw_upload_dataframe(db, analysis_id)

    checkpoint = load_analysis_checkpoint(db, analysis_id) or {}
    df, _ = detach_multiplier_columns(df)
    df = apply_pipeline_column_rename(df, checkpoint)
    records = NormalizationService(db)._ensure_columns_seeded(analysis_id)
    df = apply_user_normalization(df, records)

    return _persist_snapshot(
        db,
        analysis_id=analysis_id,
        dataset_id=ds.id,
        stage="normalized",
        df=df,
        store=store,
        meta={
            "checksum": dataframe_checksum(df),
            "phase": "v2_normalization",
            "active_columns": len(df.columns),
        },
    )


def resolve_validation_decisions(
    decisions: list[dict[str, Any]],
    column_resolver: Any,
) -> list[dict[str, Any]]:
    """Map validation decision columns to physical dataframe column names."""
    resolved: list[dict[str, Any]] = []
    for d in decisions:
        item = dict(d)
        col = str(item.get("column") or item.get("column_name") or "")
        physical = column_resolver(col) if col else None
        if physical:
            item["column"] = physical
        item["user_action"] = str(item.get("user_action") or item.get("decision") or "KEEP").upper()
        resolved.append(item)
    return resolved
