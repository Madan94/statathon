"""Tests for final approved dataset snapshot persistence."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from review.dataset_snapshot_service import (
    FINAL_STAGE,
    DatasetSnapshotService,
    resolve_processed_stage,
)


def test_resolve_processed_stage_prefers_final_when_approved():
    db = MagicMock()
    final_snap = MagicMock()
    final_snap.stage = FINAL_STAGE

    phase_row = MagicMock()
    phase_row.dataset_review_completed = True

    final_query = MagicMock()
    final_query.filter.return_value.order_by.return_value.first.return_value = final_snap

    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        if name == "DatasetLineageSnapshot":
            return final_query
        return MagicMock()

    db.query.side_effect = query_side_effect

    with patch("services.phase_status_service.PhaseStatusService") as ps_cls:
        ps_cls.return_value.get_or_create.return_value = phase_row
        assert resolve_processed_stage(db, 1) == FINAL_STAGE


def test_persist_final_approved_snapshot_writes_parquet(tmp_path):
    db = MagicMock()
    analysis_id = 99
    df = pd.DataFrame({"income": [1, 2], "hh_weight": [1.0, 1.2]})

    service = DatasetSnapshotService(db)
    service.load_working_processed_dataframe = MagicMock(
        return_value=(df, MagicMock(id=5, stage="imputed", version=2))
    )
    service._latest_snapshot = MagicMock(return_value=None)
    service._read_snapshot_df = MagicMock(return_value=None)

    fake_analysis = MagicMock()
    fake_analysis.dataset_id = 7

    with patch("services.analysis_query.get_analysis_meta", return_value=fake_analysis), patch(
        "services.apply_service._derived_dir", return_value=tmp_path
    ), patch("services.apply_service._persist_snapshot") as persist:
        persist.return_value = {
            "stage": FINAL_STAGE,
            "version": 1,
            "storage_path": str(tmp_path / f"analysis_{analysis_id}_final_v1.parquet"),
            "row_count": 2,
            "column_count": 2,
        }
        meta = service.persist_final_approved_snapshot(analysis_id, user_id=1)

    persist.assert_called_once()
    assert persist.call_args.kwargs["stage"] == FINAL_STAGE
    assert meta["stage"] == FINAL_STAGE
    csv_path = tmp_path / f"analysis_{analysis_id}_final.csv"
    assert csv_path.exists()
