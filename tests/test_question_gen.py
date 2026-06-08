"""P4 tests: question quality (D3 stubs, D4 questionType, D8 analyticsSpec, Q12 archetypes, D5 routing)."""
from __future__ import annotations

from report_builder.question_quality import (
    QUESTION_TYPES,
    archetype_questions,
    build_analytics_spec,
    is_stub_question,
    normalise_question_type,
    route_unassigned,
)


# ── D4: questionType normalisation ──────────────────────────────────────────
def test_normalise_passthrough_valid():
    for t in QUESTION_TYPES:
        assert normalise_question_type(t) == t


def test_normalise_echoed_enum_picks_first():
    assert normalise_question_type("comparison|trend|ranking|describe") == "comparison"
    assert normalise_question_type("trend/ranking") == "trend"


def test_normalise_synonyms_and_casing():
    assert normalise_question_type("Compare") == "comparison"
    assert normalise_question_type("TOP 10") == "ranking"
    assert normalise_question_type("over time") == "trend"
    assert normalise_question_type("breakdown") == "composition"


def test_normalise_empty_and_garbage_default():
    assert normalise_question_type("") == "comparison"
    assert normalise_question_type(None) == "comparison"
    assert normalise_question_type("zxqw") == "comparison"


# ── D3: stub detection ──────────────────────────────────────────────────────
def test_stub_detects_echoed_templates():
    assert is_stub_question("Specific question about this section topic?")
    assert is_stub_question("exact section title here")
    assert is_stub_question("What does this section show?")
    assert is_stub_question("?")
    assert is_stub_question("")


def test_stub_accepts_real_question():
    assert not is_stub_question("How does LFPR differ across Rural and Urban areas?")
    assert not is_stub_question("Which states have the highest unemployment rate?")


# ── D8 / Q13: analyticsSpec rule table ──────────────────────────────────────
def test_analytics_spec_operation_mapping():
    assert build_analytics_spec("comparison", [])["operation"] == "group_aggregate"
    assert build_analytics_spec("ranking", [])["operation"] == "rank"
    assert build_analytics_spec("trend", [])["operation"] == "time_series"
    assert build_analytics_spec("composition", [])["operation"] == "share"
    assert build_analytics_spec("correlation", [])["operation"] == "correlate"
    assert build_analytics_spec("describe", [])["operation"] == "summary_stats"


def test_analytics_spec_roles_and_topn():
    spec = build_analytics_spec(
        "ranking",
        [
            {"entityRef": "LFPR", "role": "measure"},
            {"entityRef": "State", "role": "grouping"},
        ],
    )
    assert spec["measure"] == {"entityRef": "LFPR"}
    assert spec["groupBy"] == [{"entityRef": "State"}]
    assert spec["topN"] == 10
    assert spec["sort"] == {"by": "measure", "order": "desc"}


def test_analytics_spec_normalises_type():
    # Echoed enum must still resolve to a single operation.
    spec = build_analytics_spec("comparison|trend", [])
    assert spec["operation"] == "group_aggregate"


# ── Q12: archetype library ──────────────────────────────────────────────────
def test_archetype_requires_a_measure():
    ents = [{"name": "State", "entityType": "dimension"}]
    assert archetype_questions("Employment", ents) == []


def test_archetype_generates_measure_x_dimension():
    ents = [
        {"name": "LFPR", "entityId": "e_lfpr", "entityType": "measure"},
        {"name": "Gender", "entityId": "e_gender", "entityType": "dimension"},
    ]
    qs = archetype_questions("Labour Force Participation", ents)
    assert len(qs) >= 1
    q0 = qs[0]
    assert q0["questionType"] in QUESTION_TYPES
    assert q0["source"] == "archetype"
    # Must carry a usable analyticsSpec referencing the measure.
    assert q0["analyticsSpec"]["measure"] == {"entityRef": "e_lfpr"}
    # Must reference both entities.
    refs = {re["entityRef"] for re in q0["requiredEntities"]}
    assert "e_lfpr" in refs and "e_gender" in refs


def test_archetype_measure_only_describe():
    ents = [{"name": "GDP", "entityId": "e_gdp", "entityType": "measure"}]
    qs = archetype_questions("Macro", ents)
    assert len(qs) == 1
    assert qs[0]["questionType"] == "describe"


# ── D5 / Q15: unassigned routing ────────────────────────────────────────────
def test_route_matches_by_token_overlap():
    topics = [
        {"topicId": "topic_lfpr", "title": "Labour Force Participation Rate"},
        {"topicId": "topic_wage", "title": "Wages and Earnings"},
    ]
    q = {"intent": "How have wages grown?", "sourceHeading": "Earnings trend"}
    assert route_unassigned(q, topics) == "topic_wage"


def test_route_falls_back_to_general():
    topics = [{"topicId": "topic_lfpr", "title": "Labour Force Participation Rate"}]
    q = {"intent": "What is the capital expenditure outlook?", "sourceHeading": "Budget"}
    assert route_unassigned(q, topics) == "topic_general"
