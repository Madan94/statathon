"""Analytics Planner — emits a multi-step computation plan BEFORE compute.

For a question like "Which states outperform their expected renewable
potential based on population size?" the plan would be:

  [
    {"op":"aggregate", "by":"state", "metric":"renewable_potential", "fn":"sum"},
    {"op":"aggregate", "by":"state", "metric":"population",          "fn":"sum"},
    {"op":"ratio", "numerator":"renewable_potential", "denominator":"population"},
    {"op":"rank", "metric":"ratio", "order":"desc"},
    {"op":"outlier", "metric":"ratio", "method":"iqr"}
  ]

The plan is deterministic + auditable: the AnalyticsExecutor follows it
without re-deciding anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intent_parser import ParsedIntent
from .column_synonym_kg import ColumnSynonymKG


@dataclass
class AnalyticsStep:
    op: str                      # 'aggregate' | 'filter' | 'ratio' | 'rank' | 'outlier' | 'trend' | 'corr' | 'compare' | 'describe'
    params: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "params": self.params, "explanation": self.explanation}


@dataclass
class AnalyticsPlan:
    steps: list[AnalyticsStep] = field(default_factory=list)
    target_columns: list[str] = field(default_factory=list)
    group_columns: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps],
                "target_columns": self.target_columns,
                "group_columns": self.group_columns,
                "rationale": self.rationale}


class AnalyticsPlanner:
    """Build an AnalyticsPlan from a ParsedIntent and a resolved column set."""

    def __init__(self, column_kg: ColumnSynonymKG):
        self.column_kg = column_kg

    def plan(self, intent: ParsedIntent, *, columns: list[str],
              numeric_columns: list[str] | None = None) -> AnalyticsPlan:
        # 1. Resolve target columns from BOTH metrics AND concepts so the
        # underlying synonym KG can expand low-specificity metric tokens
        # ("reserves") via the corresponding high-level concept ("energy").
        concept_search = list(dict.fromkeys(
            (intent.metrics_needed or []) + intent.concepts
        ))
        target_cols = self.column_kg.best_columns_for(
            concept_search, min_score=0.18,
        )
        # If still empty, fall back to ranking all columns by combined score
        # (keep deterministic — no random pick)
        if not target_cols and concept_search:
            ranked: list[tuple[float, str]] = []
            for c in concept_search:
                for m in self.column_kg.resolve(c, top_k=3, min_score=0.05):
                    ranked.append((m.score, m.column))
            ranked.sort(key=lambda kv: kv[0], reverse=True)
            seen: set[str] = set()
            for _, col in ranked:
                if col not in seen:
                    seen.add(col); target_cols.append(col)
                if len(target_cols) >= 5:
                    break
        # If we know which columns are numeric, partition: arithmetic ops use
        # only numeric metrics; non-numeric target_cols become group candidates.
        numeric_set = set(numeric_columns or [])
        arithmetic_qtypes = {"aggregation", "ranking", "trend", "anomaly",
                              "distribution", "correlation", "geographic"}
        if numeric_set and intent.question_type in arithmetic_qtypes:
            promoted_to_group = [c for c in target_cols if c not in numeric_set]
            target_cols = [c for c in target_cols if c in numeric_set]
            # The non-numeric columns are demoted into group candidates
            extra_groups = [c for c in promoted_to_group
                              if c not in target_cols]
        else:
            extra_groups = []

        # Re-rank target_cols so the column whose tokens best overlap with the
        # raw query comes first. This is the "user mentioned `reserves`, pick
        # the *_Reserves column" generic fix — no hardcoded vocabulary.
        if target_cols:
            import re as _re
            query_tokens = {
                t.lower() for t in _re.findall(r"[A-Za-z]{3,}", intent.raw_query or "")
            }
            def _affinity(col: str) -> tuple[int, int]:
                ctoks = {t.lower() for t in _re.findall(r"[A-Za-z]{3,}", col)}
                overlap = len(ctoks & query_tokens)
                # Tie-break: shorter columns are more specific
                return (-overlap, len(col))
            target_cols = sorted(target_cols, key=_affinity)
        # 2. Pick group columns. Prefer geography/demographic; then any
        # non-numeric columns demoted from target_cols (e.g. State); then
        # for ranking-like questions fall back to the first low-cardinality
        # column so we always have *something* to group by.
        group_cols: list[str] = []
        # First any non-numeric columns promoted from target_cols (e.g. State,
        # Resource_Category) — these are the most likely intended grouping
        # axes since they were already concept-matched.
        for c in extra_groups:
            if c not in target_cols and c not in group_cols:
                group_cols.append(c)
                if len(group_cols) >= 2:
                    break
        geo_cols = self.column_kg.best_columns_for(
            ["geography", "demographic"], min_score=0.30,
        )
        for c in geo_cols:
            if c not in target_cols and c not in group_cols:
                group_cols.append(c); break
        if not group_cols and intent.question_type in ("ranking", "geographic",
                                                          "comparison", "aggregation"):
            # First categorical-looking column (heuristic: in the dataset's column
            # list but NOT in target_cols which are numeric metric columns)
            for c in columns:
                if c in target_cols:
                    continue
                # Skip ID-style columns
                if str(c).lower().endswith("_id") or str(c).lower() == "id":
                    continue
                group_cols.append(c)
                break
        if "time" in intent.concepts or intent.question_type == "trend":
            time_cols = self.column_kg.best_columns_for(["time"], min_score=0.30)
            for c in time_cols:
                if c not in target_cols and c not in group_cols:
                    group_cols.append(c); break
        # 3. Add explicit filters
        steps: list[AnalyticsStep] = []
        for f in intent.filters:
            dim, val = f.get("dimension"), f.get("value")
            if dim and val:
                steps.append(AnalyticsStep(
                    op="filter", params={"dimension": dim, "value": val},
                    explanation=f"filter rows where {dim} == {val}",
                ))

        # 4. Question-type specific compute steps
        qtype = intent.question_type
        if qtype == "ranking":
            for col in target_cols[:1]:
                if group_cols:
                    steps.append(AnalyticsStep(
                        op="aggregate",
                        params={"by": group_cols, "metric": col, "fn": "sum"},
                        explanation=f"sum of {col} per {group_cols}",
                    ))
                steps.append(AnalyticsStep(
                    op="rank",
                    params={"metric": col, "order": "desc", "top_k": 10},
                    explanation=f"rank by {col} descending",
                ))
        elif qtype == "aggregation":
            for col in target_cols[:3]:
                steps.append(AnalyticsStep(
                    op="aggregate",
                    params={"by": group_cols or None, "metric": col, "fn": "sum"},
                    explanation=f"sum of {col}"
                                 + (f" per {group_cols}" if group_cols else ""),
                ))
        elif qtype == "trend":
            for col in target_cols[:2]:
                steps.append(AnalyticsStep(
                    op="trend",
                    params={"metric": col, "time_column": group_cols[-1] if group_cols else None},
                    explanation=f"trend of {col} over time",
                ))
        elif qtype == "correlation":
            if len(target_cols) >= 2:
                steps.append(AnalyticsStep(
                    op="corr",
                    params={"metrics": target_cols[:5]},
                    explanation=f"correlation matrix on {target_cols[:5]}",
                ))
        elif qtype == "comparison":
            for cmp in intent.comparisons[:2]:
                steps.append(AnalyticsStep(
                    op="compare",
                    params={"left": cmp.get("left"), "right": cmp.get("right"),
                            "metrics": target_cols[:2]},
                    explanation=f"{cmp.get('left')} vs {cmp.get('right')}",
                ))
        elif qtype == "anomaly":
            for col in target_cols[:2]:
                steps.append(AnalyticsStep(
                    op="outlier",
                    params={"metric": col, "method": "iqr"},
                    explanation=f"IQR outliers in {col}",
                ))
        elif qtype == "distribution":
            for col in target_cols[:2]:
                steps.append(AnalyticsStep(
                    op="describe",
                    params={"metric": col},
                    explanation=f"describe distribution of {col}",
                ))
        elif qtype == "causal_analysis":
            # Multi-hop: aggregate each metric per group then look at ratios
            for col in target_cols[:3]:
                steps.append(AnalyticsStep(
                    op="aggregate",
                    params={"by": group_cols or None, "metric": col, "fn": "mean"},
                    explanation=f"mean of {col} per {group_cols}",
                ))
            if len(target_cols) >= 2:
                steps.append(AnalyticsStep(
                    op="corr",
                    params={"metrics": target_cols[:3]},
                    explanation="correlation between hypothesised cause and effect",
                ))
        elif qtype == "geographic":
            for col in target_cols[:2]:
                steps.append(AnalyticsStep(
                    op="aggregate",
                    params={"by": group_cols or None, "metric": col, "fn": "sum"},
                    explanation=f"sum of {col} per {group_cols}",
                ))
                steps.append(AnalyticsStep(
                    op="rank",
                    params={"metric": col, "order": "desc", "top_k": 10},
                    explanation=f"top regions by {col}",
                ))
        else:  # describe / unknown
            for col in target_cols[:5]:
                steps.append(AnalyticsStep(
                    op="describe",
                    params={"metric": col},
                    explanation=f"describe {col}",
                ))

        if not steps:
            steps.append(AnalyticsStep(
                op="describe", params={},
                explanation="default summary; no specific operation derived",
            ))

        return AnalyticsPlan(
            steps=steps,
            target_columns=target_cols,
            group_columns=group_cols,
            rationale=f"intent={qtype}, concepts={intent.concepts}",
        )
