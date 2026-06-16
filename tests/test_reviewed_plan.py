from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from report_builder.binding.profiler import profile_dataframe
from report_builder.binding.question_binder import bind_questions
from report_builder.binding.report import build_coverage
from report_builder.binding.resolver import resolve_entities
from report_builder.binding.review import ReviewRecord, accept_all_proposed
from report_builder.binding.reviewed_plan import (
    ReviewedPlan,
    add_component_to_plan_node,
    add_question_to_plan,
    build_reviewed_plan,
    find_plan_node,
    load_reviewed_plan,
    patch_plan_node,
    patch_plan_component,
    promote_reviewed_plan,
    save_reviewed_plan,
)
from report_builder.binding.schema import BindingAST


_REPO = Path(__file__).resolve().parent.parent
GOLD_BP = _REPO / "report_builder" / "gold_standard" / "template.blueprint.json"
PLFS_CSV = _REPO / "test_data" / "synthetic_plfs_dataset.csv"


def _bound_plfs():
    blueprint = json.loads(GOLD_BP.read_text(encoding="utf-8"))
    df = pd.read_csv(PLFS_CSV)
    dataset = profile_dataframe(df, dataset_id="plfs")
    bindings = resolve_entities(blueprint["entities"], dataset)
    binding = BindingAST(templateId="tpl_plfs_annual_v1", datasetId=dataset.datasetId, entityBindings=bindings)
    rec = ReviewRecord(templateId="tpl_plfs_annual_v1", datasetSignature="sig", proposals=[b.to_dict() for b in bindings])
    accept_all_proposed(binding, rec)
    binding.questionBindings = bind_questions(blueprint, binding.entityBindings, dataset, df=df)
    build_coverage(binding)
    return blueprint, dataset, binding


def _question_leaves(node):
    """All question-type nodes under a node, regardless of nesting depth."""
    found = [node] if getattr(node, "nodeType", None) == "question" else []
    for child in node.children:
        found.extend(_question_leaves(child))
    return found


def _all_question_leaves(plan):
    out = []
    for topic in plan.planTree:
        out.extend(_question_leaves(topic))
    return out


def _first_question(plan):
    leaves = _all_question_leaves(plan)
    assert leaves, "plan has no question nodes"
    return leaves[0]


def test_reviewed_plan_fast_path_builds_topic_tree():
    blueprint, dataset, binding = _bound_plfs()

    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature="sig",
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
        semantic_slot_graph={"slots": []},
    )

    assert plan.planId.startswith("rplan_tpl_plfs_annual_v1_sig_")
    assert plan.status in {"READY", "DEGRADED", "BLOCKED"}
    assert plan.planTree
    # Blueprint may nest questions under subtopics/chapters/sections; count leaves recursively.
    assert len(_all_question_leaves(plan)) == len(binding.questionBindings)
    first_question = _first_question(plan)
    assert first_question.nodeType == "question"
    assert first_question.components


def test_reviewed_plan_round_trip_and_store(tmp_path: Path):
    blueprint, dataset, binding = _bound_plfs()
    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature="sig",
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
    )

    data = plan.to_dict()
    assert data["$schema"] == "binding.reviewedPlan.v1"
    assert ReviewedPlan.from_dict(data).planId == plan.planId

    path = save_reviewed_plan(plan, storage_dir=tmp_path)
    assert path.exists()
    loaded = load_reviewed_plan("tpl_plfs_annual_v1", "sig", storage_dir=tmp_path)
    assert loaded is not None
    assert loaded.planId == plan.planId
    assert loaded.bindingAstId == plan.bindingAstId


def test_reviewed_plan_patch_node_and_disable_question():
    blueprint, dataset, binding = _bound_plfs()
    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature="sig",
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
    )
    topic = plan.planTree[0]
    question = _first_question(plan)

    patch_plan_node(plan, topic.nodeId, title="Renamed Topic")
    patch_plan_node(plan, question.nodeId, enabled=False)

    assert find_plan_node(plan, topic.nodeId).title == "Renamed Topic"
    disabled = find_plan_node(plan, question.nodeId)
    assert disabled.enabled is False
    assert disabled.readiness == "disabled"
    assert any(a["event"] == "reviewed_plan_node_patched" for a in plan.auditTrail)


def test_reviewed_plan_add_manual_question():
    blueprint, dataset, binding = _bound_plfs()
    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature="sig",
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
    )
    topic = plan.planTree[0]
    before = len(topic.children)

    node = add_question_to_plan(
        plan,
        parent_node_id=topic.nodeId,
        title="What is the manual officer question?",
    )

    assert len(topic.children) == before + 1
    assert node.source == "manual"
    assert node.components[0].componentType == "narrative"
    assert find_plan_node(plan, node.nodeId) is not None


def test_reviewed_plan_add_component_creates_virtual_slot():
    blueprint, dataset, binding = _bound_plfs()
    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature="sig",
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
    )
    question = plan.planTree[0].children[0]
    before_components = len(question.components)

    component = add_component_to_plan_node(
        plan,
        node_id=question.nodeId,
        component_type="chart",
        payload={"requiredEntities": question.requiredEntities, "analyticsSpec": {"operation": "group_aggregate"}},
    )

    assert len(question.components) == before_components + 1
    assert component.componentType == "chart"
    assert component.slotIds
    assert any(slot["componentId"] == component.componentId for slot in plan.virtualSlots)
    assert any(a["event"] == "reviewed_plan_component_added" for a in plan.auditTrail)


def test_reviewed_plan_patch_component_formula_spec():
    blueprint, dataset, binding = _bound_plfs()
    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature="sig",
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
    )
    question = _first_question(plan)
    component = question.components[0]

    patch_plan_component(
        plan,
        node_id=question.nodeId,
        component_id=component.componentId,
        formula_spec={"type": "SHARE", "numeratorColumn": "LFPR", "denominatorColumn": "Total"},
    )

    updated = find_plan_node(plan, question.nodeId).components[0]
    assert updated.formulaSpec["type"] == "SHARE"
    assert updated.formulaSpec["numeratorColumn"] == "LFPR"
    reloaded = find_plan_node(ReviewedPlan.from_dict(plan.to_dict()), question.nodeId)
    assert reloaded.components[0].formulaSpec["type"] == "SHARE"


def test_reviewed_plan_promotion_writes_sidecar(tmp_path: Path):
    blueprint, dataset, binding = _bound_plfs()
    plan = build_reviewed_plan(
        template_id="tpl_plfs_annual_v1",
        signature="sig",
        dataset=dataset,
        blueprint=blueprint,
        binding=binding,
    )
    plan.entityBindings.append({
        "entityId": "ent_manual_custom",
        "entityName": "Custom",
        "entityType": "measure",
        "method": "manual",
        "columns": [{"column": "Custom"}],
    })

    result = promote_reviewed_plan(plan, name="Officer reviewed PLFS", storage_dir=tmp_path)

    assert result["derivedTemplateId"].startswith("dtpl_officer_reviewed_plfs_")
    assert Path(result["path"]).exists()
    assert result["learnedEntityCount"] == 1