"""Relationships from KG / blueprint / semantic graph for validators."""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from validation.multi_column.dependency_validator import multi_column_rule_confidence


def extract_column_edges(schema_graph: dict[str, Any], priority_dependencies: dict[str, Any]) -> list[dict[str, Any]]:
    edges_out: list[dict[str, Any]] = []

    sg = schema_graph or {}
    for e in sg.get("edges") or []:
        if not isinstance(e, dict):
            continue
        src = e.get("source")
        tgt = e.get("target")
        if src and tgt:
            edges_out.append(
                {
                    "source_column": src,
                    "target_column": tgt,
                    "weight": float(e.get("weight") or e.get("strength") or 0),
                    "type": str(e.get("relationship_type") or "schema_graph"),
                    "signals": {},
                }
            )

    prio = priority_dependencies if isinstance(priority_dependencies, dict) else {}
    for dependent_column, influencers in prio.items():
        if not isinstance(influencers, list):
            continue
        for inf in influencers:
            if not isinstance(inf, dict):
                continue
            src = inf.get("column") or inf.get("source_column")
            if not src:
                continue
            edges_out.append(
                {
                    "source_column": src,
                    "target_column": dependent_column,
                    "weight": float(inf.get("score") or inf.get("influence_score") or 0),
                    "type": "priority_dependency",
                    "signals": {
                        "embedding_similarity": inf.get("embedding_similarity"),
                        "dependency_reason": inf.get("dependency_reason"),
                    },
                }
            )

    return edges_out


def _norm_employment(val) -> str:
    if pd.isna(val):
        return ""
    return str(val).strip().lower()


def _col_by_keyword(columns: list[str], keys: tuple[str, ...]) -> str | None:
    for c in columns:
        cl = str(c).lower()
        if any(k in cl for k in keys):
            return c
    return None


def run_minor_full_time(df: pd.DataFrame, age_c: str | None, emp_c: str | None) -> list[int]:
    if not age_c or not emp_c:
        return []
    age = pd.to_numeric(df[age_c], errors="coerce").reset_index(drop=True)

    def is_full_time(v):
        if pd.isna(v):
            return False
        s = _norm_employment(v)
        return ("full" in s and "time" in s) or s in {"ft"} or "full-time" in s.replace(" ", "")

    emp_ft = df[emp_c].reset_index(drop=True).apply(is_full_time)
    mask = (~age.isna()) & (age < 18) & emp_ft.fillna(False)
    return [int(i) for i, ok in enumerate(mask.tolist()) if ok]


def run_salary_positive_unemployed(df: pd.DataFrame, sal_c: str | None, emp_c: str | None) -> list[int]:
    if not sal_c or not emp_c:
        return []
    sal = pd.to_numeric(df[sal_c], errors="coerce").reset_index(drop=True)
    uh: list[bool] = []
    for v in df[emp_c].values:
        s = _norm_employment(v)
        uh.append("unemploy" in s or "not working" in s or s == "student")
    uh_s = pd.Series(uh).fillna(False)
    mask = (~sal.isna()) & (sal > 0) & uh_s
    return [int(i) for i, ok in enumerate(mask.tolist()) if ok]


def build_demo_templates(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = list(df.columns)
    age_c = _col_by_keyword(cols, ("age",))
    emp_c = _col_by_keyword(cols, ("employment", "employ", "work_status"))
    sal_c = _col_by_keyword(cols, ("salary", "wage", "income"))

    templates: list[dict[str, Any]] = []

    if age_c and emp_c:
        templates.append(
            {
                "id": "minor_full_time",
                "rule_expression": 'IF age < 18 AND employment_status ~ "full_time" THEN FLAG',
                "columns_involved": [age_c, emp_c],
                "run": lambda: run_minor_full_time(df, age_c, emp_c),
            }
        )

    if sal_c and emp_c:
        templates.append(
            {
                "id": "salary_positive_unemployed",
                "rule_expression": 'IF salary > 0 AND employment_status ~ "unemployed" THEN FLAG',
                "columns_involved": [sal_c, emp_c],
                "run": lambda: run_salary_positive_unemployed(df, sal_c, emp_c),
            }
        )

    return templates


def run_templates_with_confidence(edges: list[dict[str, Any]]) -> Callable[..., list[dict[str, Any]]]:
    avg_weight = (
        sum(float(e.get("weight") or e.get("influence_score") or 0) for e in edges) / max(len(edges), 1)
        if edges
        else 0.35
    )
    graph_support = min(1.0, abs(avg_weight))

    def _inner(df: pd.DataFrame) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        rows = len(df)
        for tpl in build_demo_templates(df):
            violations = tpl["run"]()
            rel_strength = graph_support if edges else 0.45
            dom_sim = 0.75 if tpl["columns_involved"] else 0.5
            hist = 0.5

            cf = multi_column_rule_confidence(
                relationship_strength=min(1.0, abs(rel_strength)),
                domain_similarity=dom_sim,
                graph_support=graph_support if edges else 0.35,
                historical_support=hist,
            )
            payloads.append(
                {
                    "rule_id": tpl["id"],
                    "rule_expression": tpl["rule_expression"],
                    "violations": violations,
                    "columns_involved": tpl["columns_involved"],
                    "confidence": cf,
                    "severity": "high" if violations and len(violations) > max(rows * 0.05, 3) else "medium",
                    "explain": {"graph_edge_count": len(edges), "rows_flagged": len(violations)},
                }
            )
        return payloads

    return _inner
