import os
import shutil
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Dataset
from repositories.dataset_repository import DatasetRepository
from services.dataset_profile_service import DatasetProfileService
from services.dataset_profiler import profile_dataset


def save_upload(file, upload_dir: str, user_id: int, db: Session) -> Dataset:
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '(none)'}")

    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(upload_dir, name)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size_bytes = os.path.getsize(path)
    file_bytes = open(path, "rb").read()
    try:
        profile = profile_dataset(path, filename=file.filename)
    except Exception as e:
        if os.path.isfile(path):
            os.remove(path)
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {e}") from e

    ds = Dataset(
        user_id=user_id,
        filename=file.filename,
        storage_path=path,
        storage_provider="local",
        file_size=file_size_bytes,
        row_count=profile["row_count"],
        column_count=profile["column_count"],
        health_summary=profile["health_summary"],
        upload_status="UPLOADED",
        status="ingested",
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)

    DatasetProfileService(db).persist_from_profiler(
        ds.id, profile, source_bytes=file_bytes
    )
    db.commit()
    db.refresh(ds)
    return ds


def profile_registered_dataset(
    db: Session,
    dataset_id: int,
    *,
    filename: str,
    file_bytes: bytes,
    file_size: int | None = None,
) -> Dataset:
    from services.dataset_profiler import profile_dataset_bytes

    try:
        profile = profile_dataset_bytes(file_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {e}") from e

    size = file_size if file_size is not None else profile["file_size_bytes"]
    ds = DatasetRepository(db).apply_upload_profile(
        dataset_id,
        row_count=profile["row_count"],
        column_count=profile["column_count"],
        file_size=size,
        health_summary=profile["health_summary"],
    )
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found after registration")

    DatasetProfileService(db).persist_from_profiler(
        dataset_id, profile, source_bytes=file_bytes
    )
    db.commit()
    db.refresh(ds)
    return ds
