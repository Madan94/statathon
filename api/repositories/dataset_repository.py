"""Dataset row metadata updates."""
from __future__ import annotations

import os
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

    def get_by_id(self, dataset_id: int) -> Dataset | None:
        return self.db.query(Dataset).filter(Dataset.id == dataset_id).first()

    def create_from_object_registration(
        self,
        *,
        user_id: int,
        filename: str,
        object_key: str,
        file_size: int,
        checksum: str | None,
        storage_provider: str | None = None,
        upload_status: str = "UPLOADED",
    ) -> Dataset:
        provider = (storage_provider or os.getenv("STORAGE_PROVIDER") or "s3").strip()
        ds = Dataset(
            user_id=user_id,
            filename=filename,
            storage_path=None,
            object_key=object_key,
            storage_provider=provider,
            file_size=file_size,
            checksum=checksum,
            upload_status=upload_status,
            status="ingested",
        )
        self.db.add(ds)
        self.db.commit()
        self.db.refresh(ds)
        return ds

    def set_upload_status(self, dataset_id: int, status: str) -> None:
        ds = self.get_by_id(dataset_id)
        if ds:
            ds.upload_status = status
            self.db.flush()
