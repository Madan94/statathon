"""Column normalization audit trail."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from database.models import ColumnNormalizationAudit


class ColumnAuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        *,
        dataset_id: int,
        analysis_id: int,
        column_id: int | None,
        user_id: int | None,
        old_name: str | None,
        new_name: str | None,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(
            ColumnNormalizationAudit(
                dataset_id=dataset_id,
                analysis_id=analysis_id,
                column_id=column_id,
                user_id=user_id,
                old_name=old_name,
                new_name=new_name,
                action=action,
                payload=payload,
            )
        )
