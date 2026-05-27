"""Resource ownership checks."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Analysis, Dataset


def require_dataset_owner(db: Session, dataset_id: int, user_id: int) -> Dataset:
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user_id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds


def require_analysis_owner(db: Session, analysis_id: int, user_id: int) -> Analysis:
    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        raise HTTPException(status_code=404, detail="Analysis not found")
    ds = db.query(Dataset).filter(Dataset.id == an.dataset_id).first()
    if not ds or ds.user_id != user_id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return an
