from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.database import SessionLocal
from database.models import Dataset, Analysis, Report
import os

router = APIRouter(prefix="/analysis", tags=["analysis"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/{dataset_id}/analyze")
def analyze(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(404, "Dataset not found")
    an = Analysis(dataset_id=dataset_id, status="running")
    db.add(an)
    db.commit()
    db.refresh(an)
    report_dir = os.getenv("REPORT_STORAGE_PATH", "./storage/reports")
    try:
        from pipelines.orchestrator import run_pipeline

        result = run_pipeline(ds.storage_path, report_dir, an.id)
        an.status = "complete"
        r = Report(analysis_id=an.id, report_type="tamper_proof", storage_path=os.path.join(report_dir, f"report_{an.id}.pdf"), content_hash=result.get("content_hash"))
        db.add(r)
        db.commit()
        return {"analysis_id": an.id, "result": result}
    except Exception as e:
        an.status = "failed"
        an.error_message = str(e)
        db.commit()
        raise HTTPException(500, str(e))