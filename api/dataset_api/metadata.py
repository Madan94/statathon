"""Probe uploaded files for row/column counts and health before analysis runs."""
from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from core.ingestion import (
    dataframe_for_uploaded_dataset,
    health_summary,
    load_file,
)
from database.models import Dataset

logger = logging.getLogger(__name__)


def probe_and_persist_dataset_metadata(
    db: Session,
    ds: Dataset,
    *,
    object_store=None,
) -> dict | None:
    """
    Read the dataset file and persist row_count, column_count, file_size, health_summary.
    Returns health dict on success, None if probing failed.
    """
    try:
        if ds.storage_path:
            path = ds.storage_path
            if ds.file_size is None and os.path.isfile(path):
                ds.file_size = os.path.getsize(path)
            if not ds.storage_provider:
                ds.storage_provider = "local"
            df = load_file(path)
        elif ds.object_key:
            if not ds.storage_provider:
                ds.storage_provider = (os.getenv("STORAGE_PROVIDER") or "s3").strip()
            df = dataframe_for_uploaded_dataset(
                None,
                ds.object_key,
                ds.filename,
                object_store,
            )
        else:
            return None

        health = health_summary(df)
        ds.row_count = int(len(df))
        ds.column_count = int(len(df.columns))
        ds.health_summary = health
        if not ds.upload_status:
            ds.upload_status = "UPLOADED"
        db.commit()
        db.refresh(ds)
        return health
    except Exception as exc:
        logger.warning("Dataset metadata probe failed for id=%s: %s", ds.id, exc)
        if ds.storage_path and os.path.isfile(ds.storage_path) and ds.file_size is None:
            ds.file_size = os.path.getsize(ds.storage_path)
        if not ds.upload_status:
            ds.upload_status = "UPLOADED"
        if ds.storage_path and not ds.storage_provider:
            ds.storage_provider = "local"
        db.commit()
        return None
