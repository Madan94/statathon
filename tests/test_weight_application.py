"""Tests for survey weight detection, application, and invalidation."""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from services.weight_workflow_service import invalidate_weight_after_upstream_refresh, semantic_mapping_dict
from weights.weight_applier import apply_weight_to_dataset
from weights.weight_detector import detect_weight_columns
from weights.weight_recommender import recommend_weight
from weights.weight_statistics import compare_weighted_unweighted
from weights.weight_validator import validate_weight_column


def test_detect_weight_columns_by_name():
    df = pd.DataFrame(
        {
            "income": [1000, 2000, 3000, 4000],
            "hh_weight": [1.2, 0.8, 1.5, 1.1],
            "region": ["A", "B", "A", "C"],
        }
    )
    detections = detect_weight_columns(df, {"income": "numeric", "hh_weight": "numeric"})
    assert detections
    assert detections[0]["column"] == "hh_weight"
    assert detections[0]["confidence"] >= 0.5


def test_detect_weight_columns_with_semantic_mapping():
    df = pd.DataFrame(
        {
            "expansion_factor": [1.1, 1.3, 0.9, 1.2],
            "income": [1000, 2000, 3000, 4000],
        }
    )
    semantic = {
        "expansion_factor": {
            "column": "expansion_factor",
            "domain": "survey_design",
            "subdomain": "expansion_factors",
        }
    }
    detections = detect_weight_columns(
        df,
        {"expansion_factor": "numeric", "income": "numeric"},
        semantic_mapping=semantic,
    )
    assert detections
    assert detections[0]["column"] == "expansion_factor"
    assert detections[0]["signals"]["semantic"] >= 0.9


def test_validate_weight_column_passes():
    df = pd.DataFrame({"hh_weight": [1.0, 1.2, 0.9, 1.1, 1.3]})
    result = validate_weight_column(df, "hh_weight")
    assert result["valid"] is True
    assert result["quality_score"] >= 0.8


def test_recommend_weight_picks_best():
    candidates = [
        {"column": "sample_weight", "confidence": 0.82},
        {"column": "hh_weight", "confidence": 0.96},
    ]
    validations = {
        "sample_weight": {"quality_score": 0.7, "coverage": 0.9, "valid": True},
        "hh_weight": {"quality_score": 0.93, "coverage": 0.99, "valid": True},
    }
    rec = recommend_weight(candidates, validations)
    assert rec is not None
    assert rec["recommended"] == "hh_weight"


def test_compare_weighted_unweighted_metrics():
    df = pd.DataFrame(
        {
            "income": [1000, 2000, 3000, 4000],
            "hh_weight": [1.0, 1.0, 2.0, 2.0],
        }
    )
    out = compare_weighted_unweighted(df, "hh_weight", {"income": "numeric"})
    assert out["metrics"]
    assert out["metrics"][0]["unweighted"] != out["metrics"][0]["weighted"]


def test_apply_weight_creates_parallel_columns():
    df = pd.DataFrame(
        {
            "income": [1000, 2000, 3000, 4000],
            "hh_weight": [1.0, 1.0, 2.0, 2.0],
            "region": ["A", "B", "A", "B"],
        }
    )
    weighted_df, meta = apply_weight_to_dataset(
        df,
        "hh_weight",
        schema={"income": "numeric", "hh_weight": "numeric", "region": "categorical"},
    )
    assert "income_weighted" in weighted_df.columns
    assert "hh_weight" in weighted_df.columns
    assert df["income"].tolist() == weighted_df["income"].tolist()
    assert "region_weighted" not in weighted_df.columns
    assert meta["transform_mode"] == "parallel_columns"
    assert "income_weighted" in meta["weighted_columns"]


def test_semantic_mapping_dict_checkpoint_fallback():
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = []

    from services import weight_workflow_service as wws

    original = wws.load_analysis_checkpoint
    try:
        wws.load_analysis_checkpoint = lambda _db, _aid: {
            "semantic_mapping": [{"column": "wt", "domain": "sampling"}]
        }
        mapping = semantic_mapping_dict(db, 1)
        assert "wt" in mapping
        assert mapping["wt"]["domain"] == "sampling"
    finally:
        wws.load_analysis_checkpoint = original


def test_invalidate_weight_after_upstream_refresh_resets_flags():
    class PhaseRow:
        weight_application_completed = True
        dataset_review_completed = True
        updated_at = None

    class AppRow:
        applied = True
        ignored = False
        weight_column = "hh_weight"
        comparison = {"metrics": []}
        meta = {"source_imputed_snapshot_id": 10}
        updated_at = None

    db = MagicMock()
    app = AppRow()
    phase_row = PhaseRow()

    app_query = MagicMock()
    app_query.filter.return_value.first.return_value = app

    snap_query = MagicMock()
    snap_query.filter.return_value.delete.return_value = 1

    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        if name == "WeightApplication":
            return app_query
        if name == "DatasetLineageSnapshot":
            return snap_query
        return MagicMock()

    db.query.side_effect = query_side_effect

    from services import weight_workflow_service as wws

    original_ps = wws.PhaseStatusService

    class FakePhaseStatus:
        def __init__(self, _db):
            pass

        def get_or_create(self, _analysis_id):
            return phase_row

    try:
        wws.PhaseStatusService = FakePhaseStatus
        reapply = invalidate_weight_after_upstream_refresh(db, 42)
        assert reapply == "hh_weight"
        assert phase_row.weight_application_completed is False
        assert phase_row.dataset_review_completed is False
        assert app.applied is False
        assert app.meta.get("stale") is True
    finally:
        wws.PhaseStatusService = original_ps
