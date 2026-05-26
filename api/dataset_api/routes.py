import os

from botocore.exceptions import ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset
from deps import get_current_user_id, get_object_store
from repositories.dataset_repository import DatasetRepository
from services.analysis_runner import execute_registered_analysis_job
from object_storage.object_store import ObjectStore, StorageConfigError

from .schemas import RegisterDatasetRequest, UploadUrlRequest
from .services import save_upload
from .storage_keys import generate_object_key

router = APIRouter(prefix="/datasets", tags=["datasets"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SIZE_TOLERANCE = int(os.getenv("REGISTER_SIZE_TOLERANCE_BYTES", "8"))


@router.post("/upload")
def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    upload_dir = os.getenv("UPLOAD_STORAGE_PATH", "./storage/uploads")
    ds = save_upload(file, upload_dir, user_id=user_id, db=db)
    return {"dataset_id": ds.id, "id": ds.id, "filename": ds.filename}


@router.post("/upload-url")
def create_presigned_upload_url(
    payload: UploadUrlRequest,
    store: ObjectStore = Depends(get_object_store),
):
    try:
        key = generate_object_key(payload.filename)
        expires = int(os.getenv("PRESIGNED_UPLOAD_EXPIRES_SECONDS", "3600"))
        upload_url = store.generate_presigned_upload_url(key, payload.content_type, expires)
        return {"upload_url": upload_url, "object_key": key, "expires_in": expires}
    except StorageConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/register")
def register_dataset_after_presigned_upload(
    body: RegisterDatasetRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    user_id: int = Depends(get_current_user_id),
):
    try:
        meta = store.get_object_metadata(body.object_key)
    except ClientError as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code == "404":
            raise HTTPException(status_code=400, detail="object_key not found in bucket") from e
        raise HTTPException(status_code=502, detail=f"object storage head error: {e}") from e
    remote_size = meta.get("ContentLength")
    if remote_size is None:
        raise HTTPException(status_code=400, detail="could not read ContentLength from object metadata")
    if abs(remote_size - body.file_size) > SIZE_TOLERANCE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"file_size mismatch: client={body.file_size} storage={remote_size} "
                f"(tolerance {SIZE_TOLERANCE}b)"
            ),
        )

    repo = DatasetRepository(db)
    try:
        ds = repo.create_from_object_registration(
            user_id=user_id,
            filename=body.filename,
            object_key=body.object_key,
            file_size=body.file_size,
            checksum=body.checksum,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="object_key already registered") from e

    an = Analysis(dataset_id=ds.id, status="pending")
    db.add(an)
    db.commit()
    db.refresh(an)

    background_tasks.add_task(execute_registered_analysis_job, ds.id, an.id)

    return {"dataset_id": ds.id, "analysis_id": an.id}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {
        "id": ds.id,
        "filename": ds.filename,
        "user_id": ds.user_id,
        "storage_path": ds.storage_path,
        "object_key": ds.object_key,
        "storage_provider": ds.storage_provider,
        "storage_url": ds.storage_url,
        "upload_status": ds.upload_status,
        "file_size": ds.file_size,
        "checksum": ds.checksum,
        "row_count": ds.row_count,
        "column_count": ds.column_count,
        "status": ds.status,
        "health_summary": ds.health_summary,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
    }
