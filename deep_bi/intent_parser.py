"""Semantic Intent Parser.

Replaces the keyword-only planner with a *concept-level* intent parse that
works for questions where no column name appears verbatim.

Output schema (mirrors the spec):

    {
      "question_type": "causal_analysis",
      "concepts":      ["economic vulnerability", "income instability",
                         "employment status", "social group"],
      "metrics_needed":["income", "occupation", "employment"],
      "filters":       [{"dimension":"state","value":"Bihar"}],
      "comparisons":   [{"left":"male", "right":"female"}],
      "decomposition": [...],   # sub-questions for query decomposer
      "confidence":    0.94
    }

Three layers, each falls back gracefully:
  1. Gemini LLM (if GEMINI_API_KEY set) — best quality
  2. Rule-based concept extractor (always available)
  3. Token-overlap fallback (last resort)
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


_QUESTION_TYPES = {
    # type -> trigger phrases
    "aggregation":   ["total", "sum", "count of", "number of", "how many",
                      "average", "mean of"],
    "ranking":       ["top", "bottom", "highest", "lowest", "rank", "leading",
                      "outperform", "underperform"],
    "trend":         ["over time", "trend", "growth", "change in", "across years"],
    "correlation":   ["correlate", "relationship", "associated with",
                      "linked to", "vary with"],
    "comparison":    ["compare", "vs", "versus", "between", "difference",
                      "male vs female", "rural vs urban"],
    "causal_analysis": ["why", "cause", "drives", "influences", "leads to",
                        "due to", "because of", "through"],
    "distribution":  ["distribution", "spread", "histogram", "percentile",
                      "quartile"],
    "anomaly":       ["outlier", "anomaly", "unusual", "extreme", "abnormal"],
    "geographic":    ["state", "district", "region", "geography", "across states"],
    "what_if":       ["what if", "if we", "would it", "suppose"],
    "describe":      ["describe", "summarise", "summarize", "overview", "tell me about"],
}


# Concept lexicon — broad, domain-agnostic
_CONCEPT_LEXICON: dict[str, list[str]] = {
    "labour_force":      ["lfpr", "labour force", "labor force", "workforce",
                           "employment rate", "participation"],
    "unemployment":      ["unemployment", "joblessness", "ur"],
    "income":            ["income", "earning", "salary", "wage", "pay"],
    "expenditure":       ["expenditure", "expense", "spending", "consumption"],
    "education":         ["education", "literacy", "schooling", "qualification"],
    "health":            ["health", "mortality", "imr", "bmi"],
    "demographic":       ["age", "gender", "sex", "population", "household"],
    "geography":         ["state", "district", "region", "pincode", "geography"],
    "agriculture":       ["yield", "crop", "harvest", "rainfall", "soil"],
    "industrial":        ["iip", "production", "factory", "capacity", "manufacturing"],
    "energy":            ["coal", "petroleum", "gas", "renewable", "reserves",
                           "capacity", "energy", "mw", "tonnes"],
    "vulnerability":     ["vulnerable", "vulnerability", "at risk", "exposure"],
    "economic_shock":    ["economic shock", "downturn", "recession", "crisis",
                           "shock", "stress"],
    "social_group":      ["caste", "religion", "ethnicity", "social group",
                           "marginalised", "marginalized"],
    "time":              ["year", "month", "quarter", "since"],
    "growth":            ["growth", "increase", "decrease", "change"],
}


# Filter patterns: capture a place-like or year token after a preposition.
# We deliberately require >= 4 letters to avoid units (MW, KW, KG, MT, etc.).
_FILTER_PATTERNS = [
    re.compile(r"\b(?:in|for|at)\s+([A-Z][a-zA-Z]{3,}(?:\s+[A-Z][a-zA-Z]+)?)\b"),
    re.compile(r"\b(20\d{2})\b"),
]

# Tokens that look capitalised but are actually units of measure — must never
# be treated as state names.
_UNIT_TOKENS = {
    "MW", "KW", "GW", "TW", "KG", "MT", "GT", "TT", "L", "ML",
    "Billion Tonnes", "Million Tonnes", "Tonnes", "Megawatt", "Megawatts",
    "USD", "INR", "EUR",
}

# Resource categories — should map to a resource_category filter, not state.
_RESOURCE_CATEGORY_TOKENS = {
    "Coal", "Petroleum", "Natural Gas", "Lignite", "Renewable", "Solar",
    "Wind", "Biomass", "Hydroelectric", "Hydro", "Nuclear",
}


_COMPARISON_PATTERNS = [
    re.compile(r"\b(male)s?\s+(?:vs|versus|and|compared\s+to)\s+(female)s?\b", re.I),
    re.compile(r"\b(rural)\s+(?:vs|versus|and|compared\s+to)\s+(urban)\b", re.I),
    re.compile(r"\b(\d{4})\s+(?:vs|versus|and|compared\s+to)\s+(\d{4})\b"),
    # Generic "<word> (vs|versus) <word>" — capture pairs even when lowercase
    re.compile(r"\b([a-z][a-zA-Z]{2,})\s+(?:vs|versus|compared\s+to)\s+([a-z][a-zA-Z]{2,})\b", re.I),
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ParsedIntent:
    question_type: str = "describe"
    concepts: list[str] = field(default_factory=list)
    metrics_needed: list[str] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    comparisons: list[dict[str, str]] = field(default_factory=list)
    decomposition: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw_query: str = ""
    method: str = "rule"     # 'gemini' | 'rule' | 'fallback'
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class IntentParser:
    """Parse a natural-language query into a ParsedIntent."""

    def __init__(self, *, prefer_gemini: bool = True):
        self.prefer_gemini = prefer_gemini

    # ---------------- Public ----------------

    def parse(self, query: str, *, columns: list[str] | None = None,
              dataset_archetype: str | None = None) -> ParsedIntent:
        """Top-level entry — returns the best available parse."""
        if self.prefer_gemini:
            try:
                gem = self._gemini_parse(query, columns=columns,
                                           dataset_archetype=dataset_archetype)
                if gem and gem.confidence >= 0.50:
                    return gem
            except Exception as exc:
                logger.info("Gemini intent parse failed: %s", exc)
        return self._rule_parse(query, columns=columns)

    # ---------------- Gemini ----------------

    def _gemini_parse(self, query: str, *, columns: list[str] | None,
                       dataset_archetype: str | None) -> ParsedIntent | None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        try:
            from core.gemini_client import get_generative_model
            model = get_generative_model()
            if model is None:
                return None
        except Exception:
            return None

        col_hint = ", ".join(columns or [])[:600] if columns else ""
        arch_hint = dataset_archetype or "unknown"
        prompt = (
            "You are a semantic intent parser for a statistical-research BI.\n"
            "Return ONLY valid JSON with these keys:\n"
            "  question_type     (aggregation|ranking|trend|correlation|comparison|"
            "causal_analysis|distribution|anomaly|geographic|what_if|describe)\n"
            "  concepts          list of high-level concepts implied by the question\n"
            "  metrics_needed    list of concrete measures (income, count, rate, ...)\n"
            "  filters           [{dimension, value}]\n"
            "  comparisons       [{left, right}]\n"
            "  decomposition     list of sub-questions if the query is multi-hop\n"
            "  confidence        0..1\n\n"
            f"Dataset archetype: {arch_hint}\n"
            f"Available columns: {col_hint}\n\n"
            f"Query: {query!r}\n"
            "JSON:"
        )
        try:
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
            data = json.loads(text)
        except Exception:
            return None
        try:
            return ParsedIntent(
                question_type=str(data.get("question_type") or "describe"),
                concepts=[str(c) for c in (data.get("concepts") or [])],
                metrics_needed=[str(m) for m in (data.get("metrics_needed") or [])],
                filters=[{"dimension": str(f.get("dimension") or ""),
                          "value": str(f.get("value") or "")}
                         for f in (data.get("filters") or [])
                         if isinstance(f, dict)],
                comparisons=[{"left": str(c.get("left") or ""),
                              "right": str(c.get("right") or "")}
                             for c in (data.get("comparisons") or [])
                             if isinstance(c, dict)],
                decomposition=[str(d) for d in (data.get("decomposition") or [])],
                confidence=float(data.get("confidence") or 0.7),
                raw_query=query, method="gemini",
            )
        except Exception:
            return None

    # ---------------- Rule-based ----------------

    def _rule_parse(self, query: str,
                     *, columns: list[str] | None) -> ParsedIntent:
        q = query.lower()
        qtype, qtype_score = self._classify_question_type(q)
        concepts = self._extract_concepts(q)
        metrics = self._infer_metrics(concepts, qtype, columns or [])
        filters = self._extract_filters(query)
        comparisons = self._extract_comparisons(query)
        decomposition = self._decompose_if_multi_hop(query, concepts)

        # Confidence: function of question_type match + concept count
        conf = 0.40 + 0.10 * min(len(concepts), 4) + 0.10 * qtype_score
        return ParsedIntent(
            question_type=qtype,
            concepts=concepts,
            metrics_needed=metrics,
            filters=filters,
            comparisons=comparisons,
            decomposition=decomposition,
            confidence=min(1.0, conf),
            raw_query=query,
            method="rule",
            diagnostics={"qtype_score": qtype_score},
        )

    @staticmethod
    def _phrase_in_query(phrase: str, query_lower: str) -> bool:
        """Word-boundary check that tolerates trailing plural 's' / 'es' /
        'ed' / 'ing' (so 'outlier' matches 'outliers', 'rank' matches
        'ranked'). Avoids 'ur' matching 'reso**ur**ce'.
        """
        if not phrase:
            return False
        patt = re.compile(
            rf"(?<![a-z0-9]){re.escape(phrase)}(?:s|es|ed|ing)?(?![a-z0-9])"
        )
        return patt.search(query_lower) is not None

    # Priority among question types when multiple triggers match — higher
    # specificity wins (ranking is more informative than aggregation).
    _QTYPE_PRIORITY = {
        "causal_analysis": 5, "anomaly": 5, "comparison": 4,
        "ranking": 4, "trend": 4, "correlation": 4,
        "distribution": 3, "geographic": 3, "what_if": 3,
        "aggregation": 2, "describe": 1,
    }

    @staticmethod
    def _classify_question_type(q: str) -> tuple[str, float]:
        scored: list[tuple[str, int]] = []
        for t, triggers in _QUESTION_TYPES.items():
            hits = sum(1 for tr in triggers
                        if IntentParser._phrase_in_query(tr, q))
            if hits > 0:
                scored.append((t, hits))
        if not scored:
            return "describe", 0.0
        # Order: more hits first; ties broken by priority
        scored.sort(key=lambda x: (x[1], IntentParser._QTYPE_PRIORITY.get(x[0], 0)),
                     reverse=True)
        best, best_hits = scored[0]
        score = min(1.0, best_hits / 2.0)
        return best, score

    @staticmethod
    def _extract_concepts(q: str) -> list[str]:
        out: list[str] = []
        for concept, triggers in _CONCEPT_LEXICON.items():
            if any(IntentParser._phrase_in_query(tr, q) for tr in triggers):
                out.append(concept)
        # De-dup but preserve order
        seen, result = set(), []
        for c in out:
            if c not in seen:
                seen.add(c); result.append(c)
        return result

    @staticmethod
    def _infer_metrics(concepts: list[str], qtype: str,
                        columns: list[str]) -> list[str]:
        metric_hints: dict[str, list[str]] = {
            "labour_force":   ["employment_rate", "lfpr", "wpr"],
            "income":         ["income", "salary", "wage"],
            "energy":         ["reserves", "capacity"],
            "agriculture":    ["yield", "area"],
            "health":         ["mortality", "bmi"],
            "education":      ["literacy_rate", "education_years"],
            "growth":         ["growth_rate"],
            "demographic":    ["age", "household_size"],
        }
        wanted: list[str] = []
        for c in concepts:
            wanted.extend(metric_hints.get(c, []))
        # Filter by what actually appears in column names (case-insensitive)
        col_lc = [c.lower() for c in (columns or [])]
        keep = [w for w in wanted
                if any(part in col for col in col_lc for part in w.split("_"))]
        # Always return at least the raw concept names so the column resolver
        # can fall back to semantic similarity if no column-name hint matches.
        return keep or wanted or concepts

    @staticmethod
    def _extract_filters(query: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        # Resource categories (coal/petroleum/...) -> resource_category filter
        for kw in _RESOURCE_CATEGORY_TOKENS:
            if IntentParser._phrase_in_query(kw.lower(), query.lower()):
                out.append({"dimension": "resource_category", "value": kw})
        # Years
        for m in re.finditer(r"\b(20\d{2})\b", query):
            out.append({"dimension": "year", "value": m.group(1)})
        # Place-like after a preposition (excluding units)
        for patt in _FILTER_PATTERNS:
            for m in patt.finditer(query):
                token = m.group(1).strip()
                # Skip if token is a known unit / resource
                if token in _UNIT_TOKENS or token.upper() in _UNIT_TOKENS:
                    continue
                if token in _RESOURCE_CATEGORY_TOKENS:
                    # Already captured above
                    continue
                if re.fullmatch(r"\d{4}", token):
                    out.append({"dimension": "year", "value": token})
                elif len(token) >= 4:
                    out.append({"dimension": "state", "value": token})
        # De-dup
        seen, dedup = set(), []
        for f in out:
            key = (f["dimension"], f["value"])
            if key not in seen:
                seen.add(key); dedup.append(f)
        return dedup

    @staticmethod
    def _extract_comparisons(query: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for patt in _COMPARISON_PATTERNS:
            for m in patt.finditer(query):
                out.append({"left": m.group(1), "right": m.group(2)})
        return out

    @staticmethod
    def _decompose_if_multi_hop(query: str, concepts: list[str]) -> list[str]:
        # Heuristic: "through" / "via" / multiple "and" between concepts
        if len(concepts) < 3:
            return []
        if "through" in query.lower() or "via" in query.lower():
            return [f"How does {concepts[i]} relate to {concepts[i+1]}?"
                    for i in range(len(concepts) - 1)]
        return []
