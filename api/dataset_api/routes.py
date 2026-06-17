import os

from botocore.exceptions import ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis
from auth.permissions import require_dataset_owner
from deps import get_current_user_id, get_object_store
from repositories.dataset_repository import DatasetRepository
from services.analysis_runner import execute_registered_analysis_job
from object_storage.object_store import ObjectStore, StorageConfigError, try_build_default_store

from .metadata import probe_and_persist_dataset_metadata
from .import_url import import_from_presigned_url
from .profile_jobs import execute_dataset_profile_job
from .response_builder import dataset_metadata_response, dataset_upload_response
from .schemas import ImportFromUrlRequest, RegisterDatasetRequest, UploadUrlRequest
from .services import profile_registered_dataset, register_object_quick, save_upload, save_upload_relay
from .storage_keys import generate_object_key
from services.dataset_profile_service import DatasetProfileService
from services.normalization_service import NormalizationService

router = APIRouter(prefix="/datasets", tags=["datasets"])

SIZE_TOLERANCE = int(os.getenv("REGISTER_SIZE_TOLERANCE_BYTES", "8"))
ASYNC_DATASET_PROFILE = os.getenv("ASYNC_DATASET_PROFILE", "true").lower() in ("1", "true", "yes")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _queue_profile_job(
    background_tasks: BackgroundTasks,
    *,
    dataset_id: int,
    filename: str,
    object_key: str,
    file_bytes: bytes | None = None,
    file_size: int | None = None,
    analysis_id: int | None = None,
) -> None:
    background_tasks.add_task(
        execute_dataset_profile_job,
        dataset_id,
        filename=filename,
        file_bytes=file_bytes,
        object_key=object_key,
        file_size=file_size,
        analysis_id=analysis_id,
    )


@router.post("/upload")
def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    user_id: int = Depends(get_current_user_id),
):
    if ASYNC_DATASET_PROFILE:
        ds, file_bytes = save_upload_relay(file, user_id=user_id, db=db, store=store)
        _queue_profile_job(
            background_tasks,
            dataset_id=ds.id,
            filename=file.filename,
            object_key=ds.object_key,
            file_bytes=file_bytes,
            file_size=len(file_bytes),
        )
    else:
        ds = save_upload(file, user_id=user_id, db=db, store=store)
    return dataset_upload_response(ds)


@router.post("/upload-url")
def create_presigned_upload_url(
    payload: UploadUrlRequest,
    store: ObjectStore = Depends(get_object_store),
    user_id: int = Depends(get_current_user_id),
):
    _ = user_id
    try:
        key = generate_object_key(payload.filename)
        expires = int(os.getenv("PRESIGNED_UPLOAD_EXPIRES_SECONDS", "3600"))
        upload_url = store.generate_presigned_upload_url(key, payload.content_type, expires)
        return {"upload_url": upload_url, "object_key": key, "expires_in": expires}
    except StorageConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/import-from-url")
def import_dataset_from_presigned_url(
    body: ImportFromUrlRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    user_id: int = Depends(get_current_user_id),
):
    """Download CSV/Excel from a presigned S3 GET URL server-side and register dataset."""
    ds = import_from_presigned_url(
        db,
        user_id=user_id,
        url=body.url,
        filename=body.filename,
        store=store,
        background_tasks=background_tasks,
        async_profile=ASYNC_DATASET_PROFILE,
    )
    return dataset_upload_response(ds)


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

    try:
        ds = register_object_quick(
            db,
            user_id=user_id,
            filename=body.filename,
            object_key=body.object_key,
            file_size=body.file_size,
            checksum=body.checksum,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="object_key already registered") from e

    if ASYNC_DATASET_PROFILE:
        _queue_profile_job(
            background_tasks,
            dataset_id=ds.id,
            filename=body.filename,
            object_key=body.object_key,
            file_size=body.file_size,
        )
    else:
        try:
            raw = store.download_object_body(body.object_key)
        except ClientError as e:
            raise HTTPException(status_code=502, detail=f"object storage download error: {e}") from e
        ds = profile_registered_dataset(
            db,
            ds.id,
            filename=body.filename,
            file_bytes=raw,
            file_size=body.file_size,
        )

    an = Analysis(dataset_id=ds.id, status="pending")
    db.add(an)
    db.commit()
    db.refresh(an)

    if ASYNC_DATASET_PROFILE:
        _queue_profile_job(
            background_tasks,
            dataset_id=ds.id,
            filename=body.filename,
            object_key=body.object_key,
            file_size=body.file_size,
            analysis_id=an.id,
        )
    else:
        background_tasks.add_task(execute_registered_analysis_job, ds.id, an.id)

    payload = dataset_upload_response(ds)
    payload["analysis_id"] = an.id
    return payload


@router.get("/{dataset_id}/profile")
def get_dataset_profile(
    dataset_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    ds = require_dataset_owner(db, dataset_id, user_id)
    profile = DatasetProfileService(db).get_profile(dataset_id, ds=ds)
    if not profile:
        raise HTTPException(status_code=404, detail="Dataset profile not found")
    return profile


@router.get("/{dataset_id}/effective-schema")
def get_dataset_effective_schema(
    dataset_id: int,
    analysis_id: int = Query(..., alias="analysis_id"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    require_dataset_owner(db, dataset_id, user_id)
    an = db.query(Analysis).filter(Analysis.id == analysis_id, Analysis.dataset_id == dataset_id).first()
    if not an:
        raise HTTPException(status_code=404, detail="Analysis not found for dataset")
    try:
        return NormalizationService(db).get_effective_schema_response(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    ds = require_dataset_owner(db, dataset_id, user_id)
    if (ds.row_count or 0) == 0 and (ds.column_count or 0) == 0 and (ds.storage_path or ds.object_key):
        store = try_build_default_store() if ds.object_key else None
        probe_and_persist_dataset_metadata(db, ds, object_store=store)
        db.refresh(ds)
    return dataset_metadata_response(ds)
