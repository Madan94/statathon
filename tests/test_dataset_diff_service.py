"""Tests for dataset review diff aggregation."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

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
    assert inferred[0]["phase"] == "dataset_diff"


def test_merge_phase3_keeps_nonempty_relational():
    relational = {"outlier_row_decisions": {"Age": [{"row_index": 1, "decision": "DELETE_ROW"}]}}
    overlay = {"outlier_row_decisions": {}}
    merged = DatasetDiffService._merge_phase3_sources(relational, overlay)
    assert merged["outlier_row_decisions"]["Age"][0]["decision"] == "DELETE_ROW"


def test_resolve_row_index_aliases():
    assert DatasetDiffService._resolve_row_index({"row_id": 5}) == 5
    assert DatasetDiffService._resolve_row_index({"row": "7"}) == 7
    assert DatasetDiffService._resolve_row_index({}) is None


def test_resolve_decision_aliases():
    assert DatasetDiffService._resolve_decision({"user_action": "remove_row"}) == "REMOVE_ROW"
    assert DatasetDiffService._resolve_decision({"action": "DELETE_ROW"}) == "DELETE_ROW"
