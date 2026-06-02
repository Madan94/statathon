import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "api"))

from analysis_state.schema_state import (
    apply_effective_schema_to_payload,
    build_effective_schema,
    filter_semantic_mapping,
)


class _Col:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_effective_schema_excludes_deleted_and_excluded():
    cols = [
        _Col(id=1, name="AgeGroup", normalized_name="Age Group", is_deleted=False, is_excluded=False, is_active=True),
        _Col(id=2, name="quarter", normalized_name="quarter", is_deleted=True, is_excluded=False, is_active=False),
        _Col(id=3, name="month", normalized_name="month", is_deleted=False, is_excluded=True, is_active=False),
        _Col(id=4, name="Religion", normalized_name="Religion", is_deleted=False, is_excluded=False, is_active=True),
    ]
    assert build_effective_schema(cols) == ["Age Group", "Religion"]


def test_semantic_mapping_renamed_and_filtered():
    cols = [
        _Col(id=1, name="AgeGroup", normalized_name="Age Group", is_deleted=False, is_excluded=False, is_active=True),
        _Col(id=2, name="quarter", normalized_name="quarter", is_deleted=True, is_excluded=False, is_active=False),
    ]
    mapping = [
        {"column": "AgeGroup", "domain": "demographic"},
        {"column": "quarter", "domain": "time"},
    ]
    out = filter_semantic_mapping(mapping, cols)
    assert len(out) == 1
    assert out[0]["column"] == "Age Group"
    assert out[0]["original_column"] == "AgeGroup"
