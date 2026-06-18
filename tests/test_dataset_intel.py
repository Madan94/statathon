import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def test_dataset_intelligence_profiles_basic():
    from profiling.dataset_intel import build_dataset_intelligence_profiles, load_default_ontology

    df = pd.DataFrame(
        {
            "household_income_usd": [10.0, 20.0, 20.0, None],
            "patient_id": ["a", "b", "a", "c"],
        }
    )
    onto = load_default_ontology()
    cols, rollup = build_dataset_intelligence_profiles(df, onto)
    assert rollup["row_count"] == 4
    assert "household_income_usd" in cols
    assert cols["patient_id"]["cardinality"] == 3
    assert "static_macro_type_scores" in rollup


def test_column_profile_embedding_snippet():
    from profiling.dataset_intel import column_profile_embedding_snippet

    s = column_profile_embedding_snippet(
        {"datatype": "float", "cardinality": 3, "semantic_hints": ["income"]},
    )
    assert "float" in s and "income" in s


def test_auxiliary_column_flagged_when_constant():
    from profiling.dataset_intel import build_dataset_intelligence_profiles, load_default_ontology

    df = pd.DataFrame(
        {
            "survey_round": [68, 68, 68, 68],
            "state_code": ["DL", "HR", "UP", "PB"],
        }
    )
    cols, _ = build_dataset_intelligence_profiles(df, load_default_ontology())
    assert cols["survey_round"]["is_auxiliary"] is True
    assert cols["survey_round"]["constant_value"] in (68, 68.0, "68")
    assert cols["survey_round"]["cardinality"] == 1
    assert cols["state_code"].get("is_auxiliary") is not True
