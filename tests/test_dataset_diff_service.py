"""Tests for dataset review diff aggregation."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))

from review.dataset_diff_service import DatasetDiffService


class _FakeDb:
    pass


def test_infer_rows_removed_from_dataframes():
    svc = DatasetDiffService(_FakeDb())
    original = pd.DataFrame({"Age": [10, 20, 30], "Score": [1, 2, 3]})
    processed = pd.DataFrame({"Age": [10, 30], "Score": [1, 3]})
    inferred = svc._infer_rows_removed(original, processed)
    assert len(inferred) == 1
    assert inferred[0]["row_index"] == 1


def test_merge_phase3_keeps_nonempty_relational():
    relational = {"outlier_row_decisions": {"Age": [{"row_index": 1, "decision": "DELETE_ROW"}]}}
    overlay = {"outlier_row_decisions": {}}
    merged = DatasetDiffService._merge_phase3_sources(relational, overlay)
    assert merged["outlier_row_decisions"]["Age"][0]["decision"] == "DELETE_ROW"


def test_build_diff_metrics_from_snapshots_only():
    svc = DatasetDiffService(_FakeDb())
    original = pd.DataFrame({"person_id": [1, 2, 3], "age": [10, 20, 30]})
    processed = pd.DataFrame({"Person Identifier": [1, 2], "Age": [10, 20]})

    with patch.object(svc, "_normalization_changes", return_value={
        "columns_renamed": [
            {"from": "person_id", "to": "Person Identifier"},
            {"from": "age", "to": "Age"},
        ],
        "columns_removed": [],
        "columns_excluded": [],
    }), patch.object(svc, "_validation_changes", return_value={
        "rule_violations_fixed": 0,
        "values_changed": [],
        "rules_applied": [],
    }), patch.object(svc, "_anomaly_changes", return_value={
        "anomalies_processed": 0,
        "anomalies_handled": [],
        "rows_removed": [],
        "values_set_missing": [],
    }), patch.object(svc, "_imputation_changes", return_value={
        "values_imputed": 0,
        "missing_values_imputed": [],
    }):
        payload = svc.build_diff(1, original, processed)

    summary = payload["summary"]
    assert summary["rows_before"] == 3
    assert summary["rows_after"] == 2
    assert summary["rows_removed"] == 1
    assert summary["columns_removed"] == 0
    assert summary["columns_renamed"] == 2
    assert summary["columns_before"] == 2
    assert summary["columns_after"] == 2


def test_normalization_dedupes_renames():
    svc = DatasetDiffService(_FakeDb())
    db = MagicMock()
    svc.db = db

    col = MagicMock()
    col.name = "person_id"
    col.normalized_name = "Person Identifier"
    col.is_deleted = False
    col.is_excluded = False

    with patch(
        "review.dataset_diff_service.NormalizationService"
    ) as norm_cls, patch(
        "services.analysis_query.load_checkpoint_top_keys",
        return_value={"column_normalization": [
            {"original_name": "person_id", "normalized_name": "Person Identifier"},
        ]},
    ), patch(
        "review.dataset_diff_service.load_analysis_checkpoint",
        return_value={},
    ):
        norm_cls.return_value._ensure_columns_seeded.return_value = [col]
        result = svc._normalization_changes(1)

    assert len(result["columns_renamed"]) == 1
    assert result["columns_removed"] == []


def test_normalization_prefers_db_rename_over_checkpoint_alias():
    svc = DatasetDiffService(_FakeDb())
    db = MagicMock()
    svc.db = db

    col = MagicMock()
    col.name = "person_id"
    col.normalized_name = "Person Identifier"
    col.is_deleted = False
    col.is_excluded = False

    with patch(
        "review.dataset_diff_service.NormalizationService"
    ) as norm_cls, patch(
        "services.analysis_query.load_checkpoint_top_keys",
        return_value={"column_normalization": [
            {"original_name": "person_id", "canonical_name": "person_identifier"},
        ]},
    ), patch(
        "review.dataset_diff_service.load_analysis_checkpoint",
        return_value={},
    ):
        norm_cls.return_value._ensure_columns_seeded.return_value = [col]
        result = svc._normalization_changes(1)

    assert len(result["columns_renamed"]) == 1
    assert result["columns_renamed"][0] == {"from": "person_id", "to": "Person Identifier"}


def test_normalization_skips_multiplier_renames():
    svc = DatasetDiffService(_FakeDb())
    db = MagicMock()
    svc.db = db

    mult = MagicMock()
    mult.name = "MULT"
    mult.normalized_name = "survey_weight"
    mult.is_deleted = False
    mult.is_excluded = True

    with patch(
        "review.dataset_diff_service.NormalizationService"
    ) as norm_cls, patch(
        "services.analysis_query.load_checkpoint_top_keys",
        return_value={},
    ), patch(
        "review.dataset_diff_service.load_analysis_checkpoint",
        return_value={},
    ):
        norm_cls.return_value._ensure_columns_seeded.return_value = [mult]
        result = svc._normalization_changes(1)

    assert result["columns_renamed"] == []
    assert result["columns_excluded"] == []
