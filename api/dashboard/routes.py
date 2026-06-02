"""Officer dashboard aggregates (scoped to current user)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.database import SessionLocal
from utils.datetime_json import isoformat_utc
from database.models import (
    Analysis,
    Dataset,
    Report,
    ReportCorrection,
    ReportJob,
    ReportTemplate,
    ReportTemplateExtractionJob,
)
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


class ActivityItem(BaseModel):
    event_type: str
    title: str
    actor_id: int
    created_at: str | None
    metadata: dict


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
            created_at=isoformat_utc(ds.created_at),
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


@router.get("/activity", response_model=list[ActivityItem])
def dashboard_activity(
    limit: int = 150,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    safe_limit = max(20, min(int(limit), 300))
    events: list[ActivityItem] = []

    datasets = (
        db.query(Dataset)
        .filter(Dataset.user_id == user_id)
        .order_by(Dataset.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    for ds in datasets:
        events.append(
            ActivityItem(
                event_type="dataset.uploaded",
                title=f"Dataset uploaded: {ds.filename}",
                actor_id=user_id,
                created_at=isoformat_utc(ds.created_at),
                metadata={
                    "dataset_id": ds.id,
                    "status": ds.status,
                    "upload_status": ds.upload_status,
                    "row_count": ds.row_count,
                    "column_count": ds.column_count,
                    "storage_provider": ds.storage_provider,
                },
            )
        )

    analyses = (
        db.query(Analysis, Dataset)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id)
        .order_by(Analysis.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    for an, ds in analyses:
        events.append(
            ActivityItem(
                event_type=f"analysis.{an.status or 'unknown'}",
                title=f"Analysis {an.status or 'updated'} for {ds.filename}",
                actor_id=user_id,
                created_at=isoformat_utc(an.completed_at or an.created_at),
                metadata={
                    "analysis_id": an.id,
                    "dataset_id": ds.id,
                    "status": an.status,
                    "error_message": an.error_message,
                    "completed_at": isoformat_utc(an.completed_at),
                },
            )
        )

    template_jobs = (
        db.query(ReportTemplateExtractionJob)
        .filter(ReportTemplateExtractionJob.user_id == user_id)
        .order_by(ReportTemplateExtractionJob.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    for tj in template_jobs:
        events.append(
            ActivityItem(
                event_type=f"template.extract.{tj.status}",
                title=f"Template extraction {tj.status}: {tj.template_name}",
                actor_id=user_id,
                created_at=isoformat_utc(tj.updated_at or tj.created_at),
                metadata={
                    "extract_job_id": tj.id,
                    "stage": tj.stage,
                    "progress_pct": tj.progress_pct,
                    "source_filename": tj.source_filename,
                    "source_hash": tj.source_hash,
                    "created_template_id": tj.created_template_id,
                    "error_message": tj.error_message,
                },
            )
        )

    templates = (
        db.query(ReportTemplate)
        .filter(ReportTemplate.user_id == user_id)
        .order_by(ReportTemplate.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    for tpl in templates:
        events.append(
            ActivityItem(
                event_type="template.created",
                title=f"Template saved: {tpl.name}",
                actor_id=user_id,
                created_at=isoformat_utc(tpl.created_at),
                metadata={
                    "template_id": tpl.id,
                    "page_count": tpl.page_count,
                    "extraction_method": tpl.extraction_method,
                    "source_hash": tpl.source_hash,
                },
            )
        )

    report_jobs = (
        db.query(ReportJob, Analysis, Dataset)
        .join(Analysis, ReportJob.analysis_id == Analysis.id)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id)
        .order_by(ReportJob.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    for job, an, ds in report_jobs:
        events.append(
            ActivityItem(
                event_type=f"report_job.{job.status}",
                title=f"Report job {job.status} for {ds.filename}",
                actor_id=user_id,
                created_at=isoformat_utc(job.updated_at or job.created_at),
                metadata={
                    "job_id": job.id,
                    "analysis_id": an.id,
                    "dataset_id": ds.id,
                    "template_id": job.template_id,
                    "stage": job.stage,
                    "content_hash": job.content_hash,
                    "final_pdf_path": job.final_pdf_path,
                    "error_message": job.error_message,
                },
            )
        )

    corrections = (
        db.query(ReportCorrection, ReportJob, Analysis, Dataset)
        .join(ReportJob, ReportCorrection.job_id == ReportJob.id)
        .join(Analysis, ReportJob.analysis_id == Analysis.id)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .filter(Dataset.user_id == user_id)
        .order_by(ReportCorrection.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    for corr, job, an, ds in corrections:
        events.append(
            ActivityItem(
                event_type="report.correction",
                title=f"Correction recorded on job #{job.id} ({ds.filename})",
                actor_id=user_id,
                created_at=isoformat_utc(corr.created_at),
                metadata={
                    "correction_id": corr.id,
                    "job_id": job.id,
                    "analysis_id": an.id,
                    "dataset_id": ds.id,
                    "block_id": corr.block_id,
                    "kind": corr.correction_kind,
                },
            )
        )

    events.sort(key=lambda e: e.created_at or "", reverse=True)
    return events[:safe_limit]
