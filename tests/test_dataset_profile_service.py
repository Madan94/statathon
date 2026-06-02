import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))

from services.dataset_profile_service import _health_score, profile_dict_from_legacy_dataset


class _Ds:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_health_score_average():
    assert _health_score(98.0, 96.0) == 97.0


def test_legacy_profile_dict():
    ds = _Ds(
        id=1,
        row_count=100,
        column_count=5,
        file_size=1024 * 1024,
        health_summary={
            "missing_cells": 2,
            "duplicate_rows": 1,
            "numeric_columns": 3,
            "categorical_columns": 2,
            "completeness_pct": 99.0,
            "consistency_pct": 99.0,
            "memory_usage_mb": 1.5,
        },
    )
    p = profile_dict_from_legacy_dataset(ds)
    assert p is not None
    assert p["row_count"] == 100
    assert p["health_score"] == 99.0
