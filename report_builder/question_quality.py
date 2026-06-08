"""Question quality + archetype library (migration plan P4 / loop decisions Q11-Q15, Q13).

Pure, deterministic helpers (no LLM, no I/O) that turn raw VLM question output into clean,
well-formed, analytically-grounded questions:

* ``QUESTION_TYPES``          \u2014 the canonical questionType enum.
* ``normalise_question_type`` \u2014 D4: collapse a messy/echoed type into ONE valid value.
* ``is_stub_question``        \u2014 D3: detect echoed/template/placeholder intents.
* ``build_analytics_spec``    \u2014 D8/Q13: questionType + entity roles \u2192 analyticsSpec.
* ``archetype_questions``     \u2014 Q12: deterministic fallback questions from entities.
* ``route_unassigned``        \u2014 D5/Q15: nearest-topic routing with a "General" fallback.
"""
from __future__ import annotations

import re
from typing import Any

QUESTION_TYPES: tuple[str, ...] = (
    "comparison", "trend", "ranking", "distribution",
    "composition", "correlation", "describe",
)

# D8 / Q13: deterministic questionType \u2192 analytics operation backbone.
_TYPE_TO_OPERATION: dict[str, str] = {
    "comparison": "group_aggregate",
    "ranking": "rank",
    "trend": "time_series",
    "distribution": "distribution",
    "composition": "share",
    "correlation": "correlate",
    "describe": "summary_stats",
}

# D3: phrases that mark a stub / echoed / placeholder question (lowercased substrings).
_STUB_MARKERS: tuple[str, ...] = (
    "specific question about", "specific analytical question", "section topic",
    "this section topic", "exact section title", "section title here",
    "question about this", "what does this section", "what does this show",
    "placeholder", "entity_name", "entity1", "entity2", "metric name",
    "your question here", "intent here", "example question",
)


def normalise_question_type(raw: Any) -> str:
    """D4: collapse any messy questionType into exactly one canonical value.

    Handles full-enum echoes ("comparison|trend|ranking"), synonyms, and casing.
    Falls back to "comparison".
    """
    s = str(raw or "").strip().lower()
    if not s:
        return "comparison"
    # Echoed enum like "comparison|trend|ranking|describe" \u2192 first token.
    for sep in ("|", "/", ",", " or "):
        if sep in s:
            s = s.split(sep)[0].strip()
            break
    if s in QUESTION_TYPES:
        return s
    synonyms = {
        "compare": "comparison", "comparative": "comparison", "vs": "comparison",
        "rank": "ranking", "top": "ranking", "highest": "ranking", "lowest": "ranking",
        "time": "trend", "time_series": "trend", "timeseries": "trend", "over time": "trend",
        "growth": "trend", "change": "trend",
        "share": "composition", "proportion": "composition", "percent": "composition",
        "breakdown": "composition", "split": "composition",
        "correlation": "correlation", "correlate": "correlation", "relationship": "correlation",
        "distribution": "distribution", "spread": "distribution", "histogram": "distribution",
        "describe": "describe", "description": "describe", "summary": "describe", "overview": "describe",
    }
    for key, val in synonyms.items():
        if key in s:
            return val
    return "comparison"


def is_stub_question(intent: Any) -> bool:
    """D3: True if an intent is an echoed template / placeholder rather than a real question."""
    s = str(intent or "").strip()
    low = s.lower()
    if len(s) < 12:
        return True
    if any(m in low for m in _STUB_MARKERS):
        return True
    # A bare "...?" with no alphabetic content, or no question framing at all.
    if not re.search(r"[a-z]", low):
        return True
    return False


def build_analytics_spec(
    question_type: str,
    required_entities: list[dict[str, Any]],
    *,
    default_top_n: int = 10,
) -> dict[str, Any]:
    """D8/Q13: derive a value-free analyticsSpec from questionType + entity roles.

    ``required_entities`` items look like ``{"entityRef"/"entityId", "role"}`` where role is
    one of measure|grouping|groupBy|dimension|filter|time. Returns the analyticsSpec block.
    """
    qt = normalise_question_type(question_type)
    operation = _TYPE_TO_OPERATION[qt]

    measures: list[str] = []
    group_by: list[str] = []
    filters: list[str] = []
    time_ref: str | None = None
    for eb in required_entities or []:
        ref = eb.get("entityRef") or eb.get("entityId") or ""
        if not ref:
            continue
        role = str(eb.get("role") or "").lower()
        if role in ("measure", "metric", "value"):
            measures.append(ref)
        elif role in ("grouping", "groupby", "dimension", "breakdown"):
            group_by.append(ref)
        elif role in ("filter",):
            filters.append(ref)
        elif role in ("time", "period", "temporal"):
            time_ref = ref

    spec: dict[str, Any] = {
        "operation": operation,
        "measure": ({"entityRef": measures[0]} if measures else None),
        "groupBy": [{"entityRef": g} for g in group_by],
        "filters": [{"entityRef": f} for f in filters],
        "time": ({"entityRef": time_ref} if time_ref else None),
        "sort": {"by": "measure", "order": "desc"} if qt in ("comparison", "ranking") else None,
        "topN": default_top_n if qt == "ranking" else None,
        "compare": {"kind": "across_group" if qt == "comparison" else "none"},
    }
    return spec


def _measures_and_dims(entities: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    measures, dims = [], []
    for e in entities or []:
        etype = (e.get("entityType") or e.get("entityType_hint") or "dimension").lower()
        (measures if etype == "measure" else dims).append(e)
    return measures, dims


def archetype_questions(
    topic_title: str,
    entities: list[dict[str, Any]],
    *,
    max_questions: int = 3,
) -> list[dict[str, Any]]:
    """Q12: deterministic, always-valid questions from a topic's measures \u00d7 dimensions.

    Guarantees a topic with at least one measure + one dimension is never empty.
    Each question carries intent, questionType, requiredEntities, and analyticsSpec.
    """
    measures, dims = _measures_and_dims(entities)
    if not measures:
        return []
    out: list[dict[str, Any]] = []
    m = measures[0]
    m_name = m.get("name", "the indicator")
    m_ref = m.get("entityId") or m.get("name")

    templates: list[tuple[str, str]] = []
    if dims:
        d = dims[0]
        d_name = d.get("name", "category")
        d_ref = d.get("entityId") or d.get("name")
        templates.append((f"How does {m_name} differ across {d_name}?", "comparison"))
        templates.append((f"Which {d_name} have the highest {m_name}?", "ranking"))
        if len(dims) > 1:
            d2 = dims[1]
            templates.append(
                (f"How does {m_name} vary by {d2.get('name', 'group')}?", "comparison"))
    else:
        d_ref = None
        templates.append((f"What is the overall {m_name}?", "describe"))

    for i, (intent, qtype) in enumerate(templates[:max_questions]):
        req: list[dict[str, Any]] = [{"entityRef": m_ref, "role": "measure"}]
        if d_ref:
            grouping_role = "grouping"
            req.append({"entityRef": d_ref, "role": grouping_role})
        out.append({
            "intent": intent,
            "questionType": qtype,
            "requiredEntities": req,
            "analyticsSpec": build_analytics_spec(qtype, req),
            "source": "archetype",
            "sourceHeading": topic_title,
        })
    return out


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if len(t) > 2}


def route_unassigned(
    question: dict[str, Any],
    topics: list[dict[str, Any]],
    *,
    min_overlap: int = 1,
) -> str:
    """D5/Q15: pick the best topicId for an unassigned question; else "General".

    Matches the question intent/sourceHeading against topic titles by token overlap.
    Never returns an empty string \u2014 the caller is expected to create a General topic
    when this returns "topic_general".
    """
    q_tokens = _tokenize(question.get("intent", "")) | _tokenize(question.get("sourceHeading", ""))
    best_id = "topic_general"
    best_score = 0
    for t in topics or []:
        score = len(q_tokens & _tokenize(t.get("title", "")))
        if score > best_score:
            best_score = score
            best_id = t.get("topicId", "topic_general")
    return best_id if best_score >= min_overlap else "topic_general"
