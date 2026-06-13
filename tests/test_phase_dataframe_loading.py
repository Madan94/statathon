"""Ensure each phase loads the correct working snapshot stage."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))

from services.analysis_dataframe_service import WORKING_STAGE_BY_PHASE


def test_working_stage_mapping():
    assert WORKING_STAGE_BY_PHASE["anomaly"] == "validated"
    assert WORKING_STAGE_BY_PHASE["imputation"] == "anomaly_reviewed"
    assert WORKING_STAGE_BY_PHASE["review"] == "imputed"
    assert WORKING_STAGE_BY_PHASE["validation"] == "normalized"
