"""RBAC helpers for report builder resources."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth.permissions import require_analysis_owner
from database.models import Analysis, ReportJob, ReportTemplate


def require_template_access(
    db: Session, template_id: int, user_id: int, *, allow_shared: bool = True
) -> ReportTemplate:
    row = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Template not found")
    if row.user_id is not None and row.user_id != user_id:
        raise HTTPException(403, "Not allowed to access this template")
    if row.user_id is None and not allow_shared:
        raise HTTPException(403, "Not allowed to access this template")
    return row


def require_job_access(db: Session, job_id: int, user_id: int) -> ReportJob:
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    require_analysis_owner(db, job.analysis_id, user_id)
    return job


def filter_config_dict(spec) -> dict | None:
    if spec is None:
        return None
    if hasattr(spec, "model_dump"):
        return spec.model_dump(exclude_none=True)
    if isinstance(spec, dict):
        return {k: v for k, v in spec.items() if v is not None}
    return None
