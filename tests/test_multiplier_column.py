"""Tests for survey multiplier column detach / reattach."""
from __future__ import annotations

import pandas as pd

from core.multiplier_column import (
    MULTIPLIER_EXACT_NAMES,
    detach_multiplier_columns,
    extract_multiplier_sidecar,
    filter_rename_map,
    filter_sidecar_rows,
    is_multiplier_column,
    reattach_multiplier_columns,
    resolve_column_order_with_multipliers,
    validation_drop_indices,
)


def test_exact_name_match_only():
    assert is_multiplier_column("MULT")
    assert is_multiplier_column("multiplier")
    assert not is_multiplier_column("MULT_x")
    assert not is_multiplier_column("MULTIPLY")
    assert not is_multiplier_column("my_multiplier")


def test_detach_and_reattach():
    df = pd.DataFrame(
        {
            "state": ["A", "B"],
            "MULT": [100.0, 200.0],
            "value": [1, 2],
            "Multiplier": [1.5, 2.5],
        }
    )
    work, sidecar = detach_multiplier_columns(df)
    assert list(work.columns) == ["state", "value"]
    assert list(sidecar.columns) == ["MULT", "Multiplier"]
    final = reattach_multiplier_columns(
        work,
        sidecar,
        original_column_order=list(df.columns),
    )
    assert list(final.columns) == ["state", "MULT", "value", "Multiplier"]
    assert final["MULT"].tolist() == [100.0, 200.0]


def test_reattach_multiplier_at_original_position_with_renames():
    work = pd.DataFrame({"state_code": ["A"], "value": [2]})
    sidecar = pd.DataFrame({"MULT": [100.0]})
    original_order = ["State", "MULT", "Value"]
    upload_to_processed = {"State": "state_code", "Value": "value", "MULT": "MULT"}
    final = reattach_multiplier_columns(
        work,
        sidecar,
        original_column_order=original_order,
        upload_to_processed=upload_to_processed,
    )
    assert list(final.columns) == ["state_code", "MULT", "value"]


def test_resolve_column_order_with_multipliers():
    df = pd.DataFrame(columns=["state_code", "MULT", "value"])
    order = resolve_column_order_with_multipliers(
        df,
        ["State", "MULT", "Value"],
        {"State": "state_code", "Value": "value", "MULT": "MULT"},
    )
    assert order == ["state_code", "MULT", "value"]


def test_sidecar_row_filter():
    df = pd.DataFrame({"MULT": [1, 2, 3], "x": [10, 20, 30]})
    _, sidecar = detach_multiplier_columns(df)
    assert sidecar is not None
    filtered = filter_sidecar_rows(sidecar, [0, 2])
    assert filtered is not None
    assert filtered["MULT"].tolist() == [1, 3]


def test_validation_drop_indices():
    decisions = [
        {"user_action": "REMOVE_ROW", "row_id": 1},
        {"user_action": "KEEP", "row_id": 0},
    ]
    assert validation_drop_indices(decisions) == {1}


def test_all_exact_names_recognized():
    for name in MULTIPLIER_EXACT_NAMES:
        assert is_multiplier_column(name)


def test_pipeline_rename_skips_multiplier():
    df = pd.DataFrame({"MULT": [1, 2], "state": ["A", "B"]})
    checkpoint = {
        "column_normalization": [
            {"original_name": "MULT", "canonical_name": "survey_weight"},
            {"original_name": "state", "canonical_name": "state_code"},
        ]
    }
    from services.normalization_transform_service import apply_pipeline_column_rename

    out = apply_pipeline_column_rename(df, checkpoint)
    assert "MULT" in out.columns
    assert "survey_weight" not in out.columns
    assert "state_code" in out.columns


def test_sidecar_uses_raw_upload_name():
    df = pd.DataFrame({"Multiplier": [1.5, 2.5], "x": [10, 20]})
    sidecar = extract_multiplier_sidecar(df)
    assert sidecar is not None
    assert list(sidecar.columns) == ["Multiplier"]
    assert sidecar["Multiplier"].tolist() == [1.5, 2.5]


def test_filter_rename_map():
    blocked = filter_rename_map({"MULT": "weight", "a": "b"})
    assert blocked == {"a": "b"}
