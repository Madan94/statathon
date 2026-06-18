"""Phase 3A orchestration."""

from __future__ import annotations

from typing import Any

import pandas as pd

from validation.multi_column.graph_validator import evaluate_graph_linked_rules
from validation.single_column.rule_engine import run_single_column_rules
from validation.context_aware_engine import _build_column_alias_map
from validation.single_column.rule_repository import load_rule_library, rules_for_column
from validation.violation_engine import build_validation_candidates
from core.column_roles import build_column_roles, is_identifier_column


def run_validation_intelligence(
    df: pd.DataFrame,
    semantic_columns: dict[str, dict[str, Any]],
    schema_graph: dict[str, Any] | None,
    priority_dependencies: dict[str, Any] | None,
    dataset_context_hint: dict[str, Any] | None = None,
    rule_library_path: Any = None,
    column_normalization: list[dict[str, Any]] | None = None,
    column_roles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Detect explain store **candidates**. Never mutates dataframe.
    """

    compiled = load_rule_library(rule_library_path)
    alias_map = _build_column_alias_map([str(c) for c in df.columns], column_normalization)
    roles = column_roles or build_column_roles(semantic_columns)

    singles: list[dict[str, Any]] = []
    meta_ctx = dataset_context_hint or {}
    seen_rule_pairs: set[tuple[str, str]] = set()
    for col in df.columns:
        if is_identifier_column(str(col), roles, semantic_columns):
            continue
        meta_base = semantic_columns.get(str(col))
        meta = dict(meta_base) if isinstance(meta_base, dict) else {}

        matched_rules = []
        for alias in alias_map.get(str(col), [str(col)]):
            for rule in rules_for_column(
                compiled,
                str(alias),
                semantic_domain=meta.get("domain"),
                semantic_subdomain=meta.get("subdomain") or meta.get("sub_domain"),
            ):
                key = (str(col), rule.rule_id)
                if key in seen_rule_pairs:
                    continue
                seen_rule_pairs.add(key)
                matched_rules.append(rule)
        if not matched_rules:
            continue
        meta["_dataset_ctx"] = meta_ctx
        singles.extend(run_single_column_rules(df, str(col), meta, matched_rules))

    multi = evaluate_graph_linked_rules(df=df, schema_graph=schema_graph, priority_dependencies=priority_dependencies)
    candidates = build_validation_candidates(singles, multi)

    return {
        "single_column": singles,
        "multi_column": multi,
        "validation_candidates": candidates,
        "summary": {
            "rules_evaluated_single": len(singles),
            "rules_evaluated_multi": len(multi),
            "candidate_rows_single": sum(len(r.get("violations") or []) for r in singles),
            "candidate_rows_multi_unique": sum(len(r.get("violations") or []) for r in multi),
        },
    }
