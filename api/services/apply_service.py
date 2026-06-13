"""Apply user decisions across validation → anomaly → imputation with versioned lineage."""

from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from core.ingestion import dataframe_for_uploaded_dataset, infer_schema
from core.json_safe import make_json_safe
from core.rule_validator import normalize_schema
from database.models import (
    Analysis,
    Dataset,
    DatasetLineageSnapshot,
    ImputationRowDecision,
    OutlierDecision,
    ValidationDecision,
)
from imputation.executors import impute
from object_storage.object_store import try_build_default_store
from pipelines.validation_gate import apply_user_decisions
from services.normalization_transform_service import (
    apply_pipeline_column_rename,
    apply_user_normalization,
    dataframe_checksum,
    load_raw_upload_dataframe,
    resolve_validation_decisions,
)
from services.normalization_service import NormalizationService
from services.phase_audit_service import PhaseAuditService

LINEAGE_STAGES = (
    "original",
    "normalized",
    "validated",
    "anomaly_reviewed",
    "imputed",
    "final",
)


def _derived_dir() -> Path:
    base = os.getenv("DERIVED_STORAGE_PATH", "./storage/derived")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _lineage_prefix(analysis_id: int) -> str:
    return (os.getenv("S3_LINEAGE_PREFIX") or "lineage").strip().strip("/")


def _resolve_column(df: pd.DataFrame, name: str, ui_to_physical: dict[str, str]) -> str | None:
    physical = ui_to_physical.get(name, name)
    if physical in df.columns:
        return physical
    if name in df.columns:
        return name
    return None


def _column_maps(db: Session, analysis_id: int) -> tuple[dict[str, str], dict[str, str]]:
    records = NormalizationService(db)._ensure_columns_seeded(analysis_id)
    ui_to_physical: dict[str, str] = {}
    physical_to_ui: dict[str, str] = {}
    for col in records:
        orig = str(col.name)
        norm = str(col.normalized_name or col.name)
        ui_to_physical[norm] = orig
        ui_to_physical[orig] = orig
        physical_to_ui[orig] = norm
    return ui_to_physical, physical_to_ui


def _coerce_cell_value(series: pd.Series, value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return np.nan
    if pd.api.types.is_numeric_dtype(series.dtype):
        try:
            if pd.api.types.is_integer_dtype(series.dtype):
                return int(float(value))
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _safe_set_cell(df: pd.DataFrame, row_pos: int, col: str, value: Any) -> None:
    if row_pos < 0 or row_pos >= len(df) or col not in df.columns:
        return
    idx = df.index[row_pos]
    coerced = _coerce_cell_value(df[col], value)
    if pd.api.types.is_integer_dtype(df[col].dtype) and isinstance(coerced, float):
        df[col] = df[col].astype(float)
    df.at[idx, col] = coerced


def _sanitize_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        series = out[col]
        if series.dtype == object:
            numeric = pd.to_numeric(series, errors="coerce")
            if numeric.notna().sum() >= max(1, int(series.notna().sum() * 0.5)):
                out[col] = numeric
    return out


def _phase3_overlay(db: Session, analysis_id: int, checkpoint: dict[str, Any]) -> dict[str, Any]:
    from services.analysis_query import build_phase3_from_relational, load_checkpoint_phase3_overlay

    phase3 = dict(checkpoint.get("phase3") or {}) if isinstance(checkpoint.get("phase3"), dict) else {}
    overlay = load_checkpoint_phase3_overlay(db, analysis_id) or {}
    relational = build_phase3_from_relational(db, analysis_id)
    merged = {**relational, **phase3, **overlay}
    return merged


def _snapshot_exists(db: Session, analysis_id: int, stage: str) -> bool:
    """True if a lineage row exists in DB or is pending insert in this session."""
    for obj in db.new:
        if (
            isinstance(obj, DatasetLineageSnapshot)
            and obj.analysis_id == analysis_id
            and obj.stage == stage
        ):
            return True
    row = (
        db.query(DatasetLineageSnapshot.id)
        .filter(
            DatasetLineageSnapshot.analysis_id == analysis_id,
            DatasetLineageSnapshot.stage == stage,
        )
        .first()
    )
    return row is not None


def _next_version(db: Session, analysis_id: int, stage: str) -> int:
    latest = (
        db.query(DatasetLineageSnapshot)
        .filter(
            DatasetLineageSnapshot.analysis_id == analysis_id,
            DatasetLineageSnapshot.stage == stage,
        )
        .order_by(DatasetLineageSnapshot.version.desc())
        .first()
    )
    pending_versions = [
        obj.version
        for obj in db.new
        if isinstance(obj, DatasetLineageSnapshot)
        and obj.analysis_id == analysis_id
        and obj.stage == stage
        and obj.version is not None
    ]
    max_version = latest.version if latest else 0
    if pending_versions:
        max_version = max(max_version, max(pending_versions))
    return max_version + 1


def _persist_snapshot(
    db: Session,
    *,
    analysis_id: int,
    dataset_id: int,
    stage: str,
    df: pd.DataFrame,
    store: Any,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    version = _next_version(db, analysis_id, stage)
    local_path = _derived_dir() / f"analysis_{analysis_id}_{stage}_v{version}.parquet"
    df = _sanitize_for_parquet(df)
    df.to_parquet(local_path, index=False)

    object_key: str | None = None
    if store is not None:
        try:
            buf = io.BytesIO()
            df.to_parquet(buf, index=False)
            object_key = f"{_lineage_prefix(analysis_id)}/{stage}/v{version}.parquet"
            store.upload_object_body(object_key, buf.getvalue(), "application/octet-stream")
        except Exception:
            object_key = None

    safe_meta = dict(meta or {})
    safe_meta.setdefault("checksum", dataframe_checksum(df))
    snap = DatasetLineageSnapshot(
        analysis_id=analysis_id,
        dataset_id=dataset_id,
        stage=stage,
        version=version,
        storage_path=str(local_path),
        object_key=object_key,
        row_count=len(df),
        column_count=len(df.columns),
        meta=make_json_safe(safe_meta),
        created_at=datetime.utcnow(),
    )
    db.add(snap)
    return {
        "stage": stage,
        "version": version,
        "storage_path": str(local_path),
        "object_key": object_key,
        "row_count": len(df),
        "column_count": len(df.columns),
    }


def _validation_decisions(db: Session, analysis_id: int) -> list[dict[str, Any]]:
    rows = db.query(ValidationDecision).filter(ValidationDecision.analysis_id == analysis_id).all()
    return [
        {
            "rule_id": r.rule_id,
            "column": r.column_name,
            "row_id": r.row_index,
            "user_action": r.decision,
            "new_value": r.new_value,
            "severity": r.severity,
            "confidence": r.confidence,
        }
        for r in rows
    ]


def _apply_outlier_decisions(
    df: pd.DataFrame,
    decisions: list[OutlierDecision],
    ui_to_physical: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    out = df.copy()
    rows_to_drop: set[int] = set()
    stats = {"delete_value": 0, "delete_row": 0, "normalize": 0, "keep": 0, "ignore": 0}

    for d in decisions:
        action = str(d.decision).upper()
        col = _resolve_column(out, d.column_name, ui_to_physical)
        row_idx = int(d.row_index)

        if action in ("KEEP", "EDIT_VALUE"):
            stats["keep" if action == "KEEP" else "ignore"] += 1
            continue
        if action == "DELETE_ROW":
            rows_to_drop.add(row_idx)
            stats["delete_row"] += 1
            continue
        if col is None or row_idx < 0 or row_idx >= len(out):
            continue
        if action == "DELETE_VALUE":
            _safe_set_cell(out, row_idx, col, np.nan)
            stats["delete_value"] += 1
        elif action == "NORMALIZE" and pd.api.types.is_numeric_dtype(out[col]):
            s = pd.to_numeric(out[col], errors="coerce")
            mu, sd = float(s.mean()), float(s.std() + 1e-9)
            val = out.iloc[row_idx][col]
            normalized = (float(val) - mu) / sd if pd.notna(val) else np.nan
            _safe_set_cell(out, row_idx, col, normalized)
            stats["normalize"] += 1

    if rows_to_drop:
        keep = [i for i in range(len(out)) if i not in rows_to_drop]
        out = out.iloc[keep].reset_index(drop=True)
    return out, stats


def _apply_imputation(
    df: pd.DataFrame,
    phase3: dict[str, Any],
    imputation_rows: list[ImputationRowDecision],
    ui_to_physical: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = df.copy()
    selections = dict(phase3.get("imputation_method_selections") or {})
    applied: dict[str, Any] = {"columns": {}, "rows_skipped": 0}

    reject_keys: set[tuple[str, int | None]] = set()
    override: dict[tuple[str, int], Any] = {}
    accept_values: dict[tuple[str, int], Any] = {}
    for r in imputation_rows:
        col = r.column_name
        key = (col, r.row_index)
        decision = str(r.decision).upper()
        if decision in ("REJECT", "KEEP_MISSING"):
            reject_keys.add(key)
        elif decision == "OVERRIDE" and r.row_index is not None and r.imputed_value is not None:
            override[(col, int(r.row_index))] = r.imputed_value
        elif decision == "ACCEPT" and r.row_index is not None and r.imputed_value is not None:
            try:
                accept_values[(col, int(r.row_index))] = float(r.imputed_value)
            except (TypeError, ValueError):
                accept_values[(col, int(r.row_index))] = r.imputed_value

    for ui_col, method in selections.items():
        col = _resolve_column(out, ui_col, ui_to_physical)
        if not col or col not in out.columns:
            continue
        series = out[col].copy()
        missing_before = int(series.isna().sum())
        if missing_before == 0:
            continue

        imputed_series = impute(series, out, method.lower())
        for i in range(len(out)):
            if not pd.isna(series.iloc[i]):
                continue
            if (ui_col, i) in reject_keys or (col, i) in reject_keys:
                applied["rows_skipped"] += 1
                continue
            if (ui_col, i) in accept_values:
                _safe_set_cell(out, i, col, accept_values[(ui_col, i)])
            elif (col, i) in accept_values:
                _safe_set_cell(out, i, col, accept_values[(col, i)])
            elif (ui_col, i) in override:
                _safe_set_cell(out, i, col, override[(ui_col, i)])
            elif (col, i) in override:
                _safe_set_cell(out, i, col, override[(col, i)])
            else:
                _safe_set_cell(out, i, col, imputed_series.iloc[i])

        applied["columns"][ui_col] = {
            "method": method,
            "missing_before": missing_before,
            "missing_after": int(out[col].isna().sum()),
        }

    return out, applied


def materialize_processed_dataframe(db: Session, analysis_id: int) -> pd.DataFrame:
    """Rebuild the final processed dataset from persisted decisions (source of truth)."""
    from services.analysis_dataframe_service import load_snapshot_dataframe
    from services.normalization_transform_service import (
        build_column_resolver,
        load_working_dataframe,
    )

    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        raise ValueError("Analysis not found")

    checkpoint = an.checkpoint if isinstance(an.checkpoint, dict) else {}
    phase3 = _phase3_overlay(db, analysis_id, checkpoint)

    normalized = load_snapshot_dataframe(db, analysis_id, "normalized")
    if normalized is not None:
        df = normalized.copy()
    else:
        df, _, _ = load_working_dataframe(db, analysis_id, apply_user_norm=True)

    ui_to_physical, _ = _column_maps(db, analysis_id)

    val_decisions = _validation_decisions(db, analysis_id)
    if not val_decisions:
        raw = phase3.get("validation_user_decisions")
        if isinstance(raw, list):
            val_decisions = [
                {
                    "rule_id": d.get("rule_id"),
                    "column": d.get("column"),
                    "row_id": d.get("row_index"),
                    "user_action": d.get("decision"),
                    "new_value": d.get("new_value"),
                }
                for d in raw
            ]

    resolver = build_column_resolver(df, ui_to_physical)
    val_resolved = resolve_validation_decisions(val_decisions, resolver) if val_decisions else []
    if val_resolved:
        df = apply_user_decisions(df, val_resolved)

    outlier_rows = (
        db.query(OutlierDecision).filter(OutlierDecision.analysis_id == analysis_id).all()
    )
    if outlier_rows:
        df, _ = _apply_outlier_decisions(df, outlier_rows, ui_to_physical)
    else:
        raw = phase3.get("outlier_row_decisions") or {}
        pseudo: list[OutlierDecision] = []
        if isinstance(raw, dict):
            for column, decisions in raw.items():
                if not isinstance(decisions, list):
                    continue
                for d in decisions:
                    if not isinstance(d, dict):
                        continue
                    row_index = d.get("row_index")
                    if row_index is None:
                        continue
                    pseudo.append(
                        OutlierDecision(
                            analysis_id=analysis_id,
                            column_name=str(column),
                            row_index=int(row_index),
                            decision=str(d.get("decision") or "KEEP"),
                            method=str(d.get("method") or d.get("methodology") or "") or None,
                            old_value=str(d.get("old_value")) if d.get("old_value") is not None else None,
                            new_value=str(d.get("new_value")) if d.get("new_value") is not None else None,
                        )
                    )
        if pseudo:
            df, _ = _apply_outlier_decisions(df, pseudo, ui_to_physical)

    imputation_rows = (
        db.query(ImputationRowDecision)
        .filter(ImputationRowDecision.analysis_id == analysis_id)
        .all()
    )
    if imputation_rows or phase3.get("imputation_method_selections"):
        df, _ = _apply_imputation(df, phase3, imputation_rows, ui_to_physical)

    return df


def persist_processed_snapshot(db: Session, analysis_id: int) -> dict[str, Any]:
    """Refresh the working dataset snapshot via the phase chain (validated → anomaly → imputed)."""
    from services.phase_snapshot_service import PhaseSnapshotService

    return PhaseSnapshotService(db).snapshot_imputation(analysis_id)


def apply_analysis_decisions(
    db: Session,
    analysis_id: int,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        raise ValueError("Analysis not found")
    if an.status != "complete":
        raise ValueError("Analysis not complete")

    ds = db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")

    df_raw, ds, store = load_raw_upload_dataframe(db, analysis_id)
    checkpoint = an.checkpoint if isinstance(an.checkpoint, dict) else {}
    df_pipeline = apply_pipeline_column_rename(df_raw, checkpoint)

    norm_service = NormalizationService(db)
    norm_records = norm_service._ensure_columns_seeded(analysis_id)
    df = apply_user_normalization(df_pipeline, norm_records) if norm_records else df_pipeline.copy()

    ui_to_physical, _ = _column_maps(db, analysis_id)
    phase3 = checkpoint.get("phase3") if isinstance(checkpoint.get("phase3"), dict) else {}

    audit = PhaseAuditService(db)
    lineage: list[dict[str, Any]] = []

    lineage.append(
        _persist_snapshot(
            db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="original",
            df=df_raw,
            store=store,
            meta={"source": ds.filename, "phase": "v1_upload"},
        )
    )
    lineage.append(
        _persist_snapshot(
            db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="normalized",
            df=df,
            store=store,
            meta={"phase": "v2_normalization", "active_columns": len(df.columns)},
        )
    )

    val_decisions = _validation_decisions(db, analysis_id)
    if not val_decisions:
        checkpoint_decisions = phase3.get("validation_user_decisions")
        if isinstance(checkpoint_decisions, list):
            val_decisions = [
                {
                    "rule_id": d.get("rule_id"),
                    "column": d.get("column"),
                    "row_id": d.get("row_index"),
                    "user_action": d.get("decision"),
                    "new_value": d.get("new_value"),
                }
                for d in checkpoint_decisions
            ]

    from services.normalization_transform_service import build_column_resolver

    resolver = build_column_resolver(df, ui_to_physical)
    val_resolved = resolve_validation_decisions(val_decisions, resolver) if val_decisions else []
    df_validated = apply_user_decisions(df, val_resolved) if val_resolved else df.copy()
    lineage.append(
        _persist_snapshot(
            db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="validated",
            df=df_validated,
            store=store,
            meta={"validation_decisions": len(val_decisions)},
        )
    )

    outlier_rows = (
        db.query(OutlierDecision).filter(OutlierDecision.analysis_id == analysis_id).all()
    )
    df_anomaly, outlier_stats = _apply_outlier_decisions(df_validated, outlier_rows, ui_to_physical)
    lineage.append(
        _persist_snapshot(
            db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="anomaly_reviewed",
            df=df_anomaly,
            store=store,
            meta={"outlier_stats": outlier_stats},
        )
    )

    imputation_rows = (
        db.query(ImputationRowDecision)
        .filter(ImputationRowDecision.analysis_id == analysis_id)
        .all()
    )
    df_imputed, imputation_meta = _apply_imputation(df_anomaly, phase3, imputation_rows, ui_to_physical)
    lineage.append(
        _persist_snapshot(
            db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="imputed",
            df=df_imputed,
            store=store,
            meta=imputation_meta,
        )
    )

    df_final = df_imputed.copy()
    final_path = _derived_dir() / f"analysis_{analysis_id}_final.csv"
    df_final.to_csv(final_path, index=False)
    lineage.append(
        _persist_snapshot(
            db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="final",
            df=df_final,
            store=store,
            meta={"csv_export": str(final_path)},
        )
    )

    summary = make_json_safe(
        {
            "analysis_id": analysis_id,
            "dataset_id": ds.id,
            "final_path": str(final_path),
            "rows_after": len(df_final),
            "columns": list(df_final.columns),
            "lineage": lineage,
            "validation_decisions_applied": len(val_decisions),
            "outlier_decisions_applied": len(outlier_rows),
            "imputation_decisions_applied": len(imputation_rows),
        }
    )

    checkpoint = dict(checkpoint)
    checkpoint["derived_dataset"] = summary
    checkpoint["dataset_lineage"] = lineage
    an.checkpoint = checkpoint

    audit.record(
        analysis_id=analysis_id,
        phase="persistence",
        action="apply_lineage",
        user_id=user_id,
        payload=summary,
    )
    db.commit()
    return summary


def get_lineage(db: Session, analysis_id: int) -> dict[str, Any]:
    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        raise ValueError("Analysis not found")
    snaps = (
        db.query(DatasetLineageSnapshot)
        .filter(DatasetLineageSnapshot.analysis_id == analysis_id)
        .order_by(DatasetLineageSnapshot.created_at.asc())
        .all()
    )
    checkpoint = an.checkpoint if isinstance(an.checkpoint, dict) else {}
    chain = [
        {
            "stage": s.stage,
            "version": s.version,
            "storage_path": s.storage_path,
            "object_key": s.object_key,
            "row_count": s.row_count,
            "column_count": s.column_count,
            "metadata": s.meta,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snaps
    ]
    return {
        "analysis_id": analysis_id,
        "stages": LINEAGE_STAGES,
        "snapshots": chain,
        "latest_apply": checkpoint.get("derived_dataset"),
    }
