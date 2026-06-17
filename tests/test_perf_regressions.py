"""Performance regression tests for ingestion and phase status."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))


def test_save_upload_relay_does_not_pre_parse():
    from dataset_api import services as svc

    db = MagicMock()
    store = MagicMock()
    file_obj = MagicMock()
    file_obj.filename = "sample.csv"
    file_obj.file.read.return_value = b"a,b\n1,2\n"

    with patch.object(svc, "profile_dataset_bytes") as mock_profile:
        ds_mock = MagicMock()
        ds_mock.id = 1
        ds_mock.object_key = "datasets/1/sample.csv"
        with patch.object(svc.DatasetRepository(db), "create_from_object_registration", return_value=ds_mock):
            svc.save_upload_relay(file_obj, user_id=1, db=db, store=store)

    mock_profile.assert_not_called()
    store.upload_object_body.assert_called_once()


def test_get_status_payload_does_not_commit():
    from services.phase_status_service import PhaseStatusService

    db = MagicMock()
    svc = PhaseStatusService(db)
    phase3 = {
        "validation_candidates_reported_total": 0,
        "validation_results": {},
        "anomaly_results": [],
        "anomaly_candidates": [],
        "imputation_candidates": [],
        "imputation_results": [],
    }

    with patch.object(svc, "get_or_create") as mock_row:
        row = MagicMock()
        row.summary_completed = True
        row.normalization_completed = True
        row.semantic_completed = True
        row.clustering_completed = True
        row.kg_completed = True
        row.rule_validation_completed = False
        row.anomaly_completed = False
        row.missing_value_completed = False
        row.weight_application_completed = False
        row.dataset_review_completed = False
        row.updated_at = None
        mock_row.return_value = row
        with patch(
            "services.phase_status_service.build_phase3_from_relational",
            return_value=phase3,
        ):
            with patch.object(svc, "_early_phase_flags", return_value={"summary_completed": True}):
                with patch.object(svc, "validation_review_progress", return_value={"complete": True, "total": 0, "reviewed": 0}):
                    with patch.object(svc, "recompute_anomaly_columns", return_value={"complete": True}):
                        with patch.object(svc, "recompute_imputation_columns", return_value={"complete": True}):
                            with patch(
                                "services.phase_status_service.get_cached_phase_status",
                                return_value=None,
                            ):
                                with patch("services.phase_status_service.set_cached_phase_status"):
                                    db.query.return_value.filter.return_value.all.return_value = []
                                    svc.get_status_payload(42)

    db.commit.assert_not_called()
