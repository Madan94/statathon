"""Step 7 phase status should skip identifier and auxiliary columns."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.column_roles import build_column_roles, is_auxiliary_profile, role_from_meta, should_review_column_analysis
from services.phase_status_service import PhaseStatusService


def test_role_from_meta_reads_analysis_role():
    assert role_from_meta({"analysis_role": "identifier"}) == "identifier"
    assert build_column_roles({"district": {"analysis_role": "identifier"}}) == {
        "district": "identifier",
    }


def test_is_auxiliary_profile_from_flag_and_cardinality():
    assert is_auxiliary_profile({"is_auxiliary": True}) is True
    assert is_auxiliary_profile({"missing_ratio": 0, "cardinality": 1}) is True
    assert is_auxiliary_profile({"missing_ratio": 0.1, "cardinality": 1}) is False
    assert is_auxiliary_profile(None) is False


def test_should_review_column_analysis_excludes_identifier_and_auxiliary():
    columns_meta = {
        "district": {"analysis_role": "identifier"},
        "expense": {"analysis_role": "variable"},
        "survey_round": {"analysis_role": "variable"},
    }
    column_profiles = {
        "survey_round": {"is_auxiliary": True, "missing_ratio": 0, "cardinality": 1},
    }
    assert should_review_column_analysis("district", columns_meta, column_profiles) is False
    assert should_review_column_analysis("survey_round", columns_meta, column_profiles) is False
    assert should_review_column_analysis("expense", columns_meta, column_profiles) is True


def test_recompute_imputation_columns_skips_identifier_with_missing():
    phase3 = {
        "imputation_results": [
            {"column": "district"},
            {"column": "expense"},
        ],
        "imputation_candidates": [
            {"column": "district", "missing_count": 5},
            {"column": "expense", "missing_count": 2},
        ],
    }
    checkpoint = {
        "semantic_mapping": [
            {"column": "district", "analysis_role": "identifier"},
            {"column": "expense", "analysis_role": "variable"},
        ],
    }
    db = MagicMock()
    status_row = MagicMock()

    with patch(
        "services.phase_status_service.build_phase3_from_relational",
        return_value=phase3,
    ), patch(
        "services.phase_status_service.load_checkpoint_phase3_overlay",
        return_value={},
    ), patch(
        "services.phase_status_service.load_analysis_checkpoint",
        return_value=checkpoint,
    ), patch(
        "services.phase_status_service._alias_groups",
        return_value={"district": {"district"}, "expense": {"expense"}},
    ), patch.object(
        PhaseStatusService,
        "get_or_create",
        return_value=status_row,
    ), patch.object(
        PhaseStatusService,
        "_upsert_column_review",
    ) as upsert:
        db.query.return_value.filter.return_value.distinct.return_value = []
        result = PhaseStatusService(db).recompute_imputation_columns(1, persist=True)

    assert result["columns_total"] == 1
    assert result["complete"] is False
    assert result["pending_columns"] == ["expense"]
    upsert_calls = upsert.call_args_list
    district_skip = next(c for c in upsert_calls if c.args[2] == "district")
    assert district_skip.kwargs["status"] == "auto_reviewed"


def test_recompute_imputation_columns_complete_when_only_skipped_remain():
    phase3 = {
        "imputation_results": [{"column": "district"}],
        "imputation_candidates": [{"column": "district", "missing_count": 3}],
    }
    checkpoint = {
        "semantic_mapping": [{"column": "district", "analysis_role": "identifier"}],
    }
    db = MagicMock()
    status_row = MagicMock()

    with patch(
        "services.phase_status_service.build_phase3_from_relational",
        return_value=phase3,
    ), patch(
        "services.phase_status_service.load_checkpoint_phase3_overlay",
        return_value={},
    ), patch(
        "services.phase_status_service.load_analysis_checkpoint",
        return_value=checkpoint,
    ), patch(
        "services.phase_status_service._alias_groups",
        return_value={"district": {"district"}},
    ), patch.object(
        PhaseStatusService,
        "get_or_create",
        return_value=status_row,
    ), patch.object(
        PhaseStatusService,
        "_upsert_column_review",
    ):
        db.query.return_value.filter.return_value.distinct.return_value = []
        result = PhaseStatusService(db).recompute_imputation_columns(1, persist=True)

    assert result["columns_total"] == 0
    assert result["complete"] is True
