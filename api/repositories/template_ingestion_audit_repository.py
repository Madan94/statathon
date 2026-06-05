"""Audit trail for template PDF ingestion + immutable vault."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from database.models import TemplateIngestionAudit


class TemplateIngestionAuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def log_ingestion(
        self,
        *,
        source_hash: str,
        vault_pdf_key: str,
        vault_manifest_key: str,
        extraction_method: str | None,
        page_count: int | None,
        user_id: int | None = None,
        extraction_job_id: int | None = None,
        template_id: int | None = None,
        source_filename: str | None = None,
        status: str = "ingested",
        payload: dict[str, Any] | None = None,
    ) -> TemplateIngestionAudit:
        row = TemplateIngestionAudit(
            user_id=user_id,
            extraction_job_id=extraction_job_id,
            template_id=template_id,
            source_hash=source_hash,
            source_filename=source_filename,
            vault_pdf_key=vault_pdf_key,
            vault_manifest_key=vault_manifest_key,
            extraction_method=extraction_method,
            page_count=page_count,
            status=status,
            payload=payload,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def link_template_id(self, extraction_job_id: int, template_id: int) -> int:
        """Set template_id on audit rows for a completed extraction job."""
        rows = (
            self.db.query(TemplateIngestionAudit)
            .filter(TemplateIngestionAudit.extraction_job_id == extraction_job_id)
            .all()
        )
        for row in rows:
            row.template_id = template_id
        self.db.commit()
        return len(rows)
