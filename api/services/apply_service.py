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
from services.normalization_service import NormalizationService
from services.phase_audit_service import PhaseAuditService

LINEAGE_STAGES = (
    "original",
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
    return (latest.version + 1) if latest else 1


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

    snap = DatasetLineageSnapshot(
        analysis_id=analysis_id,
        dataset_id=dataset_id,
        stage=stage,
        version=version,
        storage_path=str(local_path),
        object_key=object_key,
        row_count=len(df),
        column_count=len(df.columns),
        meta=make_json_safe(meta or {}),
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
        idx = out.index[row_idx]
        if action == "DELETE_VALUE":
            out.at[idx, col] = np.nan
            stats["delete_value"] += 1
        elif action == "NORMALIZE" and pd.api.types.is_numeric_dtype(out[col]):
            s = pd.to_numeric(out[col], errors="coerce")
            mu, sd = float(s.mean()), float(s.std() + 1e-9)
            out.at[idx, col] = (float(out.at[idx, col]) - mu) / sd if pd.notna(out.at[idx, col]) else np.nan
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
    for r in imputation_rows:
        col = r.column_name
        key = (col, r.row_index)
        decision = str(r.decision).upper()
        if decision in ("REJECT", "KEEP_MISSING"):
            reject_keys.add(key)
        elif decision == "OVERRIDE" and r.row_index is not None and r.imputed_value is not None:
            override[(col, int(r.row_index))] = r.imputed_value

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
            if (ui_col, i) in override:
                out.at[out.index[i], col] = override[(ui_col, i)]
            elif (col, i) in override:
                out.at[out.index[i], col] = override[(col, i)]
            else:
                out.at[out.index[i], col] = imputed_series.iloc[i]

        applied["columns"][ui_col] = {
            "method": method,
            "missing_before": missing_before,
            "missing_after": int(out[col].isna().sum()),
        }

    return out, applied


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

    store = try_build_default_store() if ds.object_key else None
    df_raw = dataframe_for_uploaded_dataset(ds.storage_path, ds.object_key, ds.filename, store)
    schema = infer_schema(df_raw)
    df = normalize_schema(df_raw, schema)

    ui_to_physical, _ = _column_maps(db, analysis_id)
    checkpoint = an.checkpoint if isinstance(an.checkpoint, dict) else {}
    phase3 = checkpoint.get("phase3") if isinstance(checkpoint.get("phase3"), dict) else {}

    audit = PhaseAuditService(db)
    lineage: list[dict[str, Any]] = []

    lineage.append(
        _persist_snapshot(
            db,
            analysis_id=analysis_id,
            dataset_id=ds.id,
            stage="original",
            df=df,
            store=store,
            meta={"source": ds.filename},
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

    df_validated = apply_user_decisions(df, val_decisions) if val_decisions else df.copy()
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
