"""Binding-phase regression tests (S0 profile → S1 resolve → S2 review →
S3 question-bind → B6 coverage), plus a golden e2e against the gold blueprint.

Fully offline and deterministic — no LLM, no network. The energy CSV doubles as a
second-archetype smoke test proving the binder is domain-agnostic.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from report_builder.binding.profiler import profile_csv, profile_dataframe
from report_builder.binding.resolver import resolve_entities
from report_builder.binding.value_resolver import resolve_filter_value
from report_builder.binding.question_binder import bind_questions
from report_builder.binding.review import (
    accept_all_proposed,
    dataset_signature,
    finalize_review,
    open_review,
    ReviewRecord,
)
from report_builder.binding.report import build_coverage, to_markdown
from report_builder.binding.schema import BindingAST, BoundColumn, ColumnProfile, DatasetAST, EntityBinding

_REPO = Path(__file__).resolve().parent.parent
GOLD_BP = _REPO / "report_builder" / "gold_standard" / "template.blueprint.json"
PLFS_CSV = _REPO / "test_data" / "synthetic_plfs_dataset.csv"
ENERGY_CSV = _REPO / "test_data" / "unified_energy_reserves_dataset.csv"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return json.loads(GOLD_BP.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plfs_df() -> pd.DataFrame:
    return pd.read_csv(PLFS_CSV)


@pytest.fixture(scope="module")
def energy_dataset() -> DatasetAST:
    return profile_csv(str(ENERGY_CSV))


# ── B1: profiler ────────────────────────────────────────────────────────────


def test_profiler_roles_energy(energy_dataset: DatasetAST):
    roles = {c.name: c.role for c in energy_dataset.columns}
    assert roles["Site_ID"] == "id"
    assert roles["State"] == "dimension"
    assert roles["Unit_of_Measure"] == "metadata"
    assert roles["Proved_Reserves"] == "measure"
    assert energy_dataset.archetype == "energy"


def test_profiler_unit_parsing(energy_dataset: DatasetAST):
    cap = energy_dataset.column("Potential_Capacity_MW")
    assert cap is not None and cap.unit == "MW"


def test_profiler_detects_real_measuregroup(energy_dataset: DatasetAST):
    groups = energy_dataset.columnGroups
    assert len(groups) == 1
    assert groups[0].stem == "Reserve"
    assert groups[0].kind == "measureGroup"
    assert "Proved_Reserves" in groups[0].members


def test_profiler_rejects_false_group_collision(plfs_df: pd.DataFrame):
    # LFPR + UR both end in '_rate' but are distinct measures — must NOT be grouped.
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    assert d.columnGroups == []
    assert d.archetype == "labour_force"


def test_profiler_min_max_nullpct(plfs_df: pd.DataFrame):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    wpr = d.column("Worker_Population_Ratio")
    assert wpr is not None
    assert wpr.minValue is not None and wpr.maxValue is not None
    assert 0.0 <= wpr.nullPct <= 1.0


# ── B2: resolver + cardinality ──────────────────────────────────────────────


def test_resolver_one_to_one(plfs_df: pd.DataFrame, blueprint: dict):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    bindings = {b.entityId: b for b in resolve_entities(blueprint["entities"], d)}
    assert bindings["ent_wpr"].cardinality == "oneToOne"
    assert bindings["ent_wpr"].column_names == ["Worker_Population_Ratio"]
    # distinct measures must not collapse into one another
    assert bindings["ent_lfpr"].column_names == ["Labour_Force_Participation_Rate"]
    assert bindings["ent_ur"].column_names == ["Unemployment_Rate"]


def test_resolver_member_set(energy_dataset: DatasetAST):
    ents = [{"entityId": "ent_restype", "canonicalName": "Reserve Type",
             "entityType": "dimension", "aliases": ["reserve class"],
             "valueDomain": {"members": ["Proved", "Indicated", "Inferred"]}}]
    b = resolve_entities(ents, energy_dataset)[0]
    assert b.cardinality == "memberSet"
    labels = {c.memberLabel for c in b.columns}
    assert {"Proved", "Indicated", "Inferred"} <= labels
    assert "Total" not in labels  # the total is excluded from a member set


def test_resolver_composite_prefers_explicit_total(energy_dataset: DatasetAST):
    ents = [{"entityId": "ent_reserves", "canonicalName": "Reserves",
             "entityType": "measure", "aliases": ["reserve quantity"]}]
    b = resolve_entities(ents, energy_dataset)[0]
    assert b.cardinality == "composite"
    assert b.combine == "pick"
    assert b.column_names == ["Total_Reserves"]


def test_resolver_time_missing_is_unresolved(energy_dataset: DatasetAST):
    ents = [{"entityId": "ent_year", "canonicalName": "Survey Period",
             "entityType": "time", "aliases": ["Year", "round"]}]
    b = resolve_entities(ents, energy_dataset)[0]
    assert b.status == "unresolved"
    assert b.typeMismatch is True


# ── B3: value resolver + question binder ────────────────────────────────────


def test_value_resolver_exact_and_code():
    assert resolve_filter_value("Rural", ["Rural", "Urban"]) == ("Rural", True)
    assert resolve_filter_value("Rural", ["R", "U"]) == ("R", True)       # code expansion
    assert resolve_filter_value("Male", ["M", "F"]) == ("M", True)
    val, applied = resolve_filter_value("15+", ["15-29", "30-59"])         # absent
    assert applied is False


def test_question_binder_executable(plfs_df: pd.DataFrame, blueprint: dict):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = resolve_entities(blueprint["entities"], d)
    qbs = {q.questionId: q for q in bind_questions(blueprint, ebs, d, df=plfs_df)}
    q = qbs["q_wpr_01"]
    assert q.status == "executable"
    assert q.resolvedRoles.measures == ["Worker_Population_Ratio"]
    assert q.resolvedRoles.dimensions == ["Sector"]
    assert q.resolvedRoles.time.column == "Year"
    assert q.resolvedRoles.time.timeResolved is True
    # the default-member filter on age group was applied
    flt = q.resolvedRoles.filters
    assert any(f.column == "Age_Group" and f.filterApplied for f in flt)


def test_question_binder_resolves_entities_by_name(plfs_df: pd.DataFrame, blueprint: dict):
    """Programmatic-fallback questions reference entities by NAME (``entityRef``)
    and use the ``groupBy`` role — unlike the Gemini path's ``entityId``/``grouping``.
    The binder must resolve either shape (id-or-name index + role catch-all)."""
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = resolve_entities(blueprint["entities"], d)
    name_bp = {
        "topics": [{"questions": [{
            "questionId": "q_byname",
            "intent": "Compare WPR across sector.",
            "questionType": "comparison",
            "requiredEntities": [
                {"entityRef": "Worker Population Ratio", "role": "measure"},
                {"entityRef": "Sector", "role": "groupBy"},
            ],
            "analyticsSpec": {"operation": "group_aggregate", "filters": []},
        }]}],
    }
    q = {qb.questionId: qb for qb in bind_questions(name_bp, ebs, d, df=plfs_df)}["q_byname"]
    assert q.status == "executable"
    assert q.resolvedRoles.measures == ["Worker_Population_Ratio"]
    assert q.resolvedRoles.dimensions == ["Sector"]      # 'groupBy' role → dimension


def test_question_binder_blocks_on_missing_required(blueprint: dict):
    # dataset without Sector → q_wpr_01 (requires ent_sector grouping) is blocked
    df = pd.DataFrame({"Year": ["2023-24"], "Worker_Population_Ratio": [52.1]})
    d = profile_dataframe(df, dataset_id="partial")
    ebs = resolve_entities(blueprint["entities"], d)
    qbs = {q.questionId: q for q in bind_questions(blueprint, ebs, d, df=df)}
    assert qbs["q_wpr_01"].status == "blocked"
    assert "ent_sector" in qbs["q_wpr_01"].unresolvedEntities


def test_question_binder_snapshot_when_no_time(blueprint: dict):
    # has Sector but no Year → time degrades to snapshot, not block
    df = pd.DataFrame({"Sector": ["Rural", "Urban"], "State": ["A", "B"],
                       "Worker_Population_Ratio": [52.1, 46.2]})
    d = profile_dataframe(df, dataset_id="notime")
    ebs = resolve_entities(blueprint["entities"], d)
    qbs = {q.questionId: q for q in bind_questions(blueprint, ebs, d, df=df)}
    q = qbs["q_wpr_01"]
    assert q.status == "degraded"
    assert q.resolvedRoles.time.timeResolved is False


# ── B4: review state machine ────────────────────────────────────────────────


def test_signature_stable_across_row_order(plfs_df: pd.DataFrame):
    a = dataset_signature(profile_dataframe(plfs_df, dataset_id="x"))
    b = dataset_signature(profile_dataframe(plfs_df.iloc[::-1], dataset_id="x"))
    assert a == b


def test_review_accept_proposed(plfs_df: pd.DataFrame, blueprint: dict, tmp_path: Path):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = resolve_entities(blueprint["entities"], d)
    b = BindingAST(templateId="t", datasetId="plfs", entityBindings=ebs)
    b, rec, deltas = open_review(b, d, storage_dir=tmp_path)
    assert len(deltas) == len(ebs)  # fresh dataset → everything pending
    b, _ = finalize_review(b, rec, accept_proposed=True, storage_dir=tmp_path)
    assert all(e.status in ("confirmed", "unresolved") for e in b.entityBindings)


def test_review_caches_confirmations(plfs_df: pd.DataFrame, blueprint: dict, tmp_path: Path):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = resolve_entities(blueprint["entities"], d)
    b = BindingAST(templateId="t", datasetId="plfs", entityBindings=ebs)
    b, rec, _ = open_review(b, d, storage_dir=tmp_path)
    from report_builder.binding.review import confirm
    confirm(rec, "ent_wpr")
    finalize_review(b, rec, storage_dir=tmp_path)
    # re-run with same signature → ent_wpr already decided, not a delta
    ebs2 = resolve_entities(blueprint["entities"], d)
    b2 = BindingAST(templateId="t", datasetId="plfs", entityBindings=ebs2)
    b2, _rec2, deltas2 = open_review(b2, d, storage_dir=tmp_path)
    assert b2.binding_for("ent_wpr").status == "confirmed"
    assert "ent_wpr" not in {e.entityId for e in deltas2}


def test_review_reopen_removes_confirmation(plfs_df: pd.DataFrame, blueprint: dict, tmp_path: Path):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = resolve_entities(blueprint["entities"], d)
    b = BindingAST(templateId="t", datasetId="plfs", entityBindings=ebs)
    b, rec, _ = open_review(b, d, storage_dir=tmp_path)
    from report_builder.binding.review import confirm, reopen

    confirm(rec, "ent_wpr")
    assert "ent_wpr" in rec.confirmations
    reopen(rec, "ent_wpr")
    finalize_review(b, rec, storage_dir=tmp_path)

    ebs2 = resolve_entities(blueprint["entities"], d)
    b2 = BindingAST(templateId="t", datasetId="plfs", entityBindings=ebs2)
    b2, _rec2, deltas2 = open_review(b2, d, storage_dir=tmp_path)
    assert b2.binding_for("ent_wpr").status == "proposed"
    assert "ent_wpr" in {e.entityId for e in deltas2}


def test_column_ownership_locks_confirmed_exclusive():
    from report_builder.binding.review import compute_column_ownership, confirm

    rec = ReviewRecord(
        templateId="t",
        datasetSignature="s",
        proposals=[
            {
                "entityId": "ent_lfpr",
                "entityName": "LFPR",
                "entityType": "measure",
                "cardinality": "oneToOne",
                "status": "proposed",
                "columns": [{"column": "LFPR"}],
            },
            {
                "entityId": "ent_wpr",
                "entityName": "WPR",
                "entityType": "measure",
                "cardinality": "oneToOne",
                "status": "proposed",
                "columns": [{"column": "WPR"}],
            },
        ],
    )
    confirm(rec, "ent_lfpr")

    ownership = compute_column_ownership(rec)
    lfpr = ownership["columns"]["LFPR"]
    assert lfpr["locked"] is True
    assert lfpr["owners"][0]["entityId"] == "ent_lfpr"
    assert lfpr["owners"][0]["sharePolicy"] == "exclusive"
    assert ownership["columns"]["WPR"]["locked"] is False


def test_column_conflict_detects_existing_exclusive_owner():
    from report_builder.binding.review import confirm, find_exclusive_column_conflicts

    rec = ReviewRecord(
        templateId="t",
        datasetSignature="s",
        proposals=[
            {"entityId": "ent_lfpr", "entityName": "LFPR", "entityType": "measure", "columns": [{"column": "LFPR"}]},
            {"entityId": "ent_wpr", "entityName": "WPR", "entityType": "measure", "columns": [{"column": "WPR"}]},
        ],
    )
    confirm(rec, "ent_lfpr")

    conflicts = find_exclusive_column_conflicts(rec, "ent_wpr", ["LFPR"])
    assert len(conflicts) == 1
    assert conflicts[0]["column"] == "LFPR"
    assert conflicts[0]["owners"][0]["entityId"] == "ent_lfpr"


def test_confirm_blocks_duplicate_exclusive_assignment():
    from report_builder.binding.review import ColumnOwnershipConflict, confirm

    rec = ReviewRecord(
        templateId="t",
        datasetSignature="s",
        proposals=[
            {"entityId": "ent_lfpr", "entityName": "LFPR", "entityType": "measure", "columns": [{"column": "LFPR"}]},
            {"entityId": "ent_wpr", "entityName": "WPR", "entityType": "measure", "columns": [{"column": "WPR"}]},
        ],
    )
    confirm(rec, "ent_lfpr")

    with pytest.raises(ColumnOwnershipConflict) as exc:
        confirm(rec, "ent_wpr", columns=["LFPR"])

    assert exc.value.conflicts[0]["column"] == "LFPR"
    assert exc.value.conflicts[0]["owners"][0]["entityId"] == "ent_lfpr"


def test_move_column_reopens_previous_owner():
    from report_builder.binding.review import (
        compute_column_ownership,
        confirm,
        move_columns_from_entities,
    )

    rec = ReviewRecord(
        templateId="t",
        datasetSignature="s",
        proposals=[
            {"entityId": "ent_lfpr", "entityName": "LFPR", "entityType": "measure", "columns": [{"column": "LFPR"}]},
            {"entityId": "ent_wpr", "entityName": "WPR", "entityType": "measure", "columns": [{"column": "WPR"}]},
        ],
    )
    confirm(rec, "ent_lfpr")
    move_columns_from_entities(rec, columns=["LFPR"], from_entity_ids=["ent_lfpr"])
    confirm(rec, "ent_wpr", columns=["LFPR"])

    assert "ent_lfpr" not in rec.confirmations
    ownership = compute_column_ownership(rec)
    owners = ownership["columns"]["LFPR"]["owners"]
    assert any(o["entityId"] == "ent_wpr" and o["status"] == "overridden" for o in owners)
    assert any(o["entityId"] == "ent_lfpr" and o["status"] == "proposed" for o in owners)


def test_shared_column_requires_explicit_policy():
    from report_builder.binding.review import compute_column_ownership, confirm

    rec = ReviewRecord(
        templateId="t",
        datasetSignature="s",
        proposals=[
            {"entityId": "ent_period", "entityName": "Period", "entityType": "time", "columns": [{"column": "Year"}]},
            {"entityId": "ent_year_filter", "entityName": "Year Filter", "entityType": "filter", "columns": [{"column": "Year"}]},
        ],
    )
    confirm(rec, "ent_period", share_policy="shared", share_reason="time context reused")
    confirm(rec, "ent_year_filter", share_policy="shared", share_reason="filter uses same time column")

    ownership = compute_column_ownership(rec)
    year = ownership["columns"]["Year"]
    assert year["locked"] is False
    assert ownership["conflicts"] == []
    assert {o["sharePolicy"] for o in year["owners"]} == {"shared"}


def test_add_manual_entity_from_column():
    from report_builder.binding.review import add_manual_entity, compute_column_ownership

    rec = ReviewRecord(templateId="t", datasetSignature="s", proposals=[])

    add_manual_entity(
        rec,
        entity_name="Custom Measure",
        entity_type="measure",
        columns=["Custom_Column"],
        note="officer added",
    )

    assert len(rec.proposals) == 1
    prop = rec.proposals[0]
    assert prop["entityId"].startswith("ent_manual_custom_measure")
    assert prop["method"] == "manual"
    assert prop["columns"] == [{"column": "Custom_Column"}]
    assert rec.confirmations[prop["entityId"]].columns == ["Custom_Column"]
    ownership = compute_column_ownership(rec)
    assert ownership["columns"]["Custom_Column"]["locked"] is True


def test_add_manual_entity_blocks_locked_column():
    from report_builder.binding.review import ColumnOwnershipConflict, add_manual_entity, confirm

    rec = ReviewRecord(
        templateId="t",
        datasetSignature="s",
        proposals=[
            {"entityId": "ent_lfpr", "entityName": "LFPR", "entityType": "measure", "columns": [{"column": "LFPR"}]},
        ],
    )
    confirm(rec, "ent_lfpr")

    with pytest.raises(ColumnOwnershipConflict):
        add_manual_entity(
            rec,
            entity_name="Duplicate LFPR",
            entity_type="measure",
            columns=["LFPR"],
        )
    assert len(rec.proposals) == 1


def test_workspace_dependency_graph_and_issues_are_ui_ready():
    from api.report_builder_api.binding_phase_api import _build_dependency_graph, _finalize_workspace_issues, _workspace_issues, _workspace_phase_statuses

    binding = BindingAST(
        templateId="t",
        datasetId="d",
        datasetSignature="s",
        entityBindings=[
            EntityBinding(
                entityId="ent_wpr",
                entityName="Worker Population Ratio",
                entityType="measure",
                columns=[BoundColumn("Worker_Population_Ratio")],
                status="confirmed",
                risks=[{"code": "LOW_CONFIDENCE", "severity": "warn"}],
            ),
            EntityBinding(entityId="ent_sector", entityName="Sector", entityType="dimension", status="unresolved"),
        ],
    )
    blueprint = {
        "topics": [{
            "questions": [{
                "questionId": "q_wpr_sector",
                "requiredEntities": [
                    {"entityId": "ent_wpr", "role": "measure"},
                    {"entityId": "ent_sector", "role": "grouping"},
                ],
            }],
        }],
    }
    reviewed_plan = SimpleNamespace(planTree=[
        SimpleNamespace(
            nodeId="node_q_wpr_sector",
            nodeType="question",
            questionId="q_wpr_sector",
            components=[SimpleNamespace(
                componentId="comp_chart",
                componentType="chart",
                requiredEntities=[{"entityId": "ent_wpr"}],
                analyticsSpec={},
                formulaSpec={},
                slotIds=["slot_chart_01"],
            )],
            children=[],
        )
    ], coverage={"issues": [{"severity": "error", "code": "QUESTION_BLOCKED", "questionId": "q_wpr_sector", "message": "Question blocked"}]})

    graph = _build_dependency_graph(blueprint, binding, reviewed_plan)
    assert graph["entityToQuestions"]["ent_wpr"] == ["q_wpr_sector"]
    assert graph["entityToComponents"]["ent_wpr"] == ["comp_chart"]
    assert graph["columnToEntities"]["Worker_Population_Ratio"] == ["ent_wpr"]
    assert graph["questionToColumns"]["q_wpr_sector"] == ["Worker_Population_Ratio"]
    assert graph["slotToQuestion"]["slot_chart_01"] == "q_wpr_sector"

    record = ReviewRecord(
        templateId="t",
        datasetSignature="s",
        proposals=[entity.to_dict() for entity in binding.entityBindings],
    )
    issues = _workspace_issues(record, binding, {"conflicts": [{"column": "Sector"}]}, reviewed_plan)
    assert all(issue.get("issueId", "").startswith("issue_") for issue in issues)
    assert len({issue["issueId"] for issue in issues}) == len(issues)
    assert all(issue.get("message") for issue in issues)
    assert any(issue.get("code") == "ENTITY_UNRESOLVED" for issue in issues)
    assert any(issue.get("code") == "LOW_CONFIDENCE" for issue in issues)
    assert any(issue.get("code") == "COLUMN_OWNERSHIP_CONFLICT" for issue in issues)
    assert any(issue.get("code") == "QUESTION_BLOCKED" and issue.get("targetMode") == "questions" for issue in issues)
    assert any(issue.get("code") == "ANALYTICS_SPEC_MISSING" and issue.get("componentId") == "comp_chart" for issue in issues)
    assert {issue.get("targetMode") for issue in issues} >= {"entities", "columns", "questions"}

    phases = _workspace_phase_statuses(
        record,
        DatasetAST(rowCount=10, columns=[ColumnProfile(name="Worker_Population_Ratio", role="measure")]),
        binding,
        {"conflicts": [{"column": "Sector"}]},
        reviewed_plan,
        issues,
    )
    assert phases["dataset"]["counts"]["columns"] == 1
    assert phases["columns"]["status"] == "Blocked"
    assert phases["questions"]["counts"]["issues"] >= 2
    assert phases["handoff"]["status"] == "Blocked"
    assert phases["handoff"]["counts"]["blockingIssues"] == 2

    duplicate = {"severity": "warn", "code": "X", "message": "Duplicate", "entityId": "ent_wpr"}
    deduped = _finalize_workspace_issues([duplicate, duplicate])
    assert len(deduped) == 1


def test_component_recommendations_use_question_context():
    from api.report_builder_api.binding_phase_api import _component_recommendations_for_node

    node = SimpleNamespace(
        nodeType="question",
        title="Compare Worker Population Ratio across rural and urban sectors",
        questionId="q_wpr_sector",
        requiredEntities=[
            {"entityId": "ent_wpr", "role": "measure"},
            {"entityId": "ent_sector", "role": "grouping"},
        ],
        components=[SimpleNamespace(componentType="narrative")],
    )

    recommendations = _component_recommendations_for_node(node)
    by_type = {item["component_type"]: item for item in recommendations}

    assert "chart" in by_type
    assert "table" in by_type
    assert "formula_metric" in by_type
    assert "narrative" not in by_type  # already present on the node
    assert by_type["chart"]["payload"]["requiredEntities"][0]["entityId"] == "ent_wpr"
    assert by_type["chart"]["payload"]["analyticsSpec"]["operation"] == "group_aggregate"


def test_reviewed_plan_payload_counts_nested_questions_and_components():
    from api.report_builder_api.binding_phase_api import _reviewed_plan_payload

    plan = SimpleNamespace(
        planId="plan_nested",
        status="READY",
        bindingAstId="binding_1",
        semanticSlotGraph={"slots": [{"slotId": "s1"}]},
        virtualSlots=[{"slotId": "v1"}],
        planTree=[SimpleNamespace(
            nodeType="topic",
            components=[],
            children=[SimpleNamespace(
                nodeType="subtopic",
                components=[],
                children=[SimpleNamespace(
                    nodeType="question",
                    components=[SimpleNamespace(), SimpleNamespace()],
                    children=[],
                    to_dict=lambda: {},
                )],
                to_dict=lambda: {},
            )],
            to_dict=lambda: {},
        )],
    )

    payload = _reviewed_plan_payload(plan)
    assert payload["topicCount"] == 2
    assert payload["questionCount"] == 1
    assert payload["componentCount"] == 2
    assert payload["semanticSlotCount"] == 1
    assert payload["virtualSlotCount"] == 1


def test_component_patch_recomputes_readiness():
    from report_builder.binding.reviewed_plan import PlanComponent, PlanNode, ReviewedPlan, TemplatePackageRef, patch_plan_component

    component = PlanComponent(
        componentId="comp_chart",
        componentType="chart",
        questionId="q1",
        requiredEntities=[],
        analyticsSpec={},
        readiness="draft",
    )
    plan = ReviewedPlan(
        planId="plan_component_ready",
        templatePackageRef=TemplatePackageRef(templateId="tpl"),
        planTree=[PlanNode(
            nodeId="node_q1",
            nodeType="question",
            title="Question",
            questionId="q1",
            components=[component],
        )],
    )

    patch_plan_component(
        plan,
        node_id="node_q1",
        component_id="comp_chart",
        required_entities=[{"entityId": "ent_wpr", "role": "measure"}],
        analytics_spec={"operation": "group_aggregate"},
    )

    assert plan.planTree[0].components[0].readiness == "ready"


# ── B6: coverage report ─────────────────────────────────────────────────────


def test_coverage_clean_on_full_plfs(plfs_df: pd.DataFrame, blueprint: dict):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = accept_all_proposed(
        BindingAST(entityBindings=resolve_entities(blueprint["entities"], d)),
        ReviewRecord(templateId="t", datasetSignature="s"),
    ).entityBindings
    qbs = bind_questions(blueprint, ebs, d, df=plfs_df)
    b = BindingAST(templateId="t", datasetId="plfs", entityBindings=ebs, questionBindings=qbs)
    rep = build_coverage(b)
    assert rep.has_errors is False
    assert rep.questions["blocked"] == 0


def test_coverage_errors_on_blocked(blueprint: dict):
    df = pd.DataFrame({"Year": ["2023-24"], "Worker_Population_Ratio": [52.1]})
    d = profile_dataframe(df, dataset_id="partial")
    ebs = resolve_entities(blueprint["entities"], d)
    qbs = bind_questions(blueprint, ebs, d, df=df)
    b = BindingAST(templateId="t", datasetId="partial", entityBindings=ebs, questionBindings=qbs)
    rep = build_coverage(b)
    assert rep.has_errors is True
    assert any(i.code == "QUESTION_BLOCKED" for i in rep.issues)
    # unresolved entities must NOT raise type-mismatch noise
    assert not any(i.code == "TYPE_MISMATCH" and i.severity == "warn"
                   and b.binding_for(i.entityId).status == "unresolved" for i in rep.issues)


def test_coverage_markdown_renders(plfs_df: pd.DataFrame, blueprint: dict):
    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = resolve_entities(blueprint["entities"], d)
    b = BindingAST(templateId="t", datasetId="plfs", entityBindings=ebs)
    md = to_markdown(b)
    assert "# Binding Coverage" in md
    assert "## Entities" in md


# ── Golden e2e + round-trips ────────────────────────────────────────────────


def test_golden_plfs_end_to_end(plfs_df: pd.DataFrame, blueprint: dict, tmp_path: Path):
    from scripts.run_binding import run_binding

    binding, dataset_ast = run_binding(
        blueprint, plfs_df, dataset_id="synthetic_plfs",
        source_file="synthetic_plfs_dataset.csv", accept_proposed=True,
        storage_dir=tmp_path,
    )
    # round-trips
    assert DatasetAST.from_dict(dataset_ast).rowCount == len(plfs_df)
    assert BindingAST.from_dict(binding.to_dict()).templateId == binding.templateId
    # gate-clean with correct key bindings
    cov = binding.coverage
    assert not any(i["severity"] == "error" for i in cov["issues"])
    assert cov["questions"]["executable"] >= 1
    assert binding.binding_for("ent_wpr").column_names == ["Worker_Population_Ratio"]
    assert binding.binding_for("ent_period").column_names == ["Year"]


def test_reviewed_plan_builds_from_binding_fast_path(plfs_df: pd.DataFrame, blueprint: dict):
    from report_builder.binding.reviewed_plan import build_reviewed_plan

    d = profile_dataframe(plfs_df, dataset_id="plfs")
    ebs = resolve_entities(blueprint["entities"], d)
    b = BindingAST(templateId="tpl_plfs_annual_v1", datasetId="plfs", entityBindings=ebs)
    b.questionBindings = bind_questions(blueprint, ebs, d, df=plfs_df)
    build_coverage(b)

    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature=dataset_signature(d),
        dataset=d,
        blueprint=blueprint,
        binding=b,
    )
    assert plan.datasetId == "plfs"
    assert plan.planTree
    assert plan.entityBindings
    assert plan.questionBindings
