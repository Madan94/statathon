"""Tests for Step 7 auto-normalize column review."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.column_review_auto_service import ColumnReviewAutoService


def test_auto_apply_anomaly_no_detection():
    db = MagicMock()
    svc = ColumnReviewAutoService(db)
    with patch.object(svc.outlier, "_load_analysis"), patch.object(
        svc.outlier, "_get_phase3", return_value={"anomaly_results": []}
    ), patch.object(svc.outlier, "_find_anomaly_block", return_value=None):
        out = svc.auto_apply_anomaly(1, "expense")
    assert out["applied"] is False
    assert out["reason"] == "detection_not_run"


def test_auto_apply_anomaly_keeps_all_candidates():
    db = MagicMock()
    svc = ColumnReviewAutoService(db)
    block = {"detection_run": True, "method_selected": "Z_SCORE"}
    candidates = [{"column": "expense", "row": 1, "severity": "HIGH", "value": 999}]
    with patch.object(svc.outlier, "_load_analysis"), patch.object(
        svc.outlier, "_get_phase3", return_value={"anomaly_results": [block], "anomaly_candidates": candidates}
    ), patch.object(svc.outlier, "_find_anomaly_block", return_value=block), patch.object(
        svc, "_anomaly_candidates", return_value=candidates
    ), patch.object(
        svc.outlier, "_column_aliases", return_value={"expense"}
    ), patch.object(
        db, "query", return_value=MagicMock(filter=MagicMock(return_value=MagicMock()))
    ) as query_mock:
        query_mock.return_value.filter.return_value = []
        with patch.object(
            svc.outlier, "save_row_decisions", return_value={"saved": 1}
        ) as save_mock:
            out = svc.auto_apply_anomaly(1, "expense")
    assert out["applied"] is True
    assert out["decision"] == "KEEP"
    assert out["candidate_count"] == 1
    save_mock.assert_called_once()
    decisions = save_mock.call_args.args[2]
    assert decisions[0]["decision"] == "KEEP"


def test_auto_apply_imputation_uses_column_level_bulk():
    db = MagicMock()
    svc = ColumnReviewAutoService(db)
    with patch.object(svc.imputation, "_load"), patch.object(
        svc, "_canonical_imputation_column", return_value="wage"
    ), patch.object(
        svc, "_imputation_aliases", return_value={"wage"}
    ), patch.object(
        svc, "_imputation_missing_count", return_value=4300
    ), patch.object(
        svc, "_recommended_imputation_method", return_value="median"
    ), patch.object(
        svc.imputation, "_method_meta", return_value=(0.9, "median imputation")
    ), patch.object(
        db, "query", return_value=MagicMock(filter=MagicMock(return_value=MagicMock(count=MagicMock(return_value=0))))
    ), patch.object(
        svc.imputation, "save_decisions", return_value={"saved": 1}
    ) as save_mock:
        out = svc.auto_apply_imputation(1, "wage")
    assert out["missing_count"] == 4300
    assert out["normalized"] is True
    save_mock.assert_called_once()
    assert save_mock.call_args.kwargs.get("bulk") is True
    decisions = save_mock.call_args.kwargs.get("decisions") or save_mock.call_args.args[3] if len(save_mock.call_args.args) > 3 else save_mock.call_args.kwargs.get("decisions")
    # decisions passed as kwarg
    payload = save_mock.call_args.kwargs["decisions"]
    assert len(payload) == 1
    assert payload[0]["decision"] == "ACCEPT"
    assert payload[0].get("row_index") is None


def test_auto_apply_imputation_no_missing():
    db = MagicMock()
    svc = ColumnReviewAutoService(db)
    with patch.object(svc.imputation, "_load"), patch.object(
        svc, "_canonical_imputation_column", return_value="expense"
    ), patch.object(
        svc, "_imputation_missing_count", return_value=0
    ):
        out = svc.auto_apply_imputation(1, "expense")
    assert out["missing_count"] == 0
    assert out["normalized"] is True


def test_imputation_missing_count_resolves_column_aliases():
    db = MagicMock()
    svc = ColumnReviewAutoService(db)
    phase3 = {
        "imputation_candidates": [
            {"column": "receipt_any_aid_help", "missing_count": 10, "recommended_method": "knn"}
        ],
        "imputation_results": [],
    }
    with patch(
        "services.column_review_auto_service.build_phase3_from_relational",
        return_value=phase3,
    ), patch.object(
        svc.outlier,
        "_column_aliases",
        return_value={"receipt_any_aid_help", "Receipt_any_aid_help"},
    ):
        assert svc._imputation_missing_count(16, "Receipt_any_aid_help") == 10
        assert svc._recommended_imputation_method(16, "Receipt_any_aid_help") == "knn"
        assert svc._canonical_imputation_column(16, "Receipt_any_aid_help") == "receipt_any_aid_help"
