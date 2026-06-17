import os

from botocore.exceptions import ClientError
from fastapi import HTTPException
from sqlalchemy.orm import Session

from dataset_api.storage_keys import generate_object_key
from object_storage.object_store import ObjectStore
from repositories.dataset_repository import DatasetRepository
from services.dataset_profile_service import DatasetProfileService
from services.dataset_profiler import profile_dataset_bytes


def _content_type_for_filename(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        return "text/csv"
    if ext == ".xls":
        return "application/vnd.ms-excel"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _validate_extension(filename: str) -> None:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '(none)'}")


def save_upload_relay(
    file,
    user_id: int,
    db: Session,
    store: ObjectStore,
    *,
    upload_status: str = "PROCESSING",
):
    """Upload bytes to S3 and create dataset row; profiling runs in background."""
    _validate_extension(file.filename)
    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    object_key = generate_object_key(file.filename)
    content_type = _content_type_for_filename(file.filename)
    try:
        store.upload_object_body(object_key, file_bytes, content_type)
    except ClientError as e:
        raise HTTPException(status_code=502, detail=f"object storage upload error: {e}") from e

    ds = DatasetRepository(db).create_from_object_registration(
        user_id=user_id,
        filename=file.filename,
        object_key=object_key,
        file_size=len(file_bytes),
        checksum=None,
        storage_provider="s3",
        upload_status=upload_status,
        status="processing",
        commit=True,
    )
    return ds, file_bytes


def save_upload(file, user_id: int, db: Session, store: ObjectStore):
    """Sync upload path (single parse) — used when background profiling disabled."""
    ds, file_bytes = save_upload_relay(file, user_id=user_id, db=db, store=store, upload_status="UPLOADED")
    return profile_registered_dataset(
        db,
        ds.id,
        filename=file.filename,
        file_bytes=file_bytes,
        file_size=len(file_bytes),
    )


def register_object_quick(
    db: Session,
    *,
    user_id: int,
    filename: str,
    object_key: str,
    file_size: int,
    checksum: str | None = None,
):
    """Create dataset row after presigned PUT without downloading object."""
    _validate_extension(filename)
    return DatasetRepository(db).create_from_object_registration(
        user_id=user_id,
        filename=filename,
        object_key=object_key,
        file_size=file_size,
        checksum=checksum,
        upload_status="PROCESSING",
        status="processing",
        commit=True,
    )


def profile_registered_dataset(
    db: Session,
    dataset_id: int,
    *,
    filename: str,
    file_bytes: bytes,
    file_size: int | None = None,
):
    """Parse once and persist profile in a single DB transaction."""
    try:
        profile = profile_dataset_bytes(file_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {e}") from e

    size = file_size if file_size is not None else profile["file_size_bytes"]
    repo = DatasetRepository(db)
    ds = repo.apply_upload_profile(
        dataset_id,
        row_count=profile["row_count"],
        column_count=profile["column_count"],
        file_size=size,
        health_summary=profile["health_summary"],
        upload_status="UPLOADED",
        commit=False,
    )
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found after registration")

    DatasetProfileService(db).persist_from_profiler(
        dataset_id, profile, source_bytes=file_bytes
    )
    ds.status = "ingested"
    db.commit()
    db.refresh(ds)
    return ds
