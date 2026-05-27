import os
import shutil
import uuid
from sqlalchemy.orm import Session
from database.models import Dataset, DatasetColumn

def save_upload(file, upload_dir: str, user_id: int, db: Session) -> Dataset:
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename)[1]
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(upload_dir, name)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    ds = Dataset(user_id=user_id, filename=file.filename, storage_path=path, status="ingested")
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds