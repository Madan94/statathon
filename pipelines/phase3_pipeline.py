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

from core.multiplier_column import filter_candidate_rows, is_multiplier_column
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
        column_normalization=getattr(state, "column_normalization", None) or [],
    )

    # Keep legacy validation_manager call too (writes single/multi blocks
    # that downstream consumers still expect)
    val = run_validation_intelligence(
        df_coerced,
        semantic_columns=cols_meta,
        schema_graph=state.schema_graph,
        priority_dependencies=state.dependency_graph,
        dataset_context_hint=dataset_ctx,
        column_normalization=getattr(state, "column_normalization", None) or [],
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

    # ---- Persist results (exclude survey multiplier columns) ----
    state.validation_results = {
        "single_column": filter_candidate_rows(
            (gate.get("single_column") or []) + (val.get("single_column") or [])
        ),
        "multi_column": filter_candidate_rows(
            (gate.get("multi_column") or []) + (val.get("multi_column") or [])
        ),
        "rules_inventory": gate.get("rules_inventory") or [],
        "summary": {
            **(val.get("summary") or {}),
            "gate": gate.get("summary"),
        },
    }
    state.validation_candidates = filter_candidate_rows(
        gate.get("validation_candidates") or val.get("validation_candidates") or []
    )
    state.anomaly_results = [
        row
        for row in (anomaly_bundle.get("anomaly_results") or [])
        if isinstance(row, dict) and not is_multiplier_column(str(row.get("column") or ""))
    ]
    state.anomaly_candidates = [
        row
        for row in (anomaly_bundle.get("anomaly_candidates") or [])
        if isinstance(row, dict) and not is_multiplier_column(str(row.get("column") or ""))
    ]
    state.goodness_of_fit = [
        row
        for row in (anomaly_bundle.get("goodness_of_fit") or [])
        if isinstance(row, dict) and not is_multiplier_column(str(row.get("column") or ""))
    ]
    state.method_selections = {
        k: v
        for k, v in (anomaly_bundle.get("method_selections") or {}).items()
        if not is_multiplier_column(str(k))
    }
    imb_results = imb.get("imputation_results") or []
    imb_candidates = imb.get("imputation_candidates") or []
    state.imputation_results = [
        row
        for row in imb_results
        if isinstance(row, dict) and not is_multiplier_column(str(row.get("column") or ""))
    ]
    state.imputation_candidates = [
        row
        for row in imb_candidates
        if isinstance(row, dict) and not is_multiplier_column(str(row.get("column") or ""))
    ]
    if not isinstance(getattr(state, "user_decisions", None), dict):
        state.user_decisions = {}
    state.touch()
