"""G2 gate tests — generate-phase consumes the ExecutionBundle (gold source).

Proves the Phase 2b wiring:
- the DEFAULT plan source is the team's ExecutionBundle (not the re-derived planner)
- the legacy planner is reachable only behind an explicit flag (request or env)
- `NOT_READY` bundles and all-`BLOCKED` bundles never silently generate (409)
- multi-measure fan-out reaches S4 (`run_analytics`) with stable fanned plan IDs

Fully offline: a temp binding stash + finalized review record, controlled blueprint /
template / CSV, and (for the deterministic bundle cases) a monkeypatched `_build_bundle`.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi import HTTPException

from report_builder.binding import review as R
from report_builder.binding.review import ReviewRecord
from report_builder.binding.schema import (
    BoundColumn, ColumnProfile, DatasetAST, EntityBinding, ResolvedRoles,
)
from report_builder.binding.execution_contracts import (
    ExecutionBundle, FormulaSpec, QuestionExecutionPlan,
)
from api.report_builder_api import generate_phase_api as G
from api.report_builder_api.generate_phase_api import GenerateIn, generate_report, get_report

TEMPLATE_ID = "tpl_bundle_v1"
SIGNATURE = "sig_bundle_0001"


# ── controlled artifacts ──────────────────────────────────────────────────────

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
        ColumnProfile(name="bonus", dtype="number", role="measure"),
        ColumnProfile(name="sector", dtype="string", role="dimension")])


def _frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"sal": 50000, "bonus": 5000, "sector": "Rural"},
        {"sal": 52000, "bonus": 5200, "sector": "Rural"},
        {"sal": 70000, "bonus": 9000, "sector": "Urban"},
        {"sal": 68000, "bonus": 8600, "sector": "Urban"}])


def _entity_bindings() -> list[EntityBinding]:
    return [
        EntityBinding(entityId="ent_sal", entityName="Average Salary", entityType="measure",
                      columns=[BoundColumn(column="sal")], status="confirmed"),
        EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension",
                      columns=[BoundColumn(column="sector")], status="confirmed"),
    ]


@pytest.fixture()
def stashed(tmp_path, monkeypatch):
    """Temp binding store + finalized session so generate_report runs offline."""
    store = tmp_path / "bindings"
    store.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "_DEFAULT_STORE", store)
    monkeypatch.setattr(G, "_load_template_ast", _template_ast)
    # Sandbox the freeze store too (factory freezes internally) so no stale/real artifacts leak.
    from report_builder.binding import freeze_store
    monkeypatch.setattr(freeze_store, "FREEZE_DIR", store / "frozen")
    # Keep generation deterministic regardless of ambient env.
    monkeypatch.delenv("GENERATION_PLAN_SOURCE", raising=False)

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


def _exec_plan(measures: list[str], status: str = "EXECUTABLE") -> QuestionExecutionPlan:
    return QuestionExecutionPlan(
        planId="plan_q_sal_01", questionId="q_sal_01", status=status,
        analyticsSpec={
            "operation": "group_aggregate",
            "measure": {"column": measures[0] if measures else "", "agg": "mean", "unit": ""},
            "groupBy": [{"column": "sector"}],
            "filters": [], "sort": {"by": "measure", "order": "desc"}, "topN": None,
        },
        resolvedRoles=ResolvedRoles(measures=list(measures), dimensions=["sector"]),
        formulaSpec=FormulaSpec(type="DIRECT"),
    )


# ── 1-3: plan-source selection ────────────────────────────────────────────────

def test_default_plan_source_is_execution_bundle(stashed):
    out = generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert out.plan_source == "execution_bundle"
    assert out.valid is True, out.errors
    # the gold path actually answered the question (not an empty report)
    assert out.coverage["questionsAnswered"] == 1
    report = get_report(TEMPLATE_ID, SIGNATURE)
    assert report["tableAST"]["tables"][0]["rows"], "bundle path must fill the table"


def test_legacy_planner_only_when_explicitly_requested(stashed):
    out = generate_report(TEMPLATE_ID, SIGNATURE,
                          GenerateIn(period="2024", use_llm=False, plan_source="legacy"))
    assert out.plan_source == "legacy_planner"
    assert out.valid is True, out.errors


def test_env_flag_selects_legacy(stashed, monkeypatch):
    monkeypatch.setenv("GENERATION_PLAN_SOURCE", "legacy")
    out = generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert out.plan_source == "legacy_planner"


# ── 4-5: readiness discipline (never silently generate) ───────────────────────

def test_not_ready_bundle_blocks_generation(stashed, monkeypatch):
    monkeypatch.setattr(
        G, "_build_bundle",
        lambda *a, **k: ExecutionBundle(templateId=TEMPLATE_ID, datasetId="ds_test",
                                        status="NOT_READY", plans=[_exec_plan(["sal"])]))
    with pytest.raises(HTTPException) as exc:
        generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert exc.value.status_code == 409
    assert "NOT_READY" in exc.value.detail


def test_all_blocked_bundle_blocks_generation(stashed, monkeypatch):
    monkeypatch.setattr(
        G, "_build_bundle",
        lambda *a, **k: ExecutionBundle(templateId=TEMPLATE_ID, datasetId="ds_test",
                                        status="READY",
                                        plans=[_exec_plan(["sal"], status="BLOCKED")]))
    with pytest.raises(HTTPException) as exc:
        generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))
    assert exc.value.status_code == 409
    assert "BLOCKED" in exc.value.detail


# ── 6: multi-measure fan-out reaches S4 (coordinator) ─────────────────────────

def test_multi_measure_fanout_reaches_run_analytics(stashed, monkeypatch):
    """A 2-measure bundle plan must reach the coordinator as 2 fanned, stably-named plans."""
    monkeypatch.setattr(
        G, "_build_bundle",
        lambda *a, **k: ExecutionBundle(templateId=TEMPLATE_ID, datasetId="ds_test",
                                        status="READY", plans=[_exec_plan(["sal", "bonus"])]))

    captured: dict[str, list[str]] = {}

    class _Stop(Exception):
        pass

    def _spy(adapted, df, **kw):
        # The coordinator consumes the full AdaptedPlans (carrying formulaSpec /
        # normalizationPlan / lineage), not the lossy AnalyticsPlanRec list.
        captured["ids"] = [ap.planRec.planId for ap in adapted]
        captured["measures"] = [ap.planRec.measure.columnExpr for ap in adapted]
        raise _Stop  # isolate: prove S4 input only, no downstream coupling

    monkeypatch.setattr(G, "run_execution", _spy)

    with pytest.raises(_Stop):
        generate_report(TEMPLATE_ID, SIGNATURE, GenerateIn(period="2024", use_llm=False))

    assert captured["ids"] == ["plan_q_sal_01__sal", "plan_q_sal_01__bonus"]
    assert captured["measures"] == ["sal", "bonus"]
