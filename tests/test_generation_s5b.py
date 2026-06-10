"""S5b gate tests — the narrator turns analytics facts into value-safe prose.

Covers the 3-tier ladder (deterministic floor, LTM commentary, gated LLM rewrite),
the number validator that guards every tier, provenance wiring, and offline
behaviour. No network/LLM/DB — Tier 1 and Tier 2 are exercised with stubs.
"""
from __future__ import annotations

import pandas as pd

from report_builder.binding.schema import (
    BindingAST, BoundColumn, EntityBinding, QuestionBinding, ResolvedRoles, ResolvedFilter,
)
from report_builder.generation.planner_adapter import build_plans
from report_builder.generation.executor import run_analytics
from report_builder.generation.narrator import narrate, narrate_block, validate_numbers, _build_facts, _Index


# ── fixtures ──────────────────────────────────────────────────────────────────

def _wpr_template() -> dict:
    return {"contentAST": {"blocks": [{
        "blockId": "p_wpr_intro", "kind": "paragraph", "styleRef": "s_body",
        "content": "", "biQuery": "q_wpr_01",
        "templateQuestion": "Compare WPR across sector for the current period.",
        "slot": {"fillFrom": "q_wpr_01_c1", "status": "empty"},
    }]}}


def _wpr_analytics():
    binding = BindingAST(templateId="t", datasetId="d",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="WPR", entityType="measure",
                          columns=[BoundColumn(column="wpr")]),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                          columns=[BoundColumn(column="sector")]),
        ],
        questionBindings=[QuestionBinding(questionId="q_wpr_01", status="executable",
            resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["sector"],
                                        filters=[ResolvedFilter(column="age", op="ge", value=15)]))])
    bp = {"entities": [], "topics": [{"topicId": "t", "questions": [{
        "questionId": "q_wpr_01", "questionType": "comparison",
        "analyticsSpec": {"operation": "group_aggregate",
                          "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                          "groupBy": [{"entityRef": "ent_sector"}],
                          "sort": {"by": "measure", "order": "desc"}},
        "answerStructure": {"components": [{"componentId": "q_wpr_01_c1"}]}}]}]}
    frame = pd.DataFrame([
        {"wpr": 56.3, "sector": "Rural", "age": 30}, {"wpr": 56.3, "sector": "Rural", "age": 40},
        {"wpr": 47.1, "sector": "Urban", "age": 25}, {"wpr": 47.1, "sector": "Urban", "age": 35}])
    plans = build_plans(bp, binding, None)
    analytics, evidence, _ = run_analytics(plans, frame,
        question_meta={"q_wpr_01": {"label": "Worker Population Ratio"}})
    return analytics.to_dict(), evidence.to_dict()


_QCFG = {"q_wpr_01": {"measureLabel": "Worker Population Ratio", "measureShort": "WPR",
                      "dimensionNoun": "sector", "forClause": " for persons aged 15 years and above",
                      "unit": "percent"}}


# ── value validator ───────────────────────────────────────────────────────────

def test_validator_accepts_facts_and_gaps():
    allowed = {56.3, 47.1, 9.2, 53.4}
    ok, bad = validate_numbers("Rural 56.3% vs urban 47.1%, a gap of 9.2 points.", allowed)
    assert ok and bad == []


def test_validator_rejects_hallucinated_number():
    allowed = {56.3, 47.1, 9.2}
    ok, bad = validate_numbers("WPR rose to 71.4% in rural areas.", allowed)
    assert not ok and "71.4" in bad


def test_validator_ignores_period_label():
    allowed = {53.4}
    ok, bad = validate_numbers("In 2023-24, WPR was 53.4%.", allowed, ignore=["2023-24"])
    assert ok and bad == []


# ── Tier 0 deterministic floor ────────────────────────────────────────────────

def test_deterministic_floor_states_correct_numbers():
    analytics, evidence = _wpr_analytics()
    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG, use_llm=False)
    block = out["contentAST"]["blocks"][0]
    text = block["content"]
    assert "56.3%" in text and "47.1%" in text
    assert "9.2 percentage points" in text          # derived gap validates
    assert "Worker Population Ratio" in text
    assert "2023-24" in text
    assert out["narrativeTrace"][0]["tier"] == "deterministic"
    assert out["narrativeTrace"][0]["validated"] is True


def test_provenance_and_component_wiring():
    analytics, evidence = _wpr_analytics()
    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG, use_llm=False)
    prov = out["contentAST"]["blocks"][0]["provenance"]
    assert prov["questionId"] == "q_wpr_01"
    assert prov["componentId"] == "q_wpr_01_c1"      # from slot.fillFrom
    assert prov["evidenceRef"] == "ev_q_wpr_01"
    # metric present → analyticsRef points at the all-India metric (gold convention)
    assert prov["analyticsRef"] == "m_q_wpr_01"
    assert out["contentAST"]["blocks"][0]["slot"]["status"] == "filled"


def test_every_number_in_output_validates():
    analytics, evidence = _wpr_analytics()
    facts = _build_facts("q_wpr_01", _Index(analytics, evidence), _QCFG["q_wpr_01"],
                         {"period": {"current": "2023-24"}})
    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG, use_llm=False)
    text = out["contentAST"]["blocks"][0]["content"]
    ok, bad = validate_numbers(text, facts.allowed_values(), ignore=["2023-24"])
    assert ok, f"unexpected numbers {bad}"


# ── Tier 1 LTM-grounded commentary ────────────────────────────────────────────

def test_ltm_clause_appended_when_numberless():
    analytics, evidence = _wpr_analytics()
    clause = "This reflects the larger share of self-employment in rural areas"

    def ltm(query, *, indicator, question_type):
        return [clause]

    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG,
                  ltm=ltm, use_llm=False)
    text = out["contentAST"]["blocks"][0]["content"]
    assert clause in text
    assert out["narrativeTrace"][0]["tier"] == "ltm_grounded"
    assert out["narrativeTrace"][0]["ltmHits"] == 1


def test_ltm_clause_with_number_is_rejected():
    analytics, evidence = _wpr_analytics()

    def ltm(query, *, indicator, question_type):
        return ["WPR will reach 80% by 2030"]    # has numbers → filtered out, unsafe

    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG,
                  ltm=ltm, use_llm=False)
    text = out["contentAST"]["blocks"][0]["content"]
    assert "80%" not in text
    assert out["narrativeTrace"][0]["tier"] == "deterministic"
    assert out["narrativeTrace"][0]["ltmHits"] == 0


# ── Tier 2 gated LLM rewrite ──────────────────────────────────────────────────

def test_llm_rewrite_accepted_when_numbers_valid():
    analytics, evidence = _wpr_analytics()
    good = ("In 2023-24, the Worker Population Ratio stood at 56.3% in rural areas and "
            "47.1% in urban areas, a gap of 9.2 percentage points.")

    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG,
                  llm_call=lambda prompt: good, use_llm=True)
    block = out["contentAST"]["blocks"][0]
    assert block["content"] == good
    tr = out["narrativeTrace"][0]
    assert tr["tier"] == "llm" and tr["llmUsed"] is True and tr["fallback"] is False


def test_llm_rewrite_rejected_falls_back_to_deterministic():
    analytics, evidence = _wpr_analytics()
    bad = "Rural WPR surged to 90.0% — the highest on record."

    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG,
                  llm_call=lambda prompt: bad, use_llm=True)
    block = out["contentAST"]["blocks"][0]
    assert "90.0%" not in block["content"]
    tr = out["narrativeTrace"][0]
    assert tr["tier"] == "deterministic" and tr["llmUsed"] is True and tr["fallback"] is True


def test_offline_default_uses_deterministic(monkeypatch):
    analytics, evidence = _wpr_analytics()
    monkeypatch.setenv("LLM_DISABLED", "1")
    out = narrate(_wpr_template(), analytics, evidence,
                  context={"period": {"current": "2023-24"}}, questions=_QCFG)  # use_llm=None → auto
    tr = out["narrativeTrace"][0]
    assert tr["tier"] == "deterministic" and tr["llmUsed"] is False


# ── ranking narration ─────────────────────────────────────────────────────────

def test_ranking_question_narration():
    binding = BindingAST(templateId="t", datasetId="d",
        entityBindings=[
            EntityBinding(entityId="ent_wpr", entityName="WPR", entityType="measure",
                          columns=[BoundColumn(column="wpr")]),
            EntityBinding(entityId="ent_state", entityName="State", entityType="dimension",
                          columns=[BoundColumn(column="state")]),
        ],
        questionBindings=[QuestionBinding(questionId="q_rank_01", status="executable",
            resolvedRoles=ResolvedRoles(measures=["wpr"], dimensions=["state"]))])
    bp = {"entities": [], "topics": [{"topicId": "t", "questions": [{
        "questionId": "q_rank_01", "questionType": "ranking",
        "analyticsSpec": {"operation": "rank",
                          "measure": {"entityRef": "ent_wpr", "agg": "mean"},
                          "groupBy": [{"entityRef": "ent_state"}],
                          "sort": {"by": "measure", "order": "desc"}, "topN": 3},
        "answerStructure": {"components": []}}]}]}
    frame = pd.DataFrame([
        {"wpr": 65.1, "state": "HP"}, {"wpr": 63.0, "state": "SK"}, {"wpr": 50.0, "state": "MH"}])
    plans = build_plans(bp, binding, None)
    analytics, evidence, _ = run_analytics(plans, frame)
    template = {"contentAST": {"blocks": [{
        "blockId": "p_rank", "kind": "paragraph", "content": "", "biQuery": "q_rank_01",
        "slot": {"fillFrom": "q_rank_01", "status": "empty"}}]}}
    out = narrate(template, analytics.to_dict(), evidence.to_dict(),
                  questions={"q_rank_01": {"measureLabel": "WPR", "unit": "percent"}}, use_llm=False)
    text = out["contentAST"]["blocks"][0]["content"]
    assert text.startswith("HP recorded the highest WPR at 65.1%")
    assert "SK (63.0%)" in text and "MH (50.0%)" in text
    ok, bad = validate_numbers(text, _build_facts(
        "q_rank_01", _Index(analytics.to_dict(), evidence.to_dict()),
        {"measureLabel": "WPR", "unit": "percent"}, {}).allowed_values())
    assert ok, bad
