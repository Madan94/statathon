"""Tests for hackathon validation display sampling (250–600 random cap)."""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

from services.analysis_query import (
    VALIDATION_DISPLAY_SAMPLE_MAX,
    VALIDATION_DISPLAY_SAMPLE_MIN,
    build_display_sample_fields,
    compute_display_sample_size,
    ensure_validation_display_sample,
    list_validation_candidates_paginated,
)


def test_compute_display_sample_size_below_min():
    assert compute_display_sample_size(0) == 0
    assert compute_display_sample_size(100) == 100
    assert compute_display_sample_size(249) == 249


def test_compute_display_sample_size_in_range():
    random.seed(42)
    size = compute_display_sample_size(5000)
    assert VALIDATION_DISPLAY_SAMPLE_MIN <= size <= VALIDATION_DISPLAY_SAMPLE_MAX


def test_build_display_sample_fields_small_dataset():
    ids = list(range(1, 101))
    fields = build_display_sample_fields(ids, 100)
    assert fields["display_sample_enabled"] is False
    assert fields["display_sample_size"] == 100
    assert fields["display_sample_ids"] is None


def test_build_display_sample_fields_large_dataset():
    random.seed(7)
    ids = list(range(1, 5001))
    fields = build_display_sample_fields(ids, 5000)
    assert fields["display_sample_enabled"] is True
    assert VALIDATION_DISPLAY_SAMPLE_MIN <= fields["display_sample_size"] <= VALIDATION_DISPLAY_SAMPLE_MAX
    assert len(fields["display_sample_ids"]) == fields["display_sample_size"]
    assert len(set(fields["display_sample_ids"])) == fields["display_sample_size"]


def test_ensure_validation_display_sample_reuses_existing_ids():
    db = MagicMock()
    val_row = MagicMock()
    val_row.payload = {
        "display_sample_enabled": True,
        "display_sample_ids": [10, 20, 30],
        "display_sample_size": 3,
    }
    with patch(
        "services.analysis_query.count_all_stored_validation_candidates",
        return_value=5000,
    ), patch(
        "services.analysis_query._latest_validation_result_row",
        return_value=val_row,
    ):
        meta = ensure_validation_display_sample(db, 99)
    assert meta["display_sample_ids"] == [10, 20, 30]
    assert meta["display_sample_size"] == 3
    assert meta["full_total"] == 5000
    db.flush.assert_not_called()


def test_ensure_validation_display_sample_lazy_backfill_is_stable():
    db = MagicMock()
    all_ids = list(range(1, 3001))

    def _latest(_db, _aid):
        row = MagicMock()
        row.payload = getattr(_latest, "payload", {})
        return row if row.payload else None

    with patch(
        "services.analysis_query.count_all_stored_validation_candidates",
        return_value=3000,
    ), patch(
        "services.analysis_query._all_stored_candidate_ids",
        return_value=all_ids,
    ), patch(
        "services.analysis_query._latest_validation_result_row",
        side_effect=_latest,
    ), patch(
        "services.analysis_query.random.randint",
        return_value=400,
    ), patch(
        "services.analysis_query.random.sample",
        return_value=list(range(1, 401)),
    ):
        first = ensure_validation_display_sample(db, 7)
        _latest.payload = {
            "display_sample_enabled": True,
            "display_sample_ids": list(range(1, 401)),
            "display_sample_size": 400,
        }
        second = ensure_validation_display_sample(db, 7)

    assert first["display_sample_ids"] == list(range(1, 401))
    assert second["display_sample_ids"] == list(range(1, 401))
    assert db.flush.call_count == 1


def test_list_validation_candidates_paginated_total_matches_display_sample():
    mock_row = MagicMock()
    mock_row.kind = "single_column"
    mock_row.column_name = "age"
    mock_row.row_index = 1
    mock_row.severity = "HIGH"
    mock_row.candidate_action = "REVIEW"
    mock_row.detail = {"rule_id": "r1", "column": "age", "row": 1, "severity": "HIGH"}

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.options.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 387
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = [mock_row]

    db = MagicMock()
    sample_ids = list(range(1, 388))
    with patch(
        "services.analysis_query._display_filter_ids",
        return_value=sample_ids,
    ), patch(
        "services.analysis_query._validation_candidates_query",
        return_value=mock_query,
    ), patch(
        "services.analysis_query._candidate_to_dict",
        return_value={"column": "age", "row": 1},
    ):
        payload = list_validation_candidates_paginated(db, 42, page=1, page_size=50)

    assert payload["total"] == 387
    assert len(sample_ids) == 387
    assert payload["has_more"] is True
