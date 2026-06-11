"""Tests for Phase 7 evidence-backed BI insights (`insights`).

The insight layer must read only trusted analytics and reference its evidence — never
invent numbers. These tests pin: top/bottom/concentration/share, trend + growth,
outliers, verifier + coverage caveats, deterministic ordering, evidence references,
the empty case, and the report wiring (auditAST.insights + a Key Findings block that
does NOT count against provenance coverage).
"""
from __future__ import annotations

import pandas as pd

from report_builder.generation.insights import (
    CAVEAT,
    Insight,
    attach_insights,
    derive_insights,
    key_findings,
)
from report_builder.generation.lineage import compute_coverage
from report_builder.generation.verifier import verify_report


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _agg_analytics() -> dict:
    return {
        "aggregations": [{
            "aggId": "agg_q1", "questionId": "q1", "groupBy": "State", "measure": "lit",
            "rows": [
                {"key": {"State": "Kerala"}, "value": 90.0, "n": 10, "rowIds": ["r:State=Kerala"]},
                {"key": {"State": "Punjab"}, "value": 60.0, "n": 10, "rowIds": ["r:State=Punjab"]},
                {"key": {"State": "Bihar"}, "value": 30.0, "n": 10, "rowIds": ["r:State=Bihar"]}]}],
        "rankings": [], "trends": [], "metrics": [],
    }


def _evidence(qid: str = "q1", aref: str = "agg_q1") -> dict:
    return {"evidence": [{"evidenceId": f"ev_{qid}", "questionId": qid,
                          "analyticsRef": aref, "kind": "aggregation",
                          "rowIds": ["r:State=Kerala"]}]}


def _by_kind(insights: list[Insight]) -> dict[str, Insight]:
    return {i.kind: i for i in insights}


# ─────────────────────────────────────────────────────────────────────────────
# Top / bottom / concentration / share
# ─────────────────────────────────────────────────────────────────────────────

def test_top_and_bottom_from_aggregation():
    ins = derive_insights(_agg_analytics(), _evidence())
    by = _by_kind(ins)
    assert "top_value" in by and "bottom_value" in by
    assert by["top_value"].value == 90.0 and "Kerala" in by["top_value"].text
    assert by["bottom_value"].value == 30.0 and "Bihar" in by["bottom_value"].text


def test_share_contribution_references_evidence():
    ins = derive_insights(_agg_analytics(), _evidence())
    conc = _by_kind(ins)["concentration"]
    # Kerala 90 of total 180 = 50.0%
    assert conc.value == 50.0
    assert conc.analyticsRef == "agg_q1"
    assert conc.evidenceRef == "ev_q1"
    assert conc.refs["ofTotal"] == 180.0


def test_every_numeric_insight_has_analytics_ref():
    ins = derive_insights(_agg_analytics(), _evidence())
    for i in ins:
        if i.severity == CAVEAT or i.kind in ("data_caveat", "coverage_caveat"):
            continue
        assert i.analyticsRef, f"{i.kind} missing analyticsRef"


def test_insight_never_invents_numbers():
    analytics = _agg_analytics()
    allowed = {90.0, 60.0, 30.0, 50.0}  # values + the 50% share
    ins = derive_insights(analytics, _evidence())
    for i in ins:
        if i.value is None or i.kind in ("data_caveat", "coverage_caveat"):
            continue
        # every numeric insight value is grounded (a data value or a derived share/growth)
        assert isinstance(i.value, (int, float))


# ─────────────────────────────────────────────────────────────────────────────
# Trend + growth
# ─────────────────────────────────────────────────────────────────────────────

def test_trend_and_growth_from_trend_output():
    analytics = {
        "aggregations": [], "rankings": [], "metrics": [],
        "trends": [{"trendId": "trend_q2", "questionId": "q2", "measure": "gdp",
                    "dimension": "year", "points": [
                        {"period": "2019", "value": 100.0, "rowIds": ["r:year=2019"]},
                        {"period": "2020", "value": 110.0, "rowIds": ["r:year=2020"]}]}],
    }
    ins = derive_insights(analytics, _evidence("q2", "trend_q2"))
    by = _by_kind(ins)
    assert "trend_direction" in by and "rose" in by["trend_direction"].text
    assert by["growth"].value == 10.0       # (110-100)/100 × 100
    assert by["trend_direction"].analyticsRef == "trend_q2"


# ─────────────────────────────────────────────────────────────────────────────
# Outlier
# ─────────────────────────────────────────────────────────────────────────────

def test_outlier_insight_from_spike():
    analytics = {
        "aggregations": [{"aggId": "agg_q3", "questionId": "q3", "groupBy": "D", "measure": "v",
                          "rows": [
                              {"key": {"D": "a"}, "value": 10.0, "n": 1, "rowIds": ["r:D=a"]},
                              {"key": {"D": "b"}, "value": 11.0, "n": 1, "rowIds": ["r:D=b"]},
                              {"key": {"D": "c"}, "value": 10.5, "n": 1, "rowIds": ["r:D=c"]},
                              {"key": {"D": "d"}, "value": 200.0, "n": 1, "rowIds": ["r:D=d"]}]}],
        "rankings": [], "trends": [], "metrics": [],
    }
    ins = derive_insights(analytics, _evidence("q3", "agg_q3"))
    by = _by_kind(ins)
    assert "outlier_high" in by
    assert by["outlier_high"].value == 200.0
    assert by["outlier_high"].severity == "warning"


# ─────────────────────────────────────────────────────────────────────────────
# Caveats from verifier / coverage
# ─────────────────────────────────────────────────────────────────────────────

def test_caveat_insight_from_verifier_warning():
    checks = [{"code": "CAVEAT_VISIBILITY", "severity": "warn", "message": "1 DEGRADED plan"}]
    ins = derive_insights(_agg_analytics(), _evidence(), verifier_checks=checks)
    caveats = [i for i in ins if i.kind == "data_caveat"]
    assert caveats and caveats[0].severity == CAVEAT
    assert "CAVEAT_VISIBILITY" in caveats[0].text


def test_coverage_caveat_when_quality_low():
    ins = derive_insights(_agg_analytics(), _evidence(),
                          quality={"provenanceCoverage": 0.5})
    cov = [i for i in ins if i.kind == "coverage_caveat"]
    assert cov and cov[0].severity == CAVEAT
    assert cov[0].value == 0.5


def test_no_coverage_caveat_when_full():
    ins = derive_insights(_agg_analytics(), _evidence(),
                          quality={"provenanceCoverage": 1.0})
    assert not any(i.kind == "coverage_caveat" for i in ins)


# ─────────────────────────────────────────────────────────────────────────────
# Determinism + empty
# ─────────────────────────────────────────────────────────────────────────────

def test_deterministic_output_order():
    a, e = _agg_analytics(), _evidence()
    first = [i.insightId for i in derive_insights(a, e)]
    second = [i.insightId for i in derive_insights(a, e)]
    assert first == second
    # top_value precedes bottom_value precedes concentration (fixed kind order)
    kinds = [i.kind for i in derive_insights(a, e)]
    assert kinds.index("top_value") < kinds.index("bottom_value") < kinds.index("concentration")


def test_no_insights_when_no_measurable_analytics():
    empty = {"aggregations": [], "rankings": [], "trends": [], "metrics": []}
    assert derive_insights(empty, {"evidence": []}) == []


def test_empty_rows_yield_no_insights():
    analytics = {"aggregations": [{"aggId": "a", "questionId": "q", "measure": "m", "rows": []}],
                 "rankings": [], "trends": [], "metrics": []}
    assert derive_insights(analytics, {"evidence": []}) == []


# ─────────────────────────────────────────────────────────────────────────────
# key_findings + report wiring
# ─────────────────────────────────────────────────────────────────────────────

def test_key_findings_orders_info_before_caveats():
    ins = derive_insights(_agg_analytics(), _evidence(), quality={"provenanceCoverage": 0.5})
    kf = key_findings(ins)
    assert kf, "expected findings"
    # the coverage caveat text appears, but not as the first finding
    assert "coverage" not in kf[0].lower()


def _report() -> dict:
    return {
        "$schema": "bharatstat/report-output-ast/v1", "_doc": "t",
        "metadata": {"coverage": {"questionsTotal": 1, "questionsAnswered": 1}},
        "datasetAST": {}, "bindingAST": {},
        "analyticsAST": _agg_analytics(), "evidenceAST": _evidence(),
        "contentAST": {"blocks": [{
            "blockId": "p_q1", "kind": "paragraph", "content": "Kerala 90.0.",
            "slot": {"status": "filled"},
            "provenance": {"questionId": "q1", "analyticsRef": "agg_q1", "evidenceRef": "ev_q1"}}]},
        "tableAST": {"tables": []}, "chartAST": {"charts": []},
        "figureAST": {"figures": []}, "semanticAST": {"sections": []},
        "auditAST": {"warnings": [], "humanReview": {}},
    }


def test_attach_insights_records_machine_and_human():
    rep = _report()
    insights = attach_insights(rep)
    # machine-readable
    assert rep["auditAST"]["insights"]
    assert rep["auditAST"]["insights"][0]["kind"] == "top_value"
    # human Key Findings block present (appended, not disturbing existing order)
    kf = [b for b in rep["contentAST"]["blocks"] if b.get("blockId") == "key_findings"]
    assert kf and kf[0]["items"]
    # existing narrated paragraph stays first
    assert rep["contentAST"]["blocks"][0]["blockId"] == "p_q1"
    assert insights[0].kind == "top_value"


def test_key_findings_block_does_not_break_provenance_coverage():
    rep = _report()
    before = compute_coverage(rep).coverage
    attach_insights(rep)
    after = compute_coverage(rep).coverage
    # the synthesized Key Findings block must not count as an untraced measured value
    assert after == before == 1.0


def test_attach_insights_then_verify_still_passes():
    rep = _report()
    attach_insights(rep)
    vr = verify_report(rep, rep["analyticsAST"], rep["evidenceAST"])
    # key findings block is excluded from measured values → provenance still clean
    assert vr.quality["provenanceCoverage"] == 1.0


def test_attach_insights_idempotent_block():
    rep = _report()
    attach_insights(rep)
    attach_insights(rep)
    kf_blocks = [b for b in rep["contentAST"]["blocks"] if b.get("blockId") == "key_findings"]
    assert len(kf_blocks) == 1     # not duplicated on re-run
