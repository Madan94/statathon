"""Relational persistence for Phase 1 dataset/column intelligence JSON."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.database.models import ColumnIntelligenceProfile, DatasetIntelligenceRecord


class DatasetIntelligenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_analysis(
        self,
        dataset_id: int,
        analysis_id: int,
        dataset_profile: dict[str, Any],
        column_profiles: dict[str, Any],
    ) -> None:
        self.db.query(DatasetIntelligenceRecord).filter(
            DatasetIntelligenceRecord.analysis_id == analysis_id
        ).delete()
        self.db.query(ColumnIntelligenceProfile).filter(
            ColumnIntelligenceProfile.analysis_id == analysis_id
        ).delete()

        self.db.add(
            DatasetIntelligenceRecord(
                dataset_id=dataset_id,
                analysis_id=analysis_id,
                rollup_json=dict(dataset_profile or {}),
            )
        )
        for column_name, prof in sorted((column_profiles or {}).items(), key=lambda x: x[0]):
            self.db.add(
                ColumnIntelligenceProfile(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    column_name=str(column_name),
                    profile_json=dict(prof) if isinstance(prof, dict) else {"value": prof},
                )
            )
