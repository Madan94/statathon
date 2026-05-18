from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from database.database import SessionLocal
from .services import save_upload
import os

router = APIRouter(prefix="/datasets", tags=["datasets"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/upload")
def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    upload_dir = os.getenv("UPLOAD_STORAGE_PATH", "./storage/uploads")
    # TODO: resolve user_id from JWT
    ds = save_upload(file, upload_dir, user_id=1, db=db)
    return {"dataset_id": ds.id, "filename": ds.filename}