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


def test_semantic_mapping_v2_canonical_column_key():
    """V2 stores canonical keys; filter must resolve via original_name."""
    cols = [
        _Col(id=1, name="PERSON_ID", normalized_name="Person Id", is_deleted=False, is_excluded=False, is_active=True),
        _Col(id=2, name="STATE_CODE", normalized_name="State Code", is_deleted=False, is_excluded=False, is_active=True),
    ]
    mapping = [
        {
            "column": "person_identifier",
            "original_name": "PERSON_ID",
            "domain": "identifier",
            "source": "llm",
            "confidence": 0.91,
        },
        {
            "column": "state_code",
            "original_name": "STATE_CODE",
            "domain": "geography",
            "source": "embedding",
            "confidence": 0.88,
        },
    ]
    out = filter_semantic_mapping(mapping, cols)
    assert len(out) == 2
    by_col = {row["column"]: row for row in out}
    assert by_col["Person Id"]["domain"] == "identifier"
    assert by_col["Person Id"]["source"] == "llm"
    assert by_col["State Code"]["domain"] == "geography"


def test_semantic_mapping_canonical_via_column_normalization():
    cols = [
        _Col(id=1, name="PERSON_ID", normalized_name="Person Id", is_deleted=False, is_excluded=False, is_active=True),
    ]
    mapping = [{"column": "person_identifier", "domain": "identifier", "source": "llm"}]
    col_norm = [{"original_name": "PERSON_ID", "canonical_name": "person_identifier"}]
    out = filter_semantic_mapping(mapping, cols, column_normalization=col_norm)
    assert len(out) == 1
    assert out[0]["column"] == "Person Id"


def test_filter_column_profiles_snake_case_keys():
    from analysis_state.schema_state import filter_column_profiles

    cols = [
        _Col(
            id=1,
            name="Centre_Round",
            normalized_name="Centre_Round",
            is_deleted=False,
            is_excluded=False,
            is_active=True,
        ),
        _Col(
            id=2,
            name="District",
            normalized_name="District",
            is_deleted=False,
            is_excluded=False,
            is_active=True,
        ),
    ]
    profiles = {
        "centre_round": {
            "datatype": "numeric",
            "missing_ratio": 0.0,
            "cardinality": 12,
            "top_values": [{"value": "1", "count": 3}],
        },
        "district": {
            "datatype": "string",
            "missing_ratio": 0.05,
            "cardinality": 8,
            "top_values": [{"value": "North", "count": 2}],
        },
    }
    out = filter_column_profiles(profiles, cols)
    assert len(out) == 2
    assert out["Centre_Round"]["cardinality"] == 12
    assert out["District"]["cardinality"] == 8


def test_filter_phase3_anomaly_results_snake_case_keys():
    from analysis_state.schema_state import filter_phase3_by_columns

    cols = [
        _Col(
            id=1,
            name="Stratum",
            normalized_name="Stratum",
            is_deleted=False,
            is_excluded=False,
            is_active=True,
        ),
        _Col(
            id=2,
            name="District",
            normalized_name="District",
            is_deleted=False,
            is_excluded=False,
            is_active=True,
        ),
    ]
    phase3 = {
        "anomaly_results": [
            {
                "column": "stratum",
                "recommended": "Z_SCORE",
                "z_score_confidence": 82,
                "iqr_confidence": 71,
            },
            {
                "column": "district",
                "recommended": "IQR",
                "z_score_confidence": 60,
                "iqr_confidence": 88,
            },
        ],
        "goodness_of_fit": [
            {"column": "stratum", "skewness": 0.1},
            {"column": "district", "skewness": 1.2},
        ],
        "method_selections": {"stratum": "Z_SCORE"},
    }
    out = filter_phase3_by_columns(phase3, cols)
    by_col = {row["column"]: row for row in out["anomaly_results"]}
    assert set(by_col) == {"Stratum", "District"}
    assert by_col["Stratum"]["recommended"] == "Z_SCORE"
    assert by_col["Stratum"]["original_column"] == "stratum"
    gof_by_col = {row["column"]: row for row in out["goodness_of_fit"]}
    assert gof_by_col["Stratum"]["skewness"] == 0.1
    assert out["method_selections"]["Stratum"] == "Z_SCORE"
