"""Build JSON payloads for dataset upload and detail responses."""
from __future__ import annotations

from database.models import Dataset


def file_size_mb(ds: Dataset) -> float | None:
    if not ds.file_size:
        return None
    return round(ds.file_size / (1024 * 1024), 2)


def dataset_metadata_response(ds: Dataset) -> dict:
    """Full dataset metadata for GET /datasets/{id} and upload responses."""
    health = ds.health_summary if isinstance(ds.health_summary, dict) else {}
    return {
        "id": ds.id,
        "dataset_id": ds.id,
        "filename": ds.filename,
        "name": ds.filename,
        "user_id": ds.user_id,
        "storage_path": ds.storage_path,
        "object_key": ds.object_key,
        "storage_provider": ds.storage_provider,
        "storage_url": ds.storage_url,
        "upload_status": ds.upload_status,
        "file_size": ds.file_size,
        "file_size_bytes": ds.file_size,
        "file_size_mb": file_size_mb(ds),
        "checksum": ds.checksum,
        "row_count": ds.row_count,
        "column_count": ds.column_count,
        "status": ds.status,
        "health_summary": ds.health_summary,
        "missing_cells": health.get("missing_cells"),
        "duplicate_rows": health.get("duplicate_rows"),
        "numeric_columns": health.get("numeric_columns"),
        "categorical_columns": health.get("categorical_columns"),
        "column_list": health.get("column_list"),
        "memory_usage_mb": health.get("memory_usage_mb"),
        "completeness_pct": health.get("completeness_pct"),
        "consistency_pct": health.get("consistency_pct"),
        "health_score": health.get("health_score"),
        "preview_rows": health.get("preview_rows"),
        "uploaded_at": ds.created_at.isoformat() if ds.created_at else None,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
    }


def dataset_upload_response(ds: Dataset) -> dict:
    """Metadata returned immediately after upload/register."""
    base = dataset_metadata_response(ds)
    return {
        "dataset_id": ds.id,
        "id": ds.id,
        "filename": ds.filename,
        "name": ds.filename,
        "row_count": ds.row_count,
        "column_count": ds.column_count,
        "file_size": ds.file_size,
        "file_size_bytes": ds.file_size,
        "file_size_mb": base["file_size_mb"],
        "uploaded_at": base["uploaded_at"],
        "status": ds.status,
        "upload_status": ds.upload_status,
        "health_summary": ds.health_summary,
        "missing_cells": base["missing_cells"],
        "duplicate_rows": base["duplicate_rows"],
        "numeric_columns": base["numeric_columns"],
        "categorical_columns": base["categorical_columns"],
        "column_list": base["column_list"],
        "memory_usage_mb": base["memory_usage_mb"],
        "completeness_pct": base["completeness_pct"],
        "consistency_pct": base["consistency_pct"],
        "preview_rows": base["preview_rows"],
    }
