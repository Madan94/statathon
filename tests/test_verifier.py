"""Tests for the verifier gate + report quality score (`verifier.verify_report`).

The verifier is a judge, not a fixer: these tests assert it *detects* trust problems
(missing provenance, BLOCKED leak, content-hash drift, fabricated narrative numbers)
and rewards a clean report with a high quality score — without ever mutating input.
"""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from report_builder.binding.execution_contracts import (
    ExecutionBundle, FormulaSpec, NormalizationPlan,
)
from report_builder.generation.bundle_adapter import AdaptedPlan
from report_builder.generation.schema import AnalyticsPlanRec, PlanMeasure
from report_builder.generation.verifier import FAIL, PASS, WARN, verify_report


# ─────────────────────────────────────────────────────────────────────────────
# Builders — a minimal-but-valid gold report + matching analytics/evidence
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_ID = "bharatstat/report-output-ast/v1"
TOP_KEYS = (
    "$schema", "_doc", "metadata", "datasetAST", "bindingAST", "analyticsAST",
    "evidenceAST", "contentAST", "tableAST", "chartAST", "figureAST",
    "semanticAST", "auditAST",
)


def _analytics() -> dict:
    return {
        "plans": [], "executions": [
            {"executionId": "exec_q1", "planRef": "plan_q1", "engine": "pandas",
             "rowsScanned": 4, "ms": 0, "status": "ok"}],
        "aggregations": [{
            "aggId": "agg_q1", "questionId": "q1", "groupBy": "sector", "measure": "sal",
            "rows": [
                {"key": {"sector": "Urban"}, "value": 69000.0, "n": 2, "rowIds": ["r:sector=Urban"]},
                {"key": {"sector": "Rural"}, "value": 51000.0, "n": 2, "rowIds": ["r:sector=Rural"]}]}],
        "rankings": [], "trends": [],
        "metrics": [{"metricId": "m_q1", "questionId": "q1", "label": "Avg Salary",
                     "value": 60000.0, "rowIds": ["r:all"]}],
    }


def _evidence() -> dict:
    return {"evidence": [{
        "evidenceId": "ev_q1", "questionId": "q1", "componentId": "", "kind": "aggregation",
        "analyticsRef": "agg_q1", "columns": ["sal", "sector"],
        "rowIds": ["r:sector=Urban", "r:sector=Rural"], "computation": "mean",
        "value": 60000.0, "confidence": 0.95}]}


def _report(analytics: dict, evidence: dict, *, narrative: str = "",
            warnings: list[str] | None = None, period: str = "2024") -> dict:
    return {
        "$schema": SCHEMA_ID,
        "_doc": "test",
        "metadata": {"coverage": {"questionsTotal": 1, "questionsAnswered": 1},
                     "period": {"current": period}},
        "datasetAST": {}, "bindingAST": {},
        "analyticsAST": analytics, "evidenceAST": evidence,
        "contentAST": {"blocks": [{
            "blockId": "p_q1", "kind": "paragraph",
            "content": narrative or "Urban salary was 69000.0 and Rural was 51000.0.",
            "slot": {"status": "filled"},
            "provenance": {"evidenceRef": "ev_q1", "analyticsRef": "agg_q1"}}]},
        "tableAST": {"tables": [{
            "tableId": "t_q1", "slot": {"status": "filled"},
            "rows": [{"cells": ["Urban", 69000.0], "rowIds": ["r:sector=Urban"]},
                     {"cells": ["Rural", 51000.0], "rowIds": ["r:sector=Rural"]}]}]},
        "chartAST": {"charts": []}, "figureAST": {"figures": []},
        "semanticAST": {"sections": []},
        "auditAST": {"warnings": list(warnings or []), "humanReview": {}},
    }


def _row_index() -> dict:
    return {"r:sector=Urban": [2, 3], "r:sector=Rural": [0, 1], "r:all": [0, 1, 2, 3]}


def _adapted_share(qid: str = "q_share", *, status: str = "EXECUTABLE",
                   normalization: NormalizationPlan | None = None) -> AdaptedPlan:
    rec = AnalyticsPlanRec(
        planId=f"plan_{qid}", questionId=qid, operation="group_aggregate",
        measure=PlanMeasure(columnExpr="literate"), groupBy=["State"])
    return AdaptedPlan(
        planRec=rec, questionId=qid, status=status, measureColumn="literate",
        formulaSpec=FormulaSpec(type="SHARE", numeratorColumn="literate",
                                denominatorColumn="population", multiplier=100.0),
        normalizationPlan=normalization or NormalizationPlan(type="NONE"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Clean report → PASS + high score
# ─────────────────────────────────────────────────────────────────────────────

def test_clean_report_passes():
    a, e = _analytics(), _evidence()
    vr = verify_report(_report(a, e), a, e, row_index=_row_index())
    assert vr.verdict == PASS
    assert all(c.severity != "fail" for c in vr.checks)


def test_clean_report_quality_score_high():
    a, e = _analytics(), _evidence()
    vr = verify_report(_report(a, e), a, e, row_index=_row_index())
    assert vr.quality["finalScore"] >= 90.0
    assert vr.quality["provenanceCoverage"] == 1.0
    assert vr.quality["blockedLeakCount"] == 0


def test_verifier_does_not_mutate_inputs():
    a, e = _analytics(), _evidence()
    report = _report(a, e)
    snap = copy.deepcopy(report)
    verify_report(report, a, e, row_index=_row_index())
    assert report == snap          # judge, never fixer


# ─────────────────────────────────────────────────────────────────────────────
# 2. Missing provenance → FAIL
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_provenance_fails():
    a, e = _analytics(), _evidence()
    report = _report(a, e)
    report["tableAST"]["tables"][0]["rows"][0].pop("rowIds")     # strip a row's trace
    report["contentAST"]["blocks"][0].pop("provenance")          # and the block's
    vr = verify_report(report, a, e, row_index=_row_index())
    assert vr.verdict == FAIL
    assert any(c.code == "PROVENANCE" and c.severity == "fail" for c in vr.checks)
    assert vr.quality["provenanceCoverage"] < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. BLOCKED plan leak → FAIL
# ─────────────────────────────────────────────────────────────────────────────

def test_blocked_plan_leak_fails():
    a, e = _analytics(), _evidence()
    # A BLOCKED plan for q1 — yet q1 has an aggregation value in analytics → leak.
    rec = AnalyticsPlanRec(planId="plan_q1", questionId="q1",
                           measure=PlanMeasure(columnExpr="sal"), groupBy=["sector"])
    blocked = AdaptedPlan(planRec=rec, questionId="q1", status="BLOCKED",
                          measureColumn="sal", formulaSpec=FormulaSpec(type="SHARE",
                          numeratorColumn="sal", denominatorColumn=""))
    vr = verify_report(_report(a, e), a, e, adapted=[blocked], row_index=_row_index())
    assert vr.verdict == FAIL
    assert any(c.code == "NO_BLOCKED_LEAK" and c.severity == "fail" for c in vr.checks)
    assert vr.quality["blockedLeakCount"] >= 1


def test_blocked_leak_via_skipped_execution():
    a, e = _analytics(), _evidence()
    a["executions"].append({"executionId": "exec_q1", "planRef": "plan_q1",
                            "engine": "skipped", "status": "skipped"})
    vr = verify_report(_report(a, e), a, e, row_index=_row_index())
    assert vr.verdict == FAIL
    assert vr.quality["blockedLeakCount"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. DEGRADED plan without a caveat → WARN
# ─────────────────────────────────────────────────────────────────────────────

def test_degraded_without_caveat_warns():
    a, e = _analytics(), _evidence()
    degraded = _adapted_share("q_deg", status="DEGRADED")
    degraded.diagnostics = ["zero denominator for group X"]
    vr = verify_report(_report(a, e), a, e, adapted=[degraded], row_index=_row_index())
    assert vr.verdict == WARN
    assert any(c.code == "CAVEAT_VISIBILITY" and c.severity == "warn" for c in vr.checks)


def test_degraded_with_visible_caveat_passes():
    a, e = _analytics(), _evidence()
    degraded = _adapted_share("q_deg", status="DEGRADED")
    degraded.diagnostics = ["zero denominator"]
    # caveat surfaced in the audit warnings (mentions the question id)
    report = _report(a, e, warnings=["q_deg: zero denominator for group X"])
    vr = verify_report(report, a, e, adapted=[degraded], row_index=_row_index())
    assert any(c.code == "CAVEAT_VISIBILITY" and c.severity == "pass" for c in vr.checks)


# ─────────────────────────────────────────────────────────────────────────────
# 5. contentHash mismatch → FAIL
# ─────────────────────────────────────────────────────────────────────────────

def test_content_hash_mismatch_fails():
    a, e = _analytics(), _evidence()
    bundle = ExecutionBundle(templateId="t", datasetId="d", status="READY",
                             dataframeRef={"type": "csv", "contentHash": "sha256:aaaa"})
    vr = verify_report(_report(a, e), a, e, bundle=bundle, content_hash="sha256:bbbb",
                       row_index=_row_index())
    assert vr.verdict == FAIL
    assert any(c.code == "CONTENT_HASH" and c.severity == "fail" for c in vr.checks)


def test_content_hash_match_passes():
    a, e = _analytics(), _evidence()
    bundle = ExecutionBundle(templateId="t", datasetId="d", status="READY",
                             dataframeRef={"type": "csv", "contentHash": "sha256:aaaa"})
    vr = verify_report(_report(a, e), a, e, bundle=bundle, content_hash="sha256:aaaa",
                       row_index=_row_index())
    assert any(c.code == "CONTENT_HASH" and c.severity == "pass" for c in vr.checks)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Narrative number mismatch → FAIL
# ─────────────────────────────────────────────────────────────────────────────

def test_narrative_number_mismatch_fails():
    a, e = _analytics(), _evidence()
    # 88888 is not an analytics value → fabricated number.
    report = _report(a, e, narrative="Urban salary was 88888.0 this year.")
    vr = verify_report(report, a, e, row_index=_row_index())
    assert vr.verdict == FAIL
    assert any(c.code == "NARRATIVE_NUMBERS" and c.severity == "fail" for c in vr.checks)
    assert vr.quality["verifiedNumberRatio"] < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 7. Formula recompute — supported recomputes, unsupported WARNs (never crashes)
# ─────────────────────────────────────────────────────────────────────────────

def test_formula_recompute_share_matches():
    # analytics with a SHARE aggregation that IS recomputable from the data
    a = {
        "plans": [], "executions": [],
        "aggregations": [{"aggId": "agg_q_share", "questionId": "q_share",
                          "groupBy": "State", "measure": "literate",
                          "rows": [
                              {"key": {"State": "Kerala"}, "value": 90.0, "n": 2, "rowIds": ["r:State=Kerala"]},
                              {"key": {"State": "Bihar"}, "value": 60.0, "n": 2, "rowIds": ["r:State=Bihar"]}]}],
        "rankings": [], "trends": [], "metrics": [],
    }
    e = {"evidence": [{"evidenceId": "ev_q_share", "questionId": "q_share",
                       "analyticsRef": "agg_q_share", "kind": "aggregation",
                       "rowIds": ["r:State=Kerala", "r:State=Bihar"]}]}
    df = pd.DataFrame({
        "State": ["Kerala", "Kerala", "Bihar", "Bihar"],
        "literate": [90, 810, 30, 570], "population": [100, 900, 100, 900]})
    report = _report(a, e, narrative="Kerala share was 90.0 and Bihar was 60.0.")
    report["tableAST"]["tables"][0]["rows"] = [
        {"cells": ["Kerala", 90.0], "rowIds": ["r:State=Kerala"]},
        {"cells": ["Bihar", 60.0], "rowIds": ["r:State=Bihar"]}]
    report["contentAST"]["blocks"][0]["provenance"] = {"evidenceRef": "ev_q_share"}
    ri = {"r:State=Kerala": [0, 1], "r:State=Bihar": [2, 3]}

    vr = verify_report(report, a, e, adapted=[_adapted_share("q_share")], dataframe=df, row_index=ri)
    assert any(c.code == "FORMULA_RECOMPUTE" and c.severity == "pass" for c in vr.checks)
    assert vr.quality["formulaCoverage"] == 1.0


def test_unsupported_formula_recompute_warns_not_crash():
    a, e = _analytics(), _evidence()
    rec = AnalyticsPlanRec(planId="plan_q1", questionId="q1",
                           measure=PlanMeasure(columnExpr="sal"), groupBy=["sector"])
    cagr = AdaptedPlan(planRec=rec, questionId="q1", status="EXECUTABLE", measureColumn="sal",
                       formulaSpec=FormulaSpec(type="CAGR", timeWindow={"current": 2020,
                       "prior": 2015, "periods": 5}), timeColumn="year")
    df = pd.DataFrame({"sector": ["Urban", "Rural"], "sal": [69000, 51000]})
    vr = verify_report(_report(a, e), a, e, adapted=[cagr], dataframe=df, row_index=_row_index())
    rc = [c for c in vr.checks if c.code == "FORMULA_RECOMPUTE"]
    assert rc and rc[0].severity == "warn"      # unsupported type → warn, no crash
    assert vr.verdict in (WARN, PASS)


def test_formula_recompute_mismatch_fails():
    # report claims Bihar share 99.0 but the data says 60.0
    a = {
        "plans": [], "executions": [],
        "aggregations": [{"aggId": "agg_q_share", "questionId": "q_share",
                          "groupBy": "State", "measure": "literate",
                          "rows": [
                              {"key": {"State": "Kerala"}, "value": 90.0, "n": 2, "rowIds": ["r:State=Kerala"]},
                              {"key": {"State": "Bihar"}, "value": 99.0, "n": 2, "rowIds": ["r:State=Bihar"]}]}],
        "rankings": [], "trends": [], "metrics": [],
    }
    e = {"evidence": [{"evidenceId": "ev_q_share", "questionId": "q_share",
                       "analyticsRef": "agg_q_share", "kind": "aggregation",
                       "rowIds": ["r:State=Kerala", "r:State=Bihar"]}]}
    df = pd.DataFrame({
        "State": ["Kerala", "Kerala", "Bihar", "Bihar"],
        "literate": [90, 810, 30, 570], "population": [100, 900, 100, 900]})
    report = _report(a, e, narrative="Shares computed.")
    report["tableAST"]["tables"][0]["rows"] = [
        {"cells": ["Bihar", 99.0], "rowIds": ["r:State=Bihar"]}]
    report["contentAST"]["blocks"][0]["provenance"] = {"evidenceRef": "ev_q_share"}
    ri = {"r:State=Kerala": [0, 1], "r:State=Bihar": [2, 3]}

    vr = verify_report(report, a, e, adapted=[_adapted_share("q_share")], dataframe=df, row_index=ri)
    assert vr.verdict == FAIL
    assert any(c.code == "FORMULA_RECOMPUTE" and c.severity == "fail" for c in vr.checks)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Corrupted report quality drops below clean
# ─────────────────────────────────────────────────────────────────────────────

def test_corrupted_quality_score_drops():
    a, e = _analytics(), _evidence()
    clean = verify_report(_report(a, e), a, e, row_index=_row_index()).quality["finalScore"]

    corrupt = _report(a, e)
    corrupt["tableAST"]["tables"][0]["rows"][0].pop("rowIds")
    corrupt["contentAST"]["blocks"][0].pop("provenance")
    dropped = verify_report(corrupt, a, e, row_index=_row_index()).quality["finalScore"]

    assert dropped < clean


# ─────────────────────────────────────────────────────────────────────────────
# 9. to_dict round-trip (for persistence into auditAST)
# ─────────────────────────────────────────────────────────────────────────────

def test_verification_report_to_dict():
    a, e = _analytics(), _evidence()
    d = verify_report(_report(a, e), a, e, row_index=_row_index()).to_dict()
    assert d["verdict"] in (PASS, WARN, FAIL)
    assert isinstance(d["checks"], list) and d["checks"]
    assert "finalScore" in d["quality"]
