"""Global column dictionary upload and retrieval."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database.database import SessionLocal
from deps import get_current_user_id
from services.column_dictionary_service import (
    ColumnDictionaryError,
    ColumnDictionaryService,
    http_error_from_dictionary,
)

router = APIRouter(prefix="/column-dictionary", tags=["column-dictionary"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def get_column_dictionary(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    del user_id
    return ColumnDictionaryService(db).get_global_summary()


@router.post("/upload")
async def upload_column_dictionary(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Upload a .json dictionary file")
    raw = await file.read()
    try:
        return ColumnDictionaryService(db).upload_and_merge(raw, user_id)
    except ColumnDictionaryError as exc:
        raise http_error_from_dictionary(exc) from exc
