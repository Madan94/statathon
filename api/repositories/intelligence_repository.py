"""Relational persistence for Phase 1 dataset/column intelligence JSON."""
from __future__ import annotations

import json
import math
import time
from typing import Any

from sqlalchemy.orm import Session

from api.database.models import ColumnIntelligenceProfile, DatasetIntelligenceRecord
from core.json_safe import make_json_safe

_DEBUG_LOG = "/media/akassh/New Volume/MOSPI/statathon/.cursor/debug-e80a72.log"


def _agent_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "e80a72",
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    }
                )
                + "\n"
            )
    except OSError:
        pass
    # #endregion


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

        safe_rollup = make_json_safe(dict(dataset_profile or {}))
        self.db.add(
            DatasetIntelligenceRecord(
                dataset_id=dataset_id,
                analysis_id=analysis_id,
                rollup_json=safe_rollup,
            )
        )
        nan_columns: list[str] = []
        for column_name, prof in sorted((column_profiles or {}).items(), key=lambda x: x[0]):
            safe_prof = make_json_safe(dict(prof) if isinstance(prof, dict) else {"value": prof})
            skew = safe_prof.get("skewness") if isinstance(safe_prof, dict) else None
            if isinstance(skew, float) and math.isnan(skew):
                nan_columns.append(str(column_name))
            self.db.add(
                ColumnIntelligenceProfile(
                    dataset_id=dataset_id,
                    analysis_id=analysis_id,
                    column_name=str(column_name),
                    profile_json=safe_prof,
                )
            )
        # #region agent log
        _agent_log(
            "C",
            "intelligence_repository.py:replace_for_analysis",
            "column profiles sanitized before insert",
            {
                "dataset_id": dataset_id,
                "analysis_id": analysis_id,
                "column_count": len(column_profiles or {}),
                "nan_skew_columns_remaining": nan_columns,
            },
        )
        # #endregion
