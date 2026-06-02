"""Shared analysis execution (multipart upload vs presigned object storage)."""
from __future__ import annotations

import os
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset, Report
from pipelines.orchestrator import run_pipeline
from object_storage.object_store import try_build_default_store
from services.gpu_worker_client import run_remote_analysis

_logger = logging.getLogger(__name__)


def _inference_mode() -> str:
    return os.getenv("INFERENCE_MODE", "local").strip().lower()


def mark_dataset_upload_status(dataset_id: int, status: str) -> None:
    """Standalone commit — safe to call after a rolled-back request transaction."""
    db = SessionLocal()
    try:
        ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if ds and ds.object_key is not None:
            ds.upload_status = status
            db.commit()
    finally:
        db.close()


def _pipeline_object_store(ds: Dataset):
    if not ds.object_key:
        return None
    store = try_build_default_store()
    if store is None:
        raise RuntimeError(
            "Dataset is stored in object storage but STORAGE_PROVIDER / boto3 credentials are not configured."
        )
    return store


def run_semantic_analysis_pipeline(
    *,
    dataset_id: int,
    analysis_id: int,
    db: Session,
) -> dict:
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds:
        raise ValueError("Dataset not found")

    if not ds.storage_path and not ds.object_key:
        raise ValueError("Dataset missing both storage_path and object_key")

    store = _pipeline_object_store(ds)
    report_dir = os.getenv("REPORT_STORAGE_PATH", "./storage/reports")

    return run_pipeline(
        storage_path=ds.storage_path,
        filename=ds.filename,
        object_key=ds.object_key,
        report_dir=report_dir,
        analysis_id=analysis_id,
        dataset_id=dataset_id,
        db=db,
        object_store=store,
    )


def run_analysis_pipeline_with_mode(
    *,
    dataset_id: int,
    analysis_id: int,
    db: Session,
    ds: Dataset,
) -> dict:
    mode = _inference_mode()
    if mode == "remote":
        _logger.info("Running analysis via remote GPU worker for dataset=%s analysis=%s", dataset_id, analysis_id)
        return run_remote_analysis(dataset=ds, dataset_id=dataset_id, analysis_id=analysis_id)
    return run_semantic_analysis_pipeline(dataset_id=dataset_id, analysis_id=analysis_id, db=db)


def reset_orphaned_analyses() -> int:
    """Mark pending/running analyses failed after API restart (background jobs are lost)."""
    db = SessionLocal()
    try:
        rows = db.query(Analysis).filter(Analysis.status.in_(["pending", "running"])).all()
        for an in rows:
            an.status = "failed"
            an.error_message = "Analysis interrupted (server restarted). Run analysis again."
        if rows:
            db.commit()
        return len(rows)
    finally:
        db.close()


def supersede_inflight_analyses(db: Session, dataset_id: int) -> None:
    """Fail stale pending/running rows before starting a fresh analysis."""
    rows = (
        db.query(Analysis)
        .filter(
            Analysis.dataset_id == dataset_id,
            Analysis.status.in_(["pending", "running"]),
        )
        .all()
    )
    for an in rows:
        an.status = "failed"
        an.error_message = "Superseded by a new analysis run."


def persist_analysis_failure(analysis_id: int, detail: str) -> None:
    db = SessionLocal()
    try:
        an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if an:
            an.status = "failed"
            an.error_message = detail[:8000]
            db.commit()
    finally:
        db.close()


def finalize_successful_analysis(
    db: Session, dataset_id: int, analysis_id: int, result: dict
) -> None:
    analysis_row = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis_row:
        raise ValueError("Analysis row missing")
    analysis_row.status = "complete"
    analysis_row.completed_at = datetime.utcnow()
    report_dir = os.getenv("REPORT_STORAGE_PATH", "./storage/reports")
    db.add(
        Report(
            analysis_id=analysis_id,
            report_type="tamper_proof",
            storage_path=os.path.join(report_dir, f"report_{analysis_id}.pdf"),
            content_hash=result.get("content_hash"),
        )
    )
    db.commit()
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if ds and ds.object_key is not None:
        mark_dataset_upload_status(dataset_id, "ANALYZED")


def execute_dataset_analysis_job(dataset_id: int, analysis_id: int) -> None:
    """Background analysis (multipart or object storage)."""
    execute_registered_analysis_job(dataset_id, analysis_id)


def execute_registered_analysis_job(dataset_id: int, analysis_id: int) -> None:
    """
    Runs after `/datasets/register` (BackgroundTasks). Uses a fresh DB session.
    """
    db = SessionLocal()
    ds: Dataset | None = None
    try:
        ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not ds or not an:
            return
        an.status = "running"
        db.commit()

        if ds.object_key:
            mark_dataset_upload_status(dataset_id, "PROCESSING")

        try:
            result = run_analysis_pipeline_with_mode(
                dataset_id=dataset_id, analysis_id=analysis_id, db=db, ds=ds
            )
            finalize_successful_analysis(db, dataset_id, analysis_id, result)
        except Exception as exc:  # noqa: BLE001
            persist_analysis_failure(analysis_id, str(exc))
            if ds.object_key:
                mark_dataset_upload_status(dataset_id, "FAILED")
            _logger.exception("Background analysis failed for dataset=%s analysis=%s", dataset_id, analysis_id)
    finally:
        db.close()
