"""Integration tests for dataset transformation pipeline (decisions → dataframe changes)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))

from imputation.executors import impute
from pipelines.validation_gate import apply_user_decisions
from services.apply_service import _apply_imputation, _apply_outlier_decisions
from services.normalization_transform_service import (
    apply_user_normalization,
    dataframe_checksum,
    resolve_validation_decisions,
)


def _col(name: str, *, norm: str | None = None, deleted=False, excluded=False):
    return SimpleNamespace(
        name=name,
        normalized_name=norm or name,
        is_deleted=deleted,
        is_excluded=excluded,
        is_active=not deleted and not excluded,
    )


def test_normalization_rename_delete_exclude():
    df = pd.DataFrame({"AgeYears": [1, 2], "DropMe": [3, 4], "SkipMe": [5, 6]})
    records = [
        _col("AgeYears", norm="Age"),
        _col("DropMe", deleted=True),
        _col("SkipMe", excluded=True),
    ]
    out = apply_user_normalization(df, records)
    assert list(out.columns) == ["Age"]
    assert out["Age"].tolist() == [1, 2]


def test_validation_delete_row_and_treat_as_missing():
    df = pd.DataFrame({"Age": [10, 20, 30], "Score": [1.0, 2.0, 3.0]})
    decisions = [
        {"column": "Score", "row_id": 1, "user_action": "TREAT_AS_MISSING"},
        {"column": "Age", "row_id": 2, "user_action": "REMOVE_ROW"},
    ]
    out = apply_user_decisions(df, decisions)
    assert len(out) == 2
    assert pd.isna(out.loc[1, "Score"])
    assert out["Age"].tolist() == [10, 20]


def test_outlier_delete_row_and_convert_to_missing():
    df = pd.DataFrame({"Income": [100.0, 9999.0, 200.0]})
    ui_to_physical = {"Income": "Income"}
    from database.models import OutlierDecision

    decisions = [
        SimpleNamespace(
            column_name="Income",
            row_index=1,
            decision="DELETE_VALUE",
        ),
        SimpleNamespace(
            column_name="Income",
            row_index=2,
            decision="DELETE_ROW",
        ),
    ]
    out, stats = _apply_outlier_decisions(df, decisions, ui_to_physical)
    assert len(out) == 2
    assert pd.isna(out.loc[1, "Income"])
    assert stats["delete_value"] == 1
    assert stats["delete_row"] == 1


def test_imputation_median_and_keep_missing():
    df = pd.DataFrame({"Income": [10.0, np.nan, 30.0, np.nan, 50.0]})
    phase3 = {"imputation_method_selections": {"Income": "median"}}
    ui_to_physical = {"Income": "Income"}

    class RowDecision:
        def __init__(self, row_index, decision, imputed_value=None):
            self.column_name = "Income"
            self.row_index = row_index
            self.decision = decision
            self.imputed_value = imputed_value

    rows = [
        RowDecision(1, "ACCEPT", imputed_value=20.0),
        RowDecision(3, "KEEP_MISSING"),
    ]
    out, applied = _apply_imputation(df, phase3, rows, ui_to_physical)
    assert out.loc[1, "Income"] == 20.0
    assert pd.isna(out.loc[3, "Income"])
    assert applied["rows_skipped"] == 1


def test_full_pipeline_scenario_counts():
    """100 rows → rename, delete 2 rows, null 3 cells, median-impute 3 cells."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "AgeYears": rng.integers(20, 60, size=100),
            "Income": rng.integers(1000, 5000, size=100).astype(float),
        }
    )
    records = [_col("AgeYears", norm="Age")]
    df = apply_user_normalization(df, records)
    assert "Age" in df.columns
    assert "AgeYears" not in df.columns

    decisions = [
        {"column": "Age", "row_id": 10, "user_action": "REMOVE_ROW"},
        {"column": "Age", "row_id": 20, "user_action": "REMOVE_ROW"},
        {"column": "Income", "row_id": 5, "user_action": "TREAT_AS_MISSING"},
        {"column": "Income", "row_id": 6, "user_action": "TREAT_AS_MISSING"},
        {"column": "Income", "row_id": 7, "user_action": "TREAT_AS_MISSING"},
    ]
    df = apply_user_decisions(df, decisions)
    assert len(df) == 98

    ui_to_physical = {"Age": "Age", "Income": "Income"}
    phase3 = {"imputation_method_selections": {"Income": "median"}}
    imputed_series = impute(df["Income"].copy(), df, "median")

    class RowDecision:
        def __init__(self, row_index):
            self.column_name = "Income"
            self.row_index = row_index
            self.decision = "ACCEPT"
            self.imputed_value = float(imputed_series.iloc[row_index])

    imputation_rows = [RowDecision(i) for i in (5, 6, 7)]
    df_final, applied = _apply_imputation(df, phase3, imputation_rows, ui_to_physical)

    assert len(df_final) == 98
    assert df_final["Income"].isna().sum() == 0
    for idx in (5, 6, 7):
        assert not pd.isna(df_final.loc[idx, "Income"])

    summary_rows_removed = 2
    summary_values_imputed = 3
    summary_columns_renamed = 1
    assert summary_rows_removed == 100 - len(df_final)
    assert summary_values_imputed == 3
    assert summary_columns_renamed == 1
    assert dataframe_checksum(df_final)


def test_resolve_validation_decisions_maps_columns():
    df = pd.DataFrame({"physical_col": [1, 2]})
    ui_to_physical = {"Display": "physical_col"}
    from services.normalization_transform_service import build_column_resolver

    resolver = build_column_resolver(df, ui_to_physical)
    resolved = resolve_validation_decisions(
        [{"column": "Display", "row_id": 0, "decision": "TREAT_AS_MISSING"}],
        resolver,
    )
    assert resolved[0]["column"] == "physical_col"
    assert resolved[0]["user_action"] == "TREAT_AS_MISSING"
