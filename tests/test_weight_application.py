"""Tests for survey weight detection and validation."""
from __future__ import annotations

import pandas as pd

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
