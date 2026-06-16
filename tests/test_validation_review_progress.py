"""Review progress must use all persisted candidates, not the phase3 read slice."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.phase_status_service import PhaseStatusService, _candidate_key


def test_validation_review_progress_uses_all_db_candidates():
    db_candidates = [
        {"column": f"col_{i}", "row": i, "rule_id": "rule_a", "kind": "single_column"}
        for i in range(300)
    ]
    saved_decisions = []
    for i in range(300):
        d = MagicMock()
        d.column_name = f"col_{i}"
        d.row_index = i
        d.rule_id = "rule_a"
        d.rule_type = "single_column"
        saved_decisions.append(d)

    db = MagicMock()
    status_row = MagicMock()
    status_row.rule_validation_completed = False

    with patch(
        "services.phase_status_service.build_phase3_from_relational",
        return_value={
            "validation_candidates": db_candidates[:250],
            "validation_candidates_total": 654,
            "validation_candidates_reported_total": 654,
        },
    ), patch(
        "services.phase_status_service.count_validation_candidates",
        return_value=300,
    ), patch(
        "services.phase_status_service.load_all_validation_candidate_dicts",
        return_value=db_candidates,
    ), patch(
        "services.phase_status_service.load_checkpoint_phase3_overlay",
        return_value={"validation_acknowledged": True},
    ), patch.object(
        PhaseStatusService,
        "get_or_create",
        return_value=status_row,
    ):
        db.query.return_value.filter.return_value.all.return_value = saved_decisions
        progress = PhaseStatusService(db).validation_review_progress(42)

    assert progress["reviewed"] == 300
    assert progress["total"] == 300
    assert progress["reported_total"] == 654
    assert progress["truncated"] is True
    assert progress["review_complete"] is True
    assert progress["phase_complete"] is False
    assert progress["complete"] is True

    keys = {_candidate_key(c) for c in db_candidates}
    assert len(keys) == 300
