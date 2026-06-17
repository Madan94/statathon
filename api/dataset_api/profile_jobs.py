"""Background dataset profiling after upload/register."""
from __future__ import annotations

import logging

from database.database import SessionLocal
from object_storage.object_store import try_build_default_store

logger = logging.getLogger(__name__)


def execute_dataset_profile_job(
    dataset_id: int,
    *,
    filename: str,
    file_bytes: bytes | None = None,
    object_key: str | None = None,
    file_size: int | None = None,
    analysis_id: int | None = None,
) -> None:
    """Download (if needed), profile once, persist — runs outside request thread."""
    from dataset_api.services import profile_registered_dataset

    db = SessionLocal()
    try:
        body = file_bytes
        if body is None and object_key:
            store = try_build_default_store()
            if not store:
                logger.error("Profile job %s: object storage unavailable", dataset_id)
                return
            body = store.download_object_body(object_key)
        if not body:
            logger.error("Profile job %s: no file bytes", dataset_id)
            return
        profile_registered_dataset(
            db,
            dataset_id,
            filename=filename,
            file_bytes=body,
            file_size=file_size or len(body),
        )
        if analysis_id is not None:
            from services.analysis_runner import execute_registered_analysis_job

            execute_registered_analysis_job(dataset_id, analysis_id)
    except Exception as exc:
        logger.exception("Profile job failed for dataset %s: %s", dataset_id, exc)
        try:
            from repositories.dataset_repository import DatasetRepository

            DatasetRepository(db).set_upload_status(dataset_id, "PROFILE_FAILED")
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
