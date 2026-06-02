import os
import shutil
import uuid

from sqlalchemy.orm import Session

from database.models import Dataset

from .metadata import probe_and_persist_dataset_metadata


def save_upload(file, upload_dir: str, user_id: int, db: Session) -> Dataset:
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(upload_dir, name)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    file_size = os.path.getsize(path)
    ds = Dataset(
        user_id=user_id,
        filename=file.filename,
        storage_path=path,
        storage_provider="local",
        file_size=file_size,
        upload_status="UPLOADED",
        status="ingested",
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    probe_and_persist_dataset_metadata(db, ds)
    return ds