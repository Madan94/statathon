"""Resource ownership checks."""

from fastapi import HTTPException
from sqlalchemy.orm import Session, load_only

from database.models import Analysis, Dataset


def require_dataset_owner(db: Session, dataset_id: int, user_id: int) -> Dataset:
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user_id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds


def require_analysis_owner(db: Session, analysis_id: int, user_id: int) -> Analysis:
    row = (
        db.query(Analysis)
        .join(Dataset, Dataset.id == Analysis.dataset_id)
        .filter(Analysis.id == analysis_id, Dataset.user_id == user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return row


def require_analysis_owner_meta(db: Session, analysis_id: int, user_id: int) -> Analysis:
    """Ownership check without loading the large checkpoint JSON blob."""
    row = (
        db.query(Analysis)
        .options(
            load_only(
                Analysis.id,
                Analysis.dataset_id,
                Analysis.status,
                Analysis.error_message,
                Analysis.completed_at,
                Analysis.created_at,
            )
        )
        .join(Dataset, Dataset.id == Analysis.dataset_id)
        .filter(Analysis.id == analysis_id, Dataset.user_id == user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return row
