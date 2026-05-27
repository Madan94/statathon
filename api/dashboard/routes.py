"""Officer dashboard aggregates (scoped to current user)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import Analysis, Dataset, Report, ReportJob
from deps import get_current_user_id

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DatasetSummaryItem(BaseModel):
    id: int
    filename: str
    status: str
    row_count: int
    column_count: int
    created_at: str | None


class DashboardSummary(BaseModel):
    datasets_count: int
    analyses_count: int
    analyses_complete_count: int
    reports_count: int
    report_jobs_count: int
    report_jobs_exported_count: int
    latest_datasets: list[DatasetSummaryItem]


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    base_ds = db.query(Dataset).filter(Dataset.user_id == user_id)
    datasets_count = base_ds.count()

    analyses_count = (
        db.query(func.count(Analysis.id))
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id)
        .scalar()
        or 0
    )
    analyses_complete_count = (
        db.query(func.count(Analysis.id))
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id, Analysis.status == "complete")
        .scalar()
        or 0
    )
    reports_count = (
        db.query(func.count(Report.id))
        .join(Analysis, Report.analysis_id == Analysis.id)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id)
        .scalar()
        or 0
    )
    report_jobs_count = (
        db.query(func.count(ReportJob.id))
        .join(Analysis, ReportJob.analysis_id == Analysis.id)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id)
        .scalar()
        or 0
    )
    report_jobs_exported_count = (
        db.query(func.count(ReportJob.id))
        .join(Analysis, ReportJob.analysis_id == Analysis.id)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(
            Dataset.user_id == user_id,
            ReportJob.status.in_(("exported", "verified")),
        )
        .scalar()
        or 0
    )

    latest = base_ds.order_by(Dataset.created_at.desc()).limit(8).all()
    latest_datasets = [
        DatasetSummaryItem(
            id=ds.id,
            filename=ds.filename,
            status=ds.status or "pending",
            row_count=ds.row_count or 0,
            column_count=ds.column_count or 0,
            created_at=ds.created_at.isoformat() if ds.created_at else None,
        )
        for ds in latest
    ]

    return DashboardSummary(
        datasets_count=datasets_count,
        analyses_count=int(analyses_count),
        analyses_complete_count=int(analyses_complete_count),
        reports_count=int(reports_count) + int(report_jobs_exported_count),
        report_jobs_count=int(report_jobs_count),
        report_jobs_exported_count=int(report_jobs_exported_count),
        latest_datasets=latest_datasets,
    )
