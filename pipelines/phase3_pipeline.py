"""Phase 3 orchestration — detect / explain / store candidates (no destructive edits).

Pipeline order (per spec):

  Knowledge Graph  (already done before this phase)
        |
        v
  Context-Aware Validation Gate    <- single column + multi column rules
        |                              discovered dynamically from KG /
        |                              ontology / library / stats / archetype
        v
  Statistical Anomaly Detection    <- Z-score, IQR, isolation, ensemble
        |
        v
  Missing Value Intelligence       <- mechanism detection + CV ranking
"""

from __future__ import annotations

import pandas as pd

from core.rule_validator import normalize_schema
from core.state import AnalysisState
from imputation.imputation_manager import run_imputation_intelligence
from outliers.anomaly_handler import build_anomaly_intelligence
from pipelines.validation_gate import run_validation_gate
from validation.validation_manager import run_validation_intelligence


def run_phase3_intel(df: pd.DataFrame, schema: dict[str, str], state: AnalysisState) -> None:
    """Mutates ``state`` Phase-3 buckets only (never drops or imputes rows here)."""
    df_coerced = normalize_schema(df, schema)
    cols_meta = (
        state.semantic_profile.get("columns") if isinstance(state.semantic_profile.get("columns"), dict) else {}
    )
    dataset_ctx = dict(state.inferred_dataset_context) if isinstance(state.inferred_dataset_context, dict) else {}

    # ---- Step 1: Context-aware validation gate (KG → rules → violations) ----
    column_profiles = (
        state.semantic_profile.get("column_profiles")
        if isinstance(state.semantic_profile, dict)
        else None
    )
    unified_domains = (
        state.semantic_profile.get("unified_domains")
        if isinstance(state.semantic_profile, dict)
        else None
    )
    archetypes = (
        dataset_ctx.get("archetypes")
        if isinstance(dataset_ctx, dict)
        else None
    )

    gate = run_validation_gate(
        df_coerced,
        columns_meta=cols_meta,
        schema_graph=state.schema_graph,
        priority_dependencies=state.dependency_graph,
        column_profiles=column_profiles,
        unified_domains=unified_domains,
        archetypes=archetypes,
        analysis_id=getattr(state, "analysis_id", None),
    )

    # Keep legacy validation_manager call too (writes single/multi blocks
    # that downstream consumers still expect)
    val = run_validation_intelligence(
        df_coerced,
        semantic_columns=cols_meta,
        schema_graph=state.schema_graph,
        priority_dependencies=state.dependency_graph,
        dataset_context_hint=dataset_ctx,
    )

    # ---- Step 2: Goodness-of-fit + method confidence (no auto detection) ----
    anomaly_bundle = build_anomaly_intelligence(df_coerced, schema)

    # ---- Step 3: Missing value intelligence (scoring only — no outlier signal yet) ----
    imb = run_imputation_intelligence(
        df_coerced,
        schema,
        cols_meta,
        state.dependency_graph,
        state.schema_graph,
        anomaly_column_blocks=None,
    )

    # ---- Persist results ----
    state.validation_results = {
        "single_column": (gate.get("single_column") or []) + (val.get("single_column") or []),
        "multi_column": (gate.get("multi_column") or []) + (val.get("multi_column") or []),
        "summary": {
            **(val.get("summary") or {}),
            "gate": gate.get("summary"),
        },
    }
    # Validation gate's candidates (KG-driven) take precedence; fall back to legacy.
    state.validation_candidates = (
        gate.get("validation_candidates")
        or val.get("validation_candidates")
        or []
    )
    state.anomaly_results = anomaly_bundle.get("anomaly_results") or []
    state.anomaly_candidates = anomaly_bundle.get("anomaly_candidates") or []
    state.goodness_of_fit = anomaly_bundle.get("goodness_of_fit") or []
    state.method_selections = anomaly_bundle.get("method_selections") or {}
    state.imputation_results = imb.get("imputation_results") or []
    state.imputation_candidates = imb.get("imputation_candidates") or []
    if not isinstance(getattr(state, "user_decisions", None), dict):
        state.user_decisions = {}
    state.touch()
