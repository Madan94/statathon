"""Dataset row metadata updates."""
from __future__ import annotations

from sqlalchemy.orm import Session

from database.models import Dataset


class DatasetRepository:
    def __init__(self, db: Session):
        self.db = db

    def update_dimensions(self, dataset_id: int, row_count: int, column_count: int, health_summary: dict | None = None) -> None:
        ds = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not ds:
            return
        ds.row_count = row_count
        ds.column_count = column_count
        if health_summary is not None:
            ds.health_summary = health_summary
        self.db.flush()
