"""Validation demo noise — jury demo inject / refresh / remove."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_API = _REPO / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from validation.rule_discovery import DiscoveredRule


def test_validation_demo_noise_enabled_flag():
    from core.feature_flags import validation_demo_noise_enabled

    with patch.dict(os.environ, {"VALIDATION_DEMO_NOISE": "1"}):
        assert validation_demo_noise_enabled() is True
    with patch.dict(os.environ, {"VALIDATION_DEMO_NOISE": "0"}):
        assert validation_demo_noise_enabled() is False


def test_violating_value_for_rule_numeric_between():
    from services.validation_demo_noise_service import violating_value_for_rule

    rule = DiscoveredRule(
        rule_id="r1",
        kind="single_column",
        rule_type="numeric_between",
        columns=["expense"],
        params={"min": 0.0, "max": 100.0},
    )
    bad = violating_value_for_rule(rule)
    assert bad is not None
    assert float(bad) > 100.0


def test_build_demo_noise_rows_from_rules():
    from services.validation_demo_noise_service import DEMO_NOISE_COL, build_demo_noise_rows

    df = pd.DataFrame({"expense": [10.0, 20.0, 30.0], "district": [1, 2, 3]})
    rules = [
        DiscoveredRule(
            rule_id="r1",
            kind="single_column",
            rule_type="numeric_between",
            columns=["expense"],
            params={"min": 0.0, "max": 100.0},
        ),
    ]
    columns_meta = {
        "expense": {"domain": "food_expenditure", "analysis_role": "variable"},
        "district": {"domain": "geography", "analysis_role": "identifier"},
    }
    rows = build_demo_noise_rows(
        df,
        rules,
        columns_meta=columns_meta,
        column_roles={"expense": "variable", "district": "identifier"},
    )
    assert len(rows) >= 1
    assert all(r.get(DEMO_NOISE_COL) is True for r in rows)
    assert rows[0]["expense"] > 100.0


def test_inject_raises_when_feature_disabled():
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    with patch.dict(os.environ, {"VALIDATION_DEMO_NOISE": "0"}):
        svc = ValidationDemoNoiseService(MagicMock())
        with pytest.raises(PermissionError):
            svc.inject(1)


def test_refresh_raises_without_active_noise():
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    db = MagicMock()
    an = MagicMock()
    an.status = "complete"
    an.checkpoint = {"demo_noise": {}}

    with patch.dict(os.environ, {"VALIDATION_DEMO_NOISE": "1"}):
        with patch(
            "services.validation_demo_noise_service.get_analysis_meta",
            return_value=an,
        ), patch(
            "services.validation_demo_noise_service.load_analysis_checkpoint",
            return_value={"demo_noise": {}},
        ):
            svc = ValidationDemoNoiseService(db)
            with pytest.raises(ValueError, match="Inject demo noise"):
                svc.refresh(42)


def test_inject_append_rows_and_mark_active():
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    df = pd.DataFrame({"monthly_expense": [100.0, 200.0]})
    noise_rows = [{"monthly_expense": 99999.0, "_statathon_demo_noise": True}]
    an = MagicMock()
    an.status = "complete"
    an.id = 7
    an.dataset_id = 3
    an.checkpoint = {}
    checkpoint = {
        "semantic_mapping": [
            {
                "column": "monthly_expense",
                "domain": "food_expenditure",
                "analysis_role": "variable",
            }
        ],
        "schema_graph": {},
        "priority_dependencies": {},
        "demo_noise": {},
    }

    db = MagicMock()

    with patch.dict(os.environ, {"VALIDATION_DEMO_NOISE": "1"}):
        with patch(
            "services.validation_demo_noise_service.get_analysis_meta",
            return_value=an,
        ), patch(
            "services.validation_demo_noise_service.load_analysis_checkpoint",
            return_value=checkpoint,
        ), patch(
            "services.validation_demo_noise_service._load_demo_dataframe",
            return_value=df.copy(),
        ), patch(
            "services.validation_demo_noise_service.discover_all_rules",
            return_value=[
                DiscoveredRule(
                    rule_id="r1",
                    kind="single_column",
                    rule_type="numeric_between",
                    columns=["monthly_expense"],
                    params={"min": 0.0, "max": 500.0},
                )
            ],
        ), patch(
            "services.validation_demo_noise_service.build_demo_noise_rows",
            return_value=noise_rows,
        ), patch(
            "services.validation_demo_noise_service._persist_normalized_snapshot",
            return_value={"version": 2},
        ):
            svc = ValidationDemoNoiseService(db)
            out = svc.inject(7)

    assert out["success"] is True
    assert out["rows_added"] == 1
    assert out["pending_refresh"] is True
    assert an.checkpoint.get("demo_noise", {}).get("active") is True
    db.commit.assert_called_once()


def test_refresh_reruns_validation():
    from core.state import AnalysisState
    from services.validation_demo_noise_service import ValidationDemoNoiseService

    df = pd.DataFrame({"monthly_expense": [100.0, 200.0, 99999.0]})
    an = MagicMock()
    an.status = "complete"
    an.id = 7
    an.dataset_id = 3
    an.checkpoint = {
        "demo_noise": {"active": True, "rows_added": 1, "pending_refresh": True},
        "semantic_mapping": [
            {
                "column": "monthly_expense",
                "domain": "food_expenditure",
                "analysis_role": "variable",
            }
        ],
    }
    state = AnalysisState(dataset_id=3, analysis_id=7)
    state.validation_candidates = [{"column": "monthly_expense", "row": 2}]
    state.validation_results = {"summary": {"gate": {"rules_fired": 1}}}

    db = MagicMock()

    with patch.dict(os.environ, {"VALIDATION_DEMO_NOISE": "1"}):
        with patch(
            "services.validation_demo_noise_service.get_analysis_meta",
            return_value=an,
        ), patch(
            "services.validation_demo_noise_service.load_analysis_checkpoint",
            return_value=dict(an.checkpoint),
        ), patch(
            "services.validation_demo_noise_service._load_demo_dataframe",
            return_value=df,
        ), patch(
            "services.validation_demo_noise_service._rerun_validation_for_df",
            return_value=state,
        ):
            svc = ValidationDemoNoiseService(db)
            out = svc.refresh(7)

    assert out["success"] is True
    assert out["candidate_count"] == 1
    db.commit.assert_called_once()
