"""Phase 8 gate tests — the verifier FAIL becomes a hard publish gate.

These exercise the *enforcement* at the generate-phase API (the verifier's own
detection is covered in test_verifier.py). The verdict is controlled by patching
``G.verify_report`` so the gate behaviour is isolated from which specific check fails:

- PASS  → generation succeeds, publishable.
- WARN  → generation succeeds (never blocks), publishable, warning visible.
- FAIL strict (default) → HTTP 409, nothing persisted.
- FAIL draft (explicit / env) → allowed but marked non-publishable.
- auditAST.verification + auditAST.gate always present.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi import HTTPException

from report_builder.binding import review as R
from report_builder.binding.review import ReviewRecord
from report_builder.binding.schema import (
    BoundColumn, ColumnProfile, DatasetAST, EntityBinding,
)
from report_builder.generation.verifier import (
    FAIL, PASS, WARN, VerificationCheck, VerificationReport,
)
from api.report_builder_api import generate_phase_api as G
from api.report_builder_api.generate_phase_api import (
    GenerateIn, generate_report, get_report,
)

TEMPLATE_ID = "tpl_gate_v1"
SIGNATURE = "sig_gate_0001"


# ── controlled artifacts (salary by sector) ──────────────────────────────────

def _blueprint() -> dict:
    return {
        "metadata": {"title": "Salary Survey"},
        "entities": [
            {"entityId": "ent_sal", "canonicalName": "Average Salary"},
            {"entityId": "ent_sector", "canonicalName": "Sector"}],
        "topics": [{"topicId": "t_sal", "questions": [{
            "questionId": "q_sal_01", "intent": "Average salary by sector",
            "questionType": "comparison",
            "requiredEntities": [
                {"entityId": "ent_sal", "role": "measure", "required": True},
                {"entityId": "ent_sector", "role": "grouping", "required": True}],
            "analyticsSpec": {"operation": "group_aggregate",
                              "measure": {"entityRef": "ent_sal", "agg": "mean"},
                              "groupBy": [{"entityRef": "ent_sector"}],
                              "sort": {"by": "measure", "order": "desc"}},
            "answerStructure": {"components": [{"componentId": "q_sal_01_c1"}]}}]}],
    }


def _template_ast() -> dict:
    return {
        "metadata": {"templateId": TEMPLATE_ID},
        "semanticAST": {"sections": [{
            "sectionId": "sec_sal", "title": "Average Salary", "order": 1,
            "children": ["p_sal", "table_sal"]}]},
        "contentAST": {"blocks": [{
            "blockId": "p_sal", "kind": "paragraph", "content": "", "biQuery": "q_sal_01",
            "slot": {"fillFrom": "q_sal_01_c1", "status": "empty"}}]},
        "tableAST": {"tables": [{
            "tableId": "table_sal", "biQuery": "q_sal_01", "title": "Salary by Sector",
            "columns": [
                {"columnId": "col_sector", "header": "Sector", "role": "dimension"},
                {"columnId": "col_sal", "header": "Avg Salary", "role": "measure",
                 "format": "number.0"}],
            "rows": [], "slot": {"fillFrom": "q_sal_01", "status": "empty"}}]},
    }


def _dataset() -> DatasetAST:
    return DatasetAST(datasetId="ds_test", rowCount=4, archetype="survey", columns=[
        ColumnProfile(name="sal", dtype="number", role="measure"),
        ColumnProfile(name="sector", dtype="string", role="dimension")])


def _frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"sal": 50000, "sector": "Rural"}, {"sal": 52000, "sector": "Rural"},
        {"sal": 70000, "sector": "Urban"}, {"sal": 68000, "sector": "Urban"}])


def _entity_bindings() -> list[EntityBinding]:
    return [
        EntityBinding(entityId="ent_sal", entityName="Average Salary", entityType="measure",
                      columns=[BoundColumn(column="sal")], status="confirmed"),
        EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                      columns=[BoundColumn(column="sector")], status="confirmed"),
    ]


@pytest.fixture()
def stashed(tmp_path, monkeypatch):
    store = tmp_path / "bindings"
    store.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "_DEFAULT_STORE", store)
    monkeypatch.setattr(G, "_load_template_ast", _template_ast)
    from report_builder.binding import freeze_store
    monkeypatch.setattr(freeze_store, "FREEZE_DIR", store / "frozen")
    monkeypatch.delenv("GENERATION_PLAN_SOURCE", raising=False)
    monkeypatch.delenv("GENERATION_PUBLISH_MODE", raising=False)

    dataset, blueprint, df = _dataset(), _blueprint(), _frame()

    def _sp(suffix: str):
        return store / f"{TEMPLATE_ID}__{SIGNATURE}.{suffix}"

    _sp("dataset.json").write_text(json.dumps(dataset.to_dict()), encoding="utf-8")
    _sp("blueprint.json").write_text(json.dumps(blueprint), encoding="utf-8")
    df.to_csv(_sp("data.csv"), index=False)
    record = ReviewRecord(
        templateId=TEMPLATE_ID, datasetSignature=SIGNATURE, datasetId="ds_test",
        proposals=[b.to_dict() for b in _entity_bindings()])
    R.save_record(record, storage_dir=store)
    return store


def _force_verdict(monkeypatch, verdict: str, *, fails: list[str] | None = None):
    """Patch the verifier (as imported into the API module) to a fixed verdict."""
    checks = [VerificationCheck(code=c, severity="fail", message="forced")
              for c in (fails or [])]
    vr = VerificationReport(verdict=verdict, checks=checks,
                            quality={"finalScore": 100.0 if verdict == PASS else 40.0,
                                     "provenanceCoverage": 1.0})
    monkeypatch.setattr(G, "verify_report", lambda *a, **k: vr)


# ── 1: PASS happy path (real verifier) ────────────────────────────────────────

def test_pass_generation_succeeds_and_publishable(stashed):
    out = generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert out.verdict in (PASS, WARN)
    assert out.publishable is True
    assert out.publish_mode == "strict"
    report = get_report(TEMPLATE_ID, SIGNATURE)
    assert report["auditAST"]["verification"]["verdict"] in (PASS, WARN)
    assert report["auditAST"]["gate"]["publishable"] is True
    assert report["auditAST"]["publishable"] is True


# ── 2: WARN does not block ────────────────────────────────────────────────────

def test_warn_does_not_block(stashed, monkeypatch):
    _force_verdict(monkeypatch, WARN)
    out = generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert out.verdict == WARN
    assert out.publishable is True
    assert get_report(TEMPLATE_ID, SIGNATURE)["auditAST"]["publishable"] is True


# ── 3: FAIL in strict mode → 409, nothing persisted ───────────────────────────

def test_fail_strict_blocks_with_409(stashed, monkeypatch):
    _force_verdict(monkeypatch, FAIL, fails=["CONTENT_HASH"])
    with pytest.raises(HTTPException) as exc:
        generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert exc.value.status_code == 409
    assert "FAIL" in exc.value.detail and "CONTENT_HASH" in exc.value.detail


def test_fail_strict_does_not_persist(stashed, monkeypatch):
    _force_verdict(monkeypatch, FAIL, fails=["PROVENANCE"])
    with pytest.raises(HTTPException):
        generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    # nothing publishable was written — the report getter still 404s
    with pytest.raises(HTTPException) as exc:
        get_report(TEMPLATE_ID, SIGNATURE)
    assert exc.value.status_code == 404


# ── 4: FAIL in draft mode → allowed, marked non-publishable ───────────────────

def test_fail_draft_allowed_but_marked(stashed, monkeypatch):
    _force_verdict(monkeypatch, FAIL, fails=["NARRATIVE_NUMBERS"])
    out = generate_report(TEMPLATE_ID, SIGNATURE,
                          GenerateIn(period="2024", use_llm=False, publish_mode="draft"))
    assert out.verdict == FAIL
    assert out.publishable is False
    assert out.publish_mode == "draft"
    report = get_report(TEMPLATE_ID, SIGNATURE)       # persisted in draft mode
    assert report["auditAST"]["publishable"] is False
    assert report["auditAST"]["gate"]["blocked"] is False
    assert report["auditAST"]["gate"]["failedChecks"] == ["NARRATIVE_NUMBERS"]


def test_fail_draft_via_env(stashed, monkeypatch):
    monkeypatch.setenv("GENERATION_PUBLISH_MODE", "draft")
    _force_verdict(monkeypatch, FAIL, fails=["STRUCTURE"])
    out = generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert out.publish_mode == "draft" and out.publishable is False


# ── 5: request publish_mode overrides env ─────────────────────────────────────

def test_request_strict_overrides_env_draft(stashed, monkeypatch):
    monkeypatch.setenv("GENERATION_PUBLISH_MODE", "draft")
    _force_verdict(monkeypatch, FAIL, fails=["STRUCTURE"])
    with pytest.raises(HTTPException) as exc:
        generate_report(TEMPLATE_ID, SIGNATURE,
                        GenerateIn(period="2024", use_llm=False, publish_mode="strict"))
    assert exc.value.status_code == 409


# ── 6: auditAST.verification + gate always present on success ─────────────────

def test_audit_verification_and_gate_present(stashed):
    generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    audit = get_report(TEMPLATE_ID, SIGNATURE)["auditAST"]
    assert "verification" in audit and "quality" in audit["verification"]
    assert "gate" in audit and audit["gate"]["publishMode"] == "strict"
