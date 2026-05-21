import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset
from services.analysis_runner import (
    finalize_successful_analysis,
    mark_dataset_upload_status,
    persist_analysis_failure,
    run_semantic_analysis_pipeline,
)
from services.analysis_results_service import build_semantic_results_from_db

router = APIRouter(prefix="/analysis", tags=["analysis"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/{analysis_id}/results")
def get_analysis_results(analysis_id: int, db: Session = Depends(get_db)):
    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if an.status == "failed":
        raise HTTPException(status_code=409, detail=an.error_message or "Analysis failed")
    if an.status != "complete":
        raise HTTPException(status_code=409, detail="Analysis still running or pending")

    payload = an.checkpoint if isinstance(an.checkpoint, dict) else None
    if not payload:
        payload = build_semantic_results_from_db(db, analysis_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Semantic intelligence payload unavailable")
    return payload


@router.post("/{dataset_id}/analyze")
def analyze(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(404, "Dataset not found")
    an = Analysis(dataset_id=dataset_id, status="running")
    db.add(an)
    db.commit()
    db.refresh(an)

    if ds.object_key:
        mark_dataset_upload_status(dataset_id, "PROCESSING")

    try:
        result = run_semantic_analysis_pipeline(
            dataset_id=dataset_id, analysis_id=an.id, db=db
        )
        finalize_successful_analysis(db, dataset_id, an.id, result)
        db.refresh(an)
        report_dir = os.getenv("REPORT_STORAGE_PATH", "./storage/reports")
        return {
            "analysis_id": an.id,
            "id": an.id,
            "dataset_id": dataset_id,
            "result": result,
            "report_storage_path": os.path.join(report_dir, f"report_{an.id}.pdf"),
        }
    except Exception as e:
        if ds.object_key:
            mark_dataset_upload_status(dataset_id, "FAILED")
        persist_analysis_failure(an.id, str(e))
        raise HTTPException(status_code=500, detail=str(e))
