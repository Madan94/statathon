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
                       "how many", "how much", "overall", "aggregate"],
    "trend":          ["trend", "over time", "year", "month", "quarter", "change", "growth",
                       "increase", "decrease", "trajectory", "progress"],
    "correlation":    ["correlat", "relation", "associat", "link", "influence", "impact",
                       "affect", "relate", "depend", "factor"],
    "distribution":   ["distribut", "spread", "range", "percentile", "quartile", "histogram",
                       "skew", "variance", "std", "deviation"],
    "comparative":    ["compare", "vs", "versus", "differ", "between", "contrast",
                       "higher", "lower", "best", "worst", "rank"],
    "cross_section":  ["group", "segment", "category", "class", "type", "gender",
                       "region", "district", "state", "rural", "urban", "caste", "religion"],
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

# Known filter values for energy/resource datasets
_STATE_NAMES = {
    "jharkhand", "odisha", "chhattisgarh", "west bengal", "madhya pradesh",
    "telangana", "andhra pradesh", "rajasthan", "gujarat", "maharashtra",
    "tamil nadu", "karnataka", "assam", "uttar pradesh", "bihar",
}
_RESOURCE_CATEGORIES = {
    "coal", "lignite", "crude oil", "natural gas", "renewable energy",
    "solar", "wind", "hydro", "biomass",
}


def _detect_filter_conditions(query: str) -> dict[str, str | None]:
    """Detect explicit state/resource filter conditions from query text."""
    q = query.lower()
    state_filter = next((s.title() for s in _STATE_NAMES if s in q), None)
    resource_filter = next(
        (r.title() for r in _RESOURCE_CATEGORIES if r in q), None
    )
    return {"state": state_filter, "resource_category": resource_filter}


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

def _gemini_plan(query: str, context_summary: str) -> dict[str, Any] | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""You are the Planner Agent for a Government Statistical DeepAgent.

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
    ) -> ExecutionPlan:
        intent, sub_intents = _classify_intents(query)
        target_domains = _detect_domains(query)

        # Detect explicit filter conditions (state / resource_category) from query
        filter_conditions = _detect_filter_conditions(query)

        # Try to match user vocabulary to real column names via payload
        target_columns: list[str] = []
        if available_columns:
            q_lower = query.lower()
            # Exact substring match
            target_columns = [c for c in available_columns if c.lower() in q_lower]
            # Word-level fuzzy match (each word of query vs each word of column)
            if not target_columns:
                q_words = set(re.split(r"[\s_]+", q_lower))
                for c in available_columns:
                    c_words = set(re.split(r"[\s_]+", c.lower()))
                    if c_words & q_words - {"by", "in", "of", "the", "a", "and", "for"}:
                        target_columns.append(c)
            # Domain-based fallback
            if not target_columns and target_domains and analysis_payload:
                for row in analysis_payload.get("semantic_mapping") or []:
                    if (isinstance(row, dict)
                            and row.get("domain") in target_domains
                            and row.get("column")):
                        target_columns.append(str(row["column"]))
            # Always include columns that are likely filters/groupby targets
            filter_col_hints = []
            if filter_conditions.get("state") and "State" in available_columns:
                filter_col_hints.append("State")
            if filter_conditions.get("resource_category") and "Resource_Category" in available_columns:
                filter_col_hints.append("Resource_Category")
            # Ensure reserve numeric columns are included when energy domain
            if "energy" in target_domains:
                for c in available_columns:
                    if any(kw in c.lower() for kw in ("reserve", "capacity", "potential")):
                        filter_col_hints.append(c)
            for c in filter_col_hints:
                if c not in target_columns:
                    target_columns.append(c)
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

        # Attempt LLM-enhanced plan
        llm_raw = _gemini_plan(query, context_summary)

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
