"""PlannerAgent — decomposes any analytical question into an executable step plan.

The Planner is the first agent fired in the DeepAgent pipeline. It:

1. Classifies intent (aggregation / trend / correlation / distribution /
   cross-sectional / comparative / anomaly / narrative / forecast / test)
2. Identifies which data sources are needed (dataset, KG, rulebooks, history)
3. Maps the question to relevant semantic domains and columns via KG hints
4. Produces a structured ExecutionPlan consumed by the Retriever & Analyst

Gemini is used when available; a lightweight rule-based fallback guarantees
a valid plan even without an API key.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ─── Intent taxonomy ─────────────────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "aggregation":    ["count", "total", "sum", "average", "mean", "median", "max", "min",
                       "how many", "how much", "overall", "aggregate",
                       "highest", "lowest", "most", "least", "top", "bottom",
                       "which", "rank", "per", "rate", "ratio", "index"],
    "trend":          ["trend", "over time", "year", "month", "quarter", "change", "growth",
                       "increase", "decrease", "trajectory", "progress"],
    "correlation":    ["correlat", "relation", "associat", "link", "influence", "impact",
                       "affect", "relate", "depend", "factor"],
    "distribution":   ["distribut", "spread", "range", "percentile", "quartile", "histogram",
                       "skew", "variance", "std", "deviation"],
    "comparative":    ["compare", "vs", "versus", "differ", "between", "contrast",
                       "higher", "lower", "best", "worst", "rank"],
    "cross_section":  ["group", "segment", "category", "class", "type", "gender",
                       "region", "district", "state", "rural", "urban", "caste", "religion",
                       "sector", "by", "per", "breakdown"],
    "anomaly":        ["anomal", "outlier", "unusual", "suspect", "flag", "abnormal",
                       "error", "invalid", "extreme"],
    "imputation":     ["missing", "null", "blank", "fill", "impute", "incomplete"],
    "forecast":       ["forecast", "predict", "future", "project", "next year", "arima", "prophet"],
    "statistical_test": ["significan", "p-value", "chi-square", "anova", "t-test",
                         "mann-whitney", "hypothesis", "test"],
    "narrative":      ["explain", "describe", "summarize", "write", "generate", "report",
                       "narrative", "what is", "overview", "insight"],
    "graph_traversal":["how does", "path", "chain", "influence chain", "related columns",
                       "knowledge graph", "connected"],
}

# Domain keyword hints (for semantic column resolution without exact names)
DOMAIN_HINTS: dict[str, list[str]] = {
    "employment":    ["employ", "work", "job", "labor", "occupation", "workforce",
                      "unemployment", "salary", "wage", "income"],
    "education":     ["education", "school", "student", "literacy", "enroll",
                      "dropout", "teacher", "grade", "study"],
    "health":        ["health", "disease", "hospital", "mortality", "patient",
                      "treatment", "nutrition", "vaccination", "medical"],
    "agriculture":   ["crop", "farm", "land", "yield", "irrigation", "fertilizer",
                      "agricultural", "harvest", "soil"],
    "census":        ["population", "household", "migration", "housing",
                      "census", "enumeration"],
    "economic":      ["gdp", "production", "enterprise", "industry",
                      "manufacturing", "output", "revenue"],
    "energy":        ["energy", "reserve", "reserves", "coal", "lignite", "crude", "oil",
                      "natural gas", "renewable", "solar", "wind", "hydro", "biomass",
                      "petroleum", "power", "capacity", "mw", "bcm", "billion tonnes",
                      "proved", "indicated", "inferred", "potential", "resource"],
    "demographic":   ["age", "gender", "sex", "caste", "religion", "social group",
                      "ethnicity", "community"],
    "geography":     ["district", "state", "region", "rural", "urban", "block",
                      "location", "area"],
}

def _detect_filter_conditions(
    query: str,
    available_values: dict[str, list[str]] | None = None,
) -> dict[str, str | None]:
    """Detect filter conditions purely from the query + actual dataset values.

    Scans every categorical column's unique values against the query text.
    Returns {column_name: matched_value} for each column that has a match.
    Zero hardcoding — all matching is driven by the live dataset.
    """
    if not available_values:
        return {}

    q = query.lower()
    filters: dict[str, str | None] = {}

    for col, vals in available_values.items():
        for val in (vals or []):
            if val and str(val).lower() in q:
                filters[col] = val
                break  # first match per column

    return filters


def _build_available_values(
    df: "pd.DataFrame | None" = None,
    analysis_payload: "dict | None" = None,
    max_unique: int = 200,
) -> dict[str, list[str]]:
    """Build a {column → [unique_values]} map from df or analysis payload.

    Used for dynamic filter detection without any hardcoded column/value lists.
    """
    import pandas as pd
    result: dict[str, list[str]] = {}

    if df is not None and not df.empty:
        for col in df.select_dtypes(include=["object", "string", "category"]).columns:
            unique_vals = df[col].dropna().unique()
            if len(unique_vals) <= max_unique:
                result[col] = [str(v) for v in unique_vals]

    # Also pull from analysis payload column_profiles if provided
    if analysis_payload:
        col_profiles = analysis_payload.get("column_profiles") or {}
        for col, profile in col_profiles.items():
            if col in result:
                continue
            top_vals = (
                profile.get("top_values")
                or profile.get("value_counts")
                or {}
            )
            if top_vals:
                result[col] = [str(v) for v in (
                    list(top_vals.keys()) if isinstance(top_vals, dict) else top_vals
                )]

    return result


@dataclass
class PlanStep:
    step_id: str
    action: str           # retrieve_dataset / retrieve_kg / retrieve_rulebook /
                          # retrieve_history / run_analytics / run_forecast /
                          # run_test / generate_narrative / verify / assemble
    description: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "description": self.description,
            "params": self.params,
            "depends_on": self.depends_on,
        }


@dataclass
class ExecutionPlan:
    query: str
    intent: str
    sub_intents: list[str]
    target_domains: list[str]
    target_columns: list[str]      # resolved from KG / payload hints
    needs_dataset: bool
    needs_kg: bool
    needs_rulebook: bool
    needs_history: bool
    output_types: list[str]        # narrative / table / chart / metric / ast_block
    steps: list[PlanStep]
    raw_plan: dict[str, Any] = field(default_factory=dict)
    filter_conditions: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent,
            "sub_intents": self.sub_intents,
            "target_domains": self.target_domains,
            "target_columns": self.target_columns,
            "needs_dataset": self.needs_dataset,
            "needs_kg": self.needs_kg,
            "needs_rulebook": self.needs_rulebook,
            "needs_history": self.needs_history,
            "output_types": self.output_types,
            "steps": [s.to_dict() for s in self.steps],
            "filter_conditions": self.filter_conditions,
        }


# ─── Rule-based intent classifier (no LLM needed) ────────────────────────────

def _classify_intents(query: str) -> tuple[str, list[str]]:
    q = query.lower()
    scores: dict[str, int] = {}
    for intent, kws in INTENT_KEYWORDS.items():
        scores[intent] = sum(1 for kw in kws if kw in q)

    # primary = highest score, fall back to narrative
    sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_intents[0][0] if sorted_intents[0][1] > 0 else "narrative"
    sub = [k for k, v in sorted_intents[1:] if v > 0][:3]
    return primary, sub


def _detect_domains(query: str) -> list[str]:
    q = query.lower()
    return [d for d, kws in DOMAIN_HINTS.items() if any(kw in q for kw in kws)]


def _needs_kg(intent: str, query: str) -> bool:
    kg_triggers = {
        "correlation", "graph_traversal", "comparative", "trend",
        "cross_section", "narrative",
    }
    return intent in kg_triggers or any(
        kw in query.lower()
        for kw in ["graph", "knowledge", "related", "connected", "path", "how does"]
    )


def _output_types(intent: str, query: str) -> list[str]:
    q = query.lower()
    types: list[str] = []
    if intent in ("narrative", "graph_traversal"):
        types.append("narrative")
    if intent in ("aggregation", "cross_section", "comparative", "distribution"):
        types += ["table", "chart"]
    if intent in ("trend", "forecast"):
        types += ["chart", "narrative"]
    if intent == "anomaly":
        types += ["table", "narrative"]
    if intent in ("statistical_test", "correlation"):
        types += ["metric", "narrative"]
    if "report" in q or "section" in q or "block" in q:
        types.append("ast_block")
    if not types:
        types = ["narrative"]
    return list(dict.fromkeys(types))  # deduplicate preserving order


# ─── Step builder ─────────────────────────────────────────────────────────────

def _build_steps(
    intent: str,
    sub_intents: list[str],
    target_domains: list[str],
    needs_kg: bool,
    needs_history: bool,
    needs_rulebook: bool,
    output_types: list[str],
    query: str,
) -> list[PlanStep]:
    steps: list[PlanStep] = []

    steps.append(PlanStep(
        step_id="s1",
        action="retrieve_dataset",
        description="Load dataset into Arrow kernel; apply active filters",
        params={"domains": target_domains},
    ))

    if needs_kg:
        steps.append(PlanStep(
            step_id="s2",
            action="retrieve_kg",
            description="Resolve column names from KG via semantic domain traversal",
            params={"domains": target_domains},
            depends_on=["s1"],
        ))

    if needs_rulebook:
        steps.append(PlanStep(
            step_id="s3",
            action="retrieve_rulebook",
            description="Fetch validation rules and methodology notes for target domains",
            params={"domains": target_domains},
            depends_on=["s1"],
        ))

    if needs_history:
        steps.append(PlanStep(
            step_id="s4",
            action="retrieve_history",
            description="Retrieve relevant past reports and corrections from LTM",
            params={"query": query},
            depends_on=["s1"],
        ))

    analytic_deps = [s.step_id for s in steps]

    if intent in ("forecast", "trend") and "forecast" in intent + " ".join(sub_intents):
        steps.append(PlanStep(
            step_id="s5",
            action="run_forecast",
            description="Run time-series forecast (ARIMA / Prophet) on target column",
            params={"method": "auto"},
            depends_on=analytic_deps,
        ))
    elif intent in ("statistical_test",):
        steps.append(PlanStep(
            step_id="s5",
            action="run_test",
            description="Run statistical hypothesis test (chi-square / ANOVA / t-test)",
            params={"auto_select": True},
            depends_on=analytic_deps,
        ))
    elif intent in ("correlation",):
        steps.append(PlanStep(
            step_id="s5",
            action="run_analytics",
            description="Compute Pearson + Spearman correlation matrix for target domains",
            params={"mode": "correlation"},
            depends_on=analytic_deps,
        ))
    elif intent in ("distribution",):
        steps.append(PlanStep(
            step_id="s5",
            action="run_analytics",
            description="Compute distribution stats (percentiles, skew, kurtosis)",
            params={"mode": "distribution"},
            depends_on=analytic_deps,
        ))
    elif intent in ("aggregation", "cross_section", "comparative"):
        steps.append(PlanStep(
            step_id="s5",
            action="run_analytics",
            description="Aggregation / group-by / cross-tabulation",
            params={"mode": intent},
            depends_on=analytic_deps,
        ))
    elif intent == "anomaly":
        steps.append(PlanStep(
            step_id="s5",
            action="run_analytics",
            description="Retrieve flagged anomalies and compute outlier impact",
            params={"mode": "anomaly"},
            depends_on=analytic_deps,
        ))
    else:
        steps.append(PlanStep(
            step_id="s5",
            action="run_analytics",
            description="General analytics over target data",
            params={"mode": "general"},
            depends_on=analytic_deps,
        ))

    if "narrative" in output_types or "ast_block" in output_types:
        steps.append(PlanStep(
            step_id="s6",
            action="generate_narrative",
            description="Scribe drafts narrative grounded in retrieved facts",
            params={"output_types": output_types},
            depends_on=["s5"],
        ))

    steps.append(PlanStep(
        step_id="s7",
        action="verify",
        description="Verifier recomputes all numeric claims; consensus loop if needed",
        depends_on=["s5", "s6"] if "narrative" in output_types else ["s5"],
    ))

    steps.append(PlanStep(
        step_id="s8",
        action="assemble",
        description="Assemble final RenderedBlock(s) for canvas / drag-and-drop",
        params={"output_types": output_types},
        depends_on=["s7"],
    ))

    return steps


# ─── LLM-enhanced plan (Gemini) ───────────────────────────────────────────────

def _gemini_plan(query: str, context_summary: str,
                  extra_system_prompt: str | None = None) -> dict[str, Any] | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key)
        model_name = os.getenv("GEMINI_SEMANTIC_MODEL", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)
        extra_section = (
            f"\n\nAdditional instructions:\n{extra_system_prompt}\n"
            if extra_system_prompt else ""
        )
        prompt = f"""You are the Planner Agent for a Government Statistical DeepAgent.{extra_section}

Dataset context:
{context_summary}

User question: "{query}"

Produce a JSON execution plan with:
{{
  "intent": "<primary intent>",
  "sub_intents": [],
  "target_domains": [],
  "steps": [
    {{"step_id":"s1","action":"retrieve_dataset","description":"...","params":{{}},"depends_on":[]}}
  ],
  "output_types": ["narrative"|"table"|"chart"|"metric"|"ast_block"],
  "needs_kg": true/false,
  "needs_rulebook": true/false,
  "needs_history": true/false
}}

Valid actions: retrieve_dataset, retrieve_kg, retrieve_rulebook, retrieve_history,
run_analytics, run_forecast, run_test, generate_narrative, verify, assemble.
Output ONLY the JSON object, no markdown."""
        response = model.generate_content(prompt)
        text = (response.text or "").strip()
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        return json.loads(text)
    except Exception as exc:
        logger.info("Gemini plan failed: %s", exc)
        return None


# ─── Public API ───────────────────────────────────────────────────────────────

class PlannerAgent:
    """Primary reasoning layer: question → ExecutionPlan."""

    def plan(
        self,
        query: str,
        *,
        analysis_payload: dict[str, Any] | None = None,
        available_columns: list[str] | None = None,
        df: "Any | None" = None,   # pd.DataFrame — used for dynamic column/value detection
        extra_system_prompt: str | None = None,  # optional injected prompt (e.g. for chart planning)
    ) -> ExecutionPlan:
        import pandas as pd

        intent, sub_intents = _classify_intents(query)
        target_domains = _detect_domains(query)

        # Derive available_columns from df if not explicitly given
        if df is not None and not getattr(df, "empty", True):
            if available_columns is None:
                available_columns = list(df.columns)

        # Build available_values map fully from df (preferred) + payload
        available_values = _build_available_values(df, analysis_payload)

        # Detect filter conditions from actual dataset values — no hardcoding
        filter_conditions = _detect_filter_conditions(query, available_values)

        # Resolve target columns from query keywords matched against column names/values
        target_columns: list[str] = []
        if available_columns:
            q_lower = query.lower()
            stop_words = {"by", "in", "of", "the", "a", "and", "for", "is", "are",
                          "what", "show", "give", "list", "which", "how", "does",
                          "vs", "versus", "compare", "total", "all", "with", "its",
                          "that", "this", "from", "has", "have", "had", "been"}

            def _col_words(col: str) -> set[str]:
                """Split CamelCase + underscore/dash → lowercase word set."""
                # CamelCase split: XYZAbc → XYZ Abc
                camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2",
                                     re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", col))
                words = set(re.split(r"[\s_\-]+", camel_split.lower())) - stop_words
                return words

            # 1. Exact column-name substring match
            target_columns = [c for c in available_columns if c.lower() in q_lower]

            # 2. Word-level fuzzy: CamelCase-aware column word matching
            q_words = set(re.split(r"[\s_\-]+", q_lower)) - stop_words
            for c in available_columns:
                if c in target_columns:
                    continue
                c_words = _col_words(c)
                if c_words & q_words:
                    target_columns.append(c)

            # 3. Ensure filter-matched columns are always included
            for col, val in filter_conditions.items():
                if val and col in available_columns and col not in target_columns:
                    target_columns.append(col)

            # 4. Domain-based fallback: include semantically mapped columns
            if not target_columns and target_domains and analysis_payload:
                for row in analysis_payload.get("semantic_mapping") or []:
                    if (isinstance(row, dict)
                            and row.get("domain") in target_domains
                            and row.get("column")):
                        target_columns.append(str(row["column"]))

            # 5. If still empty, include all columns for general queries
            if not target_columns and available_columns:
                target_columns = list(available_columns)

            target_columns = list(dict.fromkeys(target_columns))[:20]

            # 6. Ensure at least one numeric column is included for aggregation queries
            #    (so analytics can actually compute something)
            if df is not None and not getattr(df, "empty", True):
                import pandas as _pd
                has_num = any(
                    _pd.api.types.is_numeric_dtype(df[c].dtype)
                    for c in target_columns if c in df.columns
                )
                if not has_num and intent in (
                    "aggregation", "cross_section", "comparative", "distribution", "narrative"
                ):
                    # Add top numeric columns by absolute sum
                    num_candidates = sorted(
                        [c for c in df.select_dtypes(include="number").columns
                         if c not in target_columns],
                        key=lambda c: -float(df[c].abs().sum()),
                    )
                    target_columns += num_candidates[:3]
                    target_columns = list(dict.fromkeys(target_columns))[:20]

        needs_kg_ = _needs_kg(intent, query)
        needs_history_ = intent in ("narrative", "comparative", "trend")
        needs_rulebook_ = bool(target_domains) or intent in (
            "statistical_test", "anomaly", "imputation"
        )
        output_types = _output_types(intent, query)

        # Build context summary for LLM
        col_sample = ", ".join((available_columns or [])[:15])
        domain_str = ", ".join(target_domains) if target_domains else "general"
        context_summary = (
            f"Domains: {domain_str}. "
            f"Sample columns: {col_sample}. "
            f"Intent: {intent}."
        )

        # Attempt LLM-enhanced plan (inject extra_system_prompt for specialised callers)
        llm_raw = _gemini_plan(query, context_summary, extra_system_prompt)

        # Merge LLM output where safe, keep rule-based structure
        if llm_raw:
            intent = llm_raw.get("intent", intent)
            sub_intents = llm_raw.get("sub_intents", sub_intents)
            for d in llm_raw.get("target_domains", []):
                if d not in target_domains:
                    target_domains.append(d)
            needs_kg_ = llm_raw.get("needs_kg", needs_kg_)
            needs_history_ = llm_raw.get("needs_history", needs_history_)
            needs_rulebook_ = llm_raw.get("needs_rulebook", needs_rulebook_)
            output_types = llm_raw.get("output_types", output_types)

        steps = _build_steps(
            intent, sub_intents, target_domains,
            needs_kg_, needs_history_, needs_rulebook_,
            output_types, query,
        )

        return ExecutionPlan(
            query=query,
            intent=intent,
            sub_intents=sub_intents,
            target_domains=target_domains,
            target_columns=target_columns,
            needs_dataset=True,
            needs_kg=needs_kg_,
            needs_rulebook=needs_rulebook_,
            needs_history=needs_history_,
            output_types=output_types,
            steps=steps,
            raw_plan=llm_raw or {},
            filter_conditions=filter_conditions,
        )
