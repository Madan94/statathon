"""Tests for paginated validation candidate queries."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.analysis_query import list_validation_candidates_paginated


def test_list_validation_candidates_paginated_shape():
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
    mock_query.count.return_value = 1
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = [mock_row]

    db = MagicMock()
    with patch("services.analysis_query._validation_candidates_query", return_value=mock_query):
        with patch("services.analysis_query._candidate_to_dict", return_value={"column": "age", "row": 1}):
            payload = list_validation_candidates_paginated(db, 42, page=1, page_size=50)

    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert payload["has_more"] is False
    assert len(payload["items"]) == 1
