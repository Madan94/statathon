"""Tests for global column dictionary parse, merge, lookup, and normalization apply."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))

from services.column_dictionary_service import (  # noqa: E402
    ColumnDictionaryError,
    ColumnDictionaryService,
    lookup,
    merge_mappings,
    parse_flat_dictionary,
)
from services.normalization_service import NormalizationService  # noqa: E402


class _Col:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_parse_valid_flat_dictionary():
    raw = {"LFPR": "Labour Force Participation Rate", " dist_cd ": "District Code"}
    parsed = parse_flat_dictionary(raw)
    assert parsed == {
        "LFPR": "Labour Force Participation Rate",
        "dist_cd": "District Code",
    }


def test_parse_rejects_nested_values():
    with pytest.raises(ColumnDictionaryError, match="Nested"):
        parse_flat_dictionary({"bad": {"nested": True}})


def test_parse_rejects_non_object_root():
    with pytest.raises(ColumnDictionaryError, match="JSON object"):
        parse_flat_dictionary([{"a": "b"}])


def test_merge_keep_existing_case_insensitive():
    existing = {"LFPR": "Labour Force Participation Rate"}
    incoming = {"lfpr": "Other Name", "state_ut": "State Ut"}
    merged, stats = merge_mappings(existing, incoming)
    assert merged["LFPR"] == "Labour Force Participation Rate"
    assert merged["state_ut"] == "State Ut"
    assert stats["added"] == 1
    assert stats["skipped"] == 1
    assert stats["total"] == 2


def test_lookup_case_insensitive_trim():
    mappings = {"LFPR": "Labour Force Participation Rate"}
    assert lookup("  lfpr ", mappings) == "Labour Force Participation Rate"
    assert lookup("missing", mappings) is None


def test_apply_to_columns_overrides_normalized_name():
    col = _Col(id=1, name="LFPR", normalized_name="Lfp R", is_deleted=False, is_excluded=False, is_active=True)
    svc = ColumnDictionaryService(MagicMock())
    stats = svc.apply_to_columns([col], {"lfpr": "Labour Force Participation Rate"})
    assert stats["matched_count"] == 1
    assert col.normalized_name == "Labour Force Participation Rate"


def test_apply_to_analysis_no_dictionary_is_noop(monkeypatch):
    db = MagicMock()
    svc = NormalizationService(db)
    col = _Col(id=1, name="LFPR", normalized_name="Lfp R", is_deleted=False, is_excluded=False, is_active=True)

    monkeypatch.setattr(svc, "_ensure_columns_seeded", lambda _aid: [col])
    monkeypatch.setattr(
        ColumnDictionaryService,
        "get_mappings",
        lambda self: {},
    )
    monkeypatch.setattr(
        ColumnDictionaryService,
        "get_global_summary",
        lambda self: {"version": 0, "total_keys": 0, "updated_at": None},
    )

    result = svc.apply_dictionary_to_analysis(1)
    assert result["matched"] == 0
    assert result["unmatched"] == 1
    assert col.normalized_name == "Lfp R"


def test_apply_to_analysis_overrides_pipeline_name(monkeypatch):
    db = MagicMock()
    svc = NormalizationService(db)
    col = _Col(id=1, name="dist_cd", normalized_name="Dist Cd", is_deleted=False, is_excluded=False, is_active=True)
    refreshed = [
        _Col(
            id=1,
            name="dist_cd",
            normalized_name="District Code",
            is_deleted=False,
            is_excluded=False,
            is_active=True,
        )
    ]

    monkeypatch.setattr(svc, "_ensure_columns_seeded", lambda _aid: [col])
    monkeypatch.setattr(svc.columns, "list_for_analysis", lambda _aid: refreshed)
    monkeypatch.setattr(
        ColumnDictionaryService,
        "get_mappings",
        lambda self: {"dist_cd": "District Code"},
    )
    monkeypatch.setattr(
        ColumnDictionaryService,
        "get_global_summary",
        lambda self: {"version": 1, "total_keys": 1, "updated_at": None},
    )

    result = svc.apply_dictionary_to_analysis(42)
    assert result["matched"] == 1
    assert result["columns"][0]["dictionary_mapped"] is True
    assert result["columns"][0]["match_method"] == "column_dictionary"
    db.commit.assert_called_once()


def test_upload_merge_stats_from_bytes():
    db = MagicMock()
    row = MagicMock()
    row.mappings = {"LFPR": "Labour Force Participation Rate"}
    row.version = 2
    row.updated_at = None
    db.query.return_value.filter.return_value.first.return_value = row

    svc = ColumnDictionaryService(db)
    payload = json.dumps(
        {"lfpr": "Ignored", "state_ut": "State Ut"},
    ).encode("utf-8")
    result = svc.upload_and_merge(payload, user_id=7)

    assert result["added"] == 1
    assert result["skipped"] == 1
    assert result["total_keys"] == 2
    assert result["version"] == 3
    db.commit.assert_called_once()
