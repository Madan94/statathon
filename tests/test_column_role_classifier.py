"""Tests for identifier vs variable column role classification."""
from __future__ import annotations

import pandas as pd

from model.semantic_mapping_v2.column_role_classifier import classify_column_roles
from model.semantic_mapping_v2.feature_extraction import ColumnFeature
from model.semantic_mapping_v2.matching_engine import ColumnMapping


def _feat(name: str, *, dtype: str, domain: str, samples: list) -> tuple[ColumnFeature, ColumnMapping]:
    feature = ColumnFeature(
        name=name,
        normalized=name.lower(),
        dtype=dtype,
        samples=samples,
        cardinality=len(set(samples)),
        original_name=name,
    )
    mapping = ColumnMapping(
        column=name,
        normalized_name=name.lower(),
        domain=domain,
        confidence=0.9,
        source="embedding",
    )
    return feature, mapping


def test_heuristic_stratum_is_identifier():
    feat, mapping = _feat("stratum", dtype="numeric", domain="geography", samples=[1, 2, 3])
    results, stats = classify_column_roles(
        features={"stratum": feat},
        mappings={"stratum": mapping},
        usecase="consumption",
        dataset_name="test",
        use_llm=False,
    )
    assert results["stratum"].analysis_role == "identifier"
    assert stats["role_heuristic_count"] >= 1


def test_heuristic_expenditure_is_variable():
    feat, mapping = _feat(
        "monthly_food_expense",
        dtype="numeric",
        domain="food_expenditure",
        samples=[1200.0, 4500.0, 890.0],
    )
    results, _ = classify_column_roles(
        features={"monthly_food_expense": feat},
        mappings={"monthly_food_expense": mapping},
        usecase="consumption",
        dataset_name="test",
        use_llm=False,
    )
    assert results["monthly_food_expense"].analysis_role == "variable"


def test_district_numeric_codes_identifier():
    feat, mapping = _feat("District", dtype="numeric", domain="geography", samples=[1, 2, 3, 1])
    results, _ = classify_column_roles(
        features={"district": feat},
        mappings={"district": mapping},
        usecase="consumption",
        dataset_name="nss",
        use_llm=False,
    )
    assert results["district"].analysis_role == "identifier"
