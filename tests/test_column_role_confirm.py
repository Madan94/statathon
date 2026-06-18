"""Column role confirm must persist JSON-safe checkpoint data."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np


def test_persist_validation_only_checkpoint_is_json_safe():
    from core.state import AnalysisState
    from services.phase3_persistence_service import Phase3PersistenceService

    state = AnalysisState(dataset_id=1, analysis_id=42)
    state.validation_results = {"summary": {"rules_fired": np.int64(3)}}
    state.validation_candidates = [{"row": np.int64(7), "column": "wage", "kind": "single_column"}]

    an = MagicMock()
    an.checkpoint = {"phase3": {}}

    db = MagicMock()
    db.query.return_value.filter.return_value.delete.return_value = None
    db.query.return_value.filter.return_value.first.return_value = an
    db.query.return_value.filter.return_value.all.return_value = []

    with patch(
        "services.analysis_query.get_analysis_meta",
        return_value=an,
    ):
        Phase3PersistenceService(db).persist_validation_only(state)

    saved = an.checkpoint
    assert saved["phase3"]["validation_results"]["summary"]["rules_fired"] == 3
    assert saved["phase3"]["validation_candidates"][0]["row"] == 7
