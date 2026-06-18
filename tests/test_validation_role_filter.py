"""Validation should skip identifier columns."""
from __future__ import annotations

import pandas as pd

from validation.context_aware_engine import run_context_aware_validation
from validation.validation_manager import run_validation_intelligence


def test_validation_skips_identifier_columns():
    df = pd.DataFrame(
        {
            "district": [1, 2, 3, 999],
            "expense": [100.0, 200.0, 150.0, 50.0],
        }
    )
    columns_meta = {
        "district": {"domain": "geography", "analysis_role": "identifier"},
        "expense": {"domain": "food_expenditure", "analysis_role": "variable"},
    }
    column_roles = {"district": "identifier", "expense": "variable"}

    out = run_context_aware_validation(
        df,
        columns_meta=columns_meta,
        column_roles=column_roles,
    )
    summary = out.get("summary") or {}
    assert summary.get("identifier_columns") == ["district"]
    assert "expense" in (summary.get("variable_columns") or [])
    for cand in out.get("validation_candidates") or []:
        assert str(cand.get("column")) != "district"


def test_legacy_manager_skips_identifier():
    df = pd.DataFrame({"district": [1, 2], "wage": [100, 200]})
    semantic = {
        "district": {"domain": "geography", "analysis_role": "identifier"},
        "wage": {"domain": "labour", "analysis_role": "variable", "subdomain": "wage"},
    }
    out = run_validation_intelligence(
        df,
        semantic_columns=semantic,
        schema_graph=None,
        priority_dependencies=None,
        column_roles={"district": "identifier", "wage": "variable"},
    )
    cols = {str(r.get("column")) for r in out.get("single_column") or []}
    assert "district" not in cols
