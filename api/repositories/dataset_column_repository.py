"""Dataset column normalization persistence."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from database.models import DatasetColumn


class DatasetColumnRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_analysis(self, analysis_id: int) -> list[DatasetColumn]:
        return (
            self.db.query(DatasetColumn)
            .filter(DatasetColumn.analysis_id == analysis_id)
            .order_by(DatasetColumn.id)
            .all()
        )

    def seed_from_raw_columns(
        self,
        *,
        dataset_id: int,
        analysis_id: int,
        raw_columns: list[str],
        inferred_types: dict[str, str] | None = None,
        suggested_names: dict[str, str] | None = None,
    ) -> list[DatasetColumn]:
        existing = {c.name: c for c in self.list_for_analysis(analysis_id)}
        types = inferred_types or {}
        suggested = suggested_names or {}
        rows: list[DatasetColumn] = []
        for col in raw_columns:
            name = str(col)
            if name in existing:
                rows.append(existing[name])
                continue
            row = DatasetColumn(
                dataset_id=dataset_id,
                analysis_id=analysis_id,
                name=name,
                normalized_name=suggested.get(name, name),
                inferred_type=types.get(name),
                is_deleted=False,
                is_excluded=False,
                is_active=True,
                last_modified=datetime.utcnow(),
            )
            self.db.add(row)
            rows.append(row)
        self.db.flush()
        return rows
