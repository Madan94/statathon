import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Report

router = APIRouter(prefix="/reports", tags=["reports"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/{analysis_id}/download")
def download_report(analysis_id: int, db: Session = Depends(get_db)):
    an = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not an:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if an.status != "complete":
        raise HTTPException(status_code=409, detail="Analysis not complete")

    report_row = (
        db.query(Report)
        .filter(Report.analysis_id == analysis_id, Report.report_type == "tamper_proof")
        .order_by(Report.id.desc())
        .first()
    )
    report_dir = os.getenv("REPORT_STORAGE_PATH", "./storage/reports")
    candidates = []
    if report_row and report_row.storage_path:
        candidates.append(report_row.storage_path)
    candidates.append(os.path.join(report_dir, f"report_{analysis_id}.pdf"))

    pdf_path: Path | None = None
    for raw in candidates:
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.is_file():
            pdf_path = p
            break

    if pdf_path is None:
        raise HTTPException(status_code=404, detail="Report PDF not found")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"statathon-report-{analysis_id}.pdf",
    )
