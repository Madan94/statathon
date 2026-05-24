"""Phase 3 orchestration — detect / explain / store candidates (no destructive edits)."""

from __future__ import annotations

import pandas as pd

from core.rule_validator import normalize_schema
from core.state import AnalysisState
from imputation.imputation_manager import run_imputation_intelligence
from outliers.anomaly_handler import build_anomaly_intelligence
from validation.validation_manager import run_validation_intelligence


def run_phase3_intel(df: pd.DataFrame, schema: dict[str, str], state: AnalysisState) -> None:
    """Mutates ``state`` Phase-3 buckets only (never drops or imputes rows here)."""
    df_coerced = normalize_schema(df, schema)
    cols_meta = (
        state.semantic_profile.get("columns") if isinstance(state.semantic_profile.get("columns"), dict) else {}
    )
    dataset_ctx = dict(state.inferred_dataset_context) if isinstance(state.inferred_dataset_context, dict) else {}

    val = run_validation_intelligence(
        df_coerced,
        semantic_columns=cols_meta,
        schema_graph=state.schema_graph,
        priority_dependencies=state.dependency_graph,
        dataset_context_hint=dataset_ctx,
    )
    anomaly_bundle = build_anomaly_intelligence(df_coerced, schema)
    imb = run_imputation_intelligence(
        df_coerced,
        schema,
        cols_meta,
        state.dependency_graph,
        state.schema_graph,
        anomaly_column_blocks=anomaly_bundle.get("anomaly_results"),
    )

    state.validation_results = {
        "single_column": val.get("single_column"),
        "multi_column": val.get("multi_column"),
        "summary": val.get("summary"),
    }
    state.validation_candidates = val.get("validation_candidates") or []
    state.anomaly_results = anomaly_bundle.get("anomaly_results") or []
    state.anomaly_candidates = anomaly_bundle.get("anomaly_candidates") or []
    state.imputation_results = imb.get("imputation_results") or []
    state.imputation_candidates = imb.get("imputation_candidates") or []
    if not isinstance(getattr(state, "user_decisions", None), dict):
        state.user_decisions = {}
    state.touch()
