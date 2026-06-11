"""Tests for Phase 6 provenance + statistical-context enrichment (`lineage`).

Proves the audit chain closes end-to-end:
- table cells, chart points, metrics and narrative numbers each count as measured
  values and are traced;
- a per-plan lineage index carries planId / componentRef / sourceColumns / formulaType
  / filters / analyticsRef / evidenceRef / rowIds;
- auditAST.provenance reports coverage + dataset identity; clean fixture → 100%;
- missing provenance lowers coverage (and the verifier, which shares the same
  measured-value enumeration, fails);
- StatisticalContext (sourceNotes / unitRegistry / geographyLevel / …) is surfaced
  only when present, never invented;
- the PDF provenance appendix lists every measured output.
"""
from __future__ import annotations

import pandas as pd

from report_builder.binding.execution_contracts import (
    ExecutionBundle, FormulaSpec, LineageRef, StatisticalContext,
)
from report_builder.binding.schema import BindingAST
from report_builder.generation.bundle_adapter import AdaptedPlan
from report_builder.generation.lineage import (
    build_lineage_index,
    compute_coverage,
    enrich_report_provenance,
    iter_measured_values,
    provenance_coverage,
)
from report_builder.generation.render.document import build_provenance_appendix
from report_builder.generation.schema import AnalyticsPlanRec, PlanMeasure
from report_builder.generation.verifier import FAIL, verify_report

SCHEMA_ID = "bharatstat/report-output-ast/v1"


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _analytics() -> dict:
    return {
        "plans": [], "executions": [],
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


def _report() -> dict:
    a, e = _analytics(), _evidence()
    return {
        "$schema": SCHEMA_ID, "_doc": "test",
        "metadata": {"coverage": {"questionsTotal": 1, "questionsAnswered": 1},
                     "period": {"current": "2024"}},
        "datasetAST": {}, "bindingAST": {},
        "analyticsAST": a, "evidenceAST": e,
        "contentAST": {"blocks": [{
            "blockId": "p_q1", "kind": "paragraph",
            "content": "Urban salary was 69000.0 and Rural was 51000.0.",
            "slot": {"status": "filled"},
            "provenance": {"questionId": "q1", "analyticsRef": "agg_q1", "evidenceRef": "ev_q1"}}]},
        "tableAST": {"tables": [{
            "tableId": "t_q1", "biQuery": "q1", "slot": {"status": "filled"},
            "provenance": {"questionId": "q1", "analyticsRef": "agg_q1", "evidenceRef": "ev_q1"},
            "rows": [{"sector": "Urban", "sal": 69000.0, "rowIds": ["r:sector=Urban"]},
                     {"sector": "Rural", "sal": 51000.0, "rowIds": ["r:sector=Rural"]}]}]},
        "chartAST": {"charts": [{
            "chartId": "c_q1", "biQuery": "q1", "slot": {"status": "filled"},
            "provenance": {"questionId": "q1", "analyticsRef": "agg_q1", "evidenceRef": "ev_q1"},
            "series": [{"label": "Salary", "points": [
                {"x": "Urban", "y": 69000.0, "rowIds": ["r:sector=Urban"]},
                {"x": "Rural", "y": 51000.0, "rowIds": ["r:sector=Rural"]}]}]}]},
        "figureAST": {"figures": []}, "semanticAST": {"sections": []},
        "auditAST": {"warnings": [], "humanReview": {}},
    }


def _adapted(qid: str = "q1") -> AdaptedPlan:
    rec = AnalyticsPlanRec(
        planId=f"plan_{qid}", questionId=qid, operation="group_aggregate",
        measure=PlanMeasure(columnExpr="sal"), groupBy=["sector"], filters=["age>=15"])
    return AdaptedPlan(
        planRec=rec, questionId=qid, status="EXECUTABLE", measureColumn="sal",
        componentRef="q1_c1",
        formulaSpec=FormulaSpec(type="DIRECT"),
        lineage=LineageRef(sourceQuestionId=qid, sourceColumnIds=["sal", "sector"]))


def _bundle() -> ExecutionBundle:
    return ExecutionBundle(
        templateId="t", datasetId="d", status="READY",
        bindingAst=BindingAST(datasetSignature="sig_abc"),
        dataframeRef={"type": "csv", "contentHash": "sha256:deadbeef"},
        statisticalContext=StatisticalContext(
            geographyLevel="state_ut", sourceNotes=["PLFS 2024-25"],
            unitRegistry={"sal": "INR"}, surveyRound="PLFS Annual 2024-25"))


# ─────────────────────────────────────────────────────────────────────────────
# Measured values + coverage
# ─────────────────────────────────────────────────────────────────────────────

def test_table_chart_metric_are_measured_and_traced():
    mvs = iter_measured_values(_report())
    kinds = {m.kind for m in mvs}
    assert {"block", "chartPoint", "tableRow", "metric"} <= kinds
    assert all(m.traced for m in mvs)        # every value has a provenance trace


def test_clean_fixture_coverage_is_100():
    cov = compute_coverage(_report())
    assert cov.measured > 0
    assert cov.coverage == 1.0
    assert provenance_coverage(_report()) == 1.0


def test_missing_provenance_lowers_coverage():
    rep = _report()
    rep["tableAST"]["tables"][0]["rows"][0].pop("rowIds")    # one untraced row
    cov = compute_coverage(rep)
    assert cov.coverage < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Lineage index
# ─────────────────────────────────────────────────────────────────────────────

def test_lineage_index_carries_full_trace():
    entries = build_lineage_index([_adapted()], _evidence())
    assert len(entries) == 1
    e = entries[0].to_dict()
    assert e["questionId"] == "q1"
    assert e["planId"] == "plan_q1"
    assert e["componentRef"] == "q1_c1"
    assert e["measureColumn"] == "sal"
    assert e["analyticsRef"] == "agg_q1"
    assert e["evidenceRef"] == "ev_q1"
    assert e["sourceColumns"] == ["sal", "sector"]
    assert e["rowIds"] == ["r:sector=Urban", "r:sector=Rural"]
    assert e["formulaType"] == "DIRECT"
    assert e["filters"] == ["age>=15"]


def test_lineage_index_empty_without_plans():
    assert build_lineage_index(None, _evidence()) == []
    assert build_lineage_index([], {}) == []


# ─────────────────────────────────────────────────────────────────────────────
# enrich_report_provenance
# ─────────────────────────────────────────────────────────────────────────────

def test_enrich_populates_audit_provenance():
    rep = _report()
    summary = enrich_report_provenance(rep, adapted=[_adapted()], evidence=_evidence(),
                                       bundle=_bundle())
    audit_prov = rep["auditAST"]["provenance"]
    assert audit_prov["coverage"] == 1.0
    assert audit_prov["measuredValues"] == summary["measuredValues"] > 0
    assert audit_prov["datasetSignature"] == "sig_abc"
    assert audit_prov["contentHash"] == "sha256:deadbeef"
    assert len(audit_prov["entries"]) == 1
    assert audit_prov["entries"][0]["planId"] == "plan_q1"


def test_enrich_adds_plan_trace_to_artifacts_additively():
    rep = _report()
    enrich_report_provenance(rep, adapted=[_adapted()], evidence=_evidence(), bundle=_bundle())
    tprov = rep["tableAST"]["tables"][0]["provenance"]
    # existing fields preserved
    assert tprov["questionId"] == "q1" and tprov["analyticsRef"] == "agg_q1"
    # plan-level fields added
    assert tprov["planId"] == "plan_q1"
    assert tprov["sourceColumns"] == ["sal", "sector"]
    assert tprov["formulaType"] == "DIRECT"
    assert tprov["componentRef"] == "q1_c1"


def test_enrich_surfaces_statistical_context_when_present():
    rep = _report()
    enrich_report_provenance(rep, adapted=[_adapted()], evidence=_evidence(), bundle=_bundle())
    stat = rep["auditAST"]["statisticalContext"]
    assert stat["geographyLevel"] == "state_ut"
    assert stat["sourceNotes"] == ["PLFS 2024-25"]
    assert stat["unitRegistry"] == {"sal": "INR"}
    assert stat["surveyRound"] == "PLFS Annual 2024-25"


def test_enrich_does_not_invent_context_without_bundle():
    rep = _report()
    enrich_report_provenance(rep, adapted=[_adapted()], evidence=_evidence())  # no bundle
    assert "statisticalContext" not in rep["auditAST"]   # nothing invented
    assert rep["auditAST"]["provenance"]["datasetSignature"] == ""


def test_enrich_legacy_path_no_plans_still_valid():
    rep = _report()
    summary = enrich_report_provenance(rep)               # no adapted / evidence / bundle
    assert summary["coverage"] == 1.0                     # computed from report alone
    assert summary["entries"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Provenance appendix lists measured outputs
# ─────────────────────────────────────────────────────────────────────────────

def test_appendix_lists_measured_outputs_from_entries():
    rep = _report()
    enrich_report_provenance(rep, adapted=[_adapted()], evidence=_evidence(), bundle=_bundle())
    html = build_provenance_appendix(rep)
    assert "Appendix: Provenance" in html
    assert "q1" in html and "plan_q1" in html
    assert "r:sector=Urban" in html


def test_appendix_empty_when_nothing():
    rep = {"auditAST": {}, "contentAST": {"blocks": []}}
    assert build_provenance_appendix(rep) == ""


# ─────────────────────────────────────────────────────────────────────────────
# Verifier shares the same measured-value enumeration
# ─────────────────────────────────────────────────────────────────────────────

def test_verifier_agrees_with_coverage_on_missing_provenance():
    rep = _report()
    rep["tableAST"]["tables"][0]["rows"][0].pop("rowIds")
    rep["contentAST"]["blocks"][0].pop("provenance")
    a, e = rep["analyticsAST"], rep["evidenceAST"]
    vr = verify_report(rep, a, e)
    assert vr.verdict == FAIL
    assert vr.quality["provenanceCoverage"] < 1.0
    # the verifier's coverage matches the standalone audit coverage (one source of truth)
    assert vr.quality["provenanceCoverage"] == round(compute_coverage(rep).coverage, 3)
