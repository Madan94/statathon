"""ReviewedPlan — officer-reviewed truth layer between binder and S4.

This module is intentionally additive. The current binder can already produce a
``BindingAST`` and an ``ExecutionBundle``; ``ReviewedPlan`` captures the richer,
auditable plan that officers will later edit through the topic/component UI.

Fast path today:
    blueprint + BindingAST + coverage + semantic slot graph
    -> ReviewedPlan with a Topic -> Question tree and component slots

Later phases can add CRUD, virtual slots, formulas, and promotion without
changing the S4 runtime contract.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from report_builder.binding.schema import BindingAST, DatasetAST, QuestionBinding


REVIEWED_PLAN_SCHEMA = "binding.reviewedPlan.v1"
_DEFAULT_STORE = Path(__file__).resolve().parents[2] / "storage" / "reviewed_plans"
_DERIVED_TEMPLATE_STORE = Path(__file__).resolve().parents[2] / "storage" / "derived_templates"
_LEARNED_ENTITY_STORE = Path(__file__).resolve().parents[2] / "storage" / "learned_entities"


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _question_id_set(binding: BindingAST) -> set[str]:
    return {q.questionId for q in binding.questionBindings if q.questionId}


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return slug or "node"


@dataclass
class TemplatePackageRef:
    templateId: str = ""
    version: str = "1.0.0"
    blueprintHash: str = ""
    astHash: str = ""
    semanticSlotGraphHash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "templateId": self.templateId,
            "version": self.version,
            "blueprintHash": self.blueprintHash,
            "astHash": self.astHash,
            "semanticSlotGraphHash": self.semanticSlotGraphHash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TemplatePackageRef":
        return cls(
            templateId=str(d.get("templateId") or ""),
            version=str(d.get("version") or "1.0.0"),
            blueprintHash=str(d.get("blueprintHash") or ""),
            astHash=str(d.get("astHash") or ""),
            semanticSlotGraphHash=str(d.get("semanticSlotGraphHash") or ""),
        )


@dataclass
class PlanComponent:
    componentId: str
    componentType: str = "narrative"
    questionId: str = ""
    source: str = "extracted"       # extracted | manual | virtual
    requiredEntities: list[dict[str, Any]] = field(default_factory=list)
    analyticsSpec: dict[str, Any] = field(default_factory=dict)
    formulaSpec: dict[str, Any] = field(default_factory=dict)
    answerStructure: dict[str, Any] = field(default_factory=dict)
    slotIds: list[str] = field(default_factory=list)
    readiness: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "componentId": self.componentId,
            "componentType": self.componentType,
            "questionId": self.questionId,
            "source": self.source,
            "requiredEntities": list(self.requiredEntities),
            "analyticsSpec": dict(self.analyticsSpec),
            "formulaSpec": dict(self.formulaSpec),
            "answerStructure": dict(self.answerStructure),
            "slotIds": list(self.slotIds),
            "readiness": self.readiness,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanComponent":
        return cls(
            componentId=str(d.get("componentId") or ""),
            componentType=str(d.get("componentType") or "narrative"),
            questionId=str(d.get("questionId") or ""),
            source=str(d.get("source") or "extracted"),
            requiredEntities=list(d.get("requiredEntities") or []),
            analyticsSpec=dict(d.get("analyticsSpec") or {}),
            formulaSpec=dict(d.get("formulaSpec") or {}),
            answerStructure=dict(d.get("answerStructure") or {}),
            slotIds=list(d.get("slotIds") or []),
            readiness=str(d.get("readiness") or "unknown"),
        )


@dataclass
class PlanNode:
    nodeId: str
    nodeType: str = "topic"          # topic | chapter | section | subtopic | subsubtopic | question
    title: str = ""
    parentId: str | None = None
    order: int = 0
    source: str = "extracted"
    enabled: bool = True
    questionId: str | None = None
    requiredEntities: list[dict[str, Any]] = field(default_factory=list)
    components: list[PlanComponent] = field(default_factory=list)
    readiness: str = "unknown"
    children: list["PlanNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "nodeId": self.nodeId,
            "nodeType": self.nodeType,
            "title": self.title,
            "order": self.order,
            "source": self.source,
            "enabled": self.enabled,
            "requiredEntities": list(self.requiredEntities),
            "components": [c.to_dict() for c in self.components],
            "readiness": self.readiness,
            "children": [c.to_dict() for c in self.children],
        }
        if self.parentId:
            out["parentId"] = self.parentId
        if self.questionId:
            out["questionId"] = self.questionId
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanNode":
        return cls(
            nodeId=str(d.get("nodeId") or ""),
            nodeType=str(d.get("nodeType") or "topic"),
            title=str(d.get("title") or ""),
            parentId=d.get("parentId"),
            order=int(d.get("order") or 0),
            source=str(d.get("source") or "extracted"),
            enabled=bool(d.get("enabled", True)),
            questionId=d.get("questionId"),
            requiredEntities=list(d.get("requiredEntities") or []),
            components=[PlanComponent.from_dict(c) for c in (d.get("components") or [])],
            readiness=str(d.get("readiness") or "unknown"),
            children=[PlanNode.from_dict(c) for c in (d.get("children") or [])],
        )


@dataclass
class ReviewedPlan:
    planId: str
    templatePackageRef: TemplatePackageRef
    datasetId: str = ""
    datasetSignature: str = ""
    bindingAstId: str = ""
    status: str = "DRAFT"            # DRAFT | READY | DEGRADED | BLOCKED
    planTree: list[PlanNode] = field(default_factory=list)
    entityBindings: list[dict[str, Any]] = field(default_factory=list)
    questionBindings: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    semanticSlotGraph: dict[str, Any] = field(default_factory=dict)
    virtualSlots: list[dict[str, Any]] = field(default_factory=list)
    auditTrail: list[dict[str, Any]] = field(default_factory=list)
    createdAt: float = field(default_factory=time.time)
    updatedAt: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": REVIEWED_PLAN_SCHEMA,
            "planId": self.planId,
            "templatePackageRef": self.templatePackageRef.to_dict(),
            "datasetId": self.datasetId,
            "datasetSignature": self.datasetSignature,
            "bindingAstId": self.bindingAstId,
            "status": self.status,
            "planTree": [n.to_dict() for n in self.planTree],
            "entityBindings": list(self.entityBindings),
            "questionBindings": list(self.questionBindings),
            "coverage": dict(self.coverage),
            "semanticSlotGraph": dict(self.semanticSlotGraph),
            "virtualSlots": list(self.virtualSlots),
            "auditTrail": list(self.auditTrail),
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewedPlan":
        return cls(
            planId=str(d.get("planId") or ""),
            templatePackageRef=TemplatePackageRef.from_dict(d.get("templatePackageRef") or {}),
            datasetId=str(d.get("datasetId") or ""),
            datasetSignature=str(d.get("datasetSignature") or ""),
            bindingAstId=str(d.get("bindingAstId") or ""),
            status=str(d.get("status") or "DRAFT"),
            planTree=[PlanNode.from_dict(n) for n in (d.get("planTree") or [])],
            entityBindings=list(d.get("entityBindings") or []),
            questionBindings=list(d.get("questionBindings") or []),
            coverage=dict(d.get("coverage") or {}),
            semanticSlotGraph=dict(d.get("semanticSlotGraph") or {}),
            virtualSlots=list(d.get("virtualSlots") or []),
            auditTrail=list(d.get("auditTrail") or []),
            createdAt=float(d.get("createdAt") or time.time()),
            updatedAt=float(d.get("updatedAt") or time.time()),
        )


def _component_slots(semantic_slot_graph: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for slot in semantic_slot_graph.get("slots") or []:
        component_id = str(slot.get("componentId") or "")
        slot_id = str(slot.get("slotId") or "")
        if component_id and slot_id:
            out.setdefault(component_id, []).append(slot_id)
    return out


def _question_status(binding: BindingAST) -> dict[str, str]:
    return {q.questionId: q.status for q in binding.questionBindings}


def _components_for_question(question: dict[str, Any], slot_index: dict[str, list[str]], status: str) -> list[PlanComponent]:
    answer = question.get("answerStructure") or question.get("outputContract") or {}
    components = answer.get("components") if isinstance(answer, dict) else []
    out: list[PlanComponent] = []
    for idx, comp in enumerate(components or []):
        component_id = str(comp.get("componentId") or f"{question.get('questionId', 'q')}_component_{idx + 1}")
        out.append(PlanComponent(
            componentId=component_id,
            componentType=str(comp.get("kind") or comp.get("componentKind") or "narrative"),
            questionId=str(question.get("questionId") or ""),
            source="extracted",
            requiredEntities=list(question.get("requiredEntities") or []),
            analyticsSpec=dict(question.get("analyticsSpec") or {}),
            formulaSpec=dict(question.get("formulaSpec") or comp.get("formulaSpec") or {}),
            answerStructure=dict(comp),
            slotIds=slot_index.get(component_id, []),
            readiness=status,
        ))
    if not out:
        question_id = str(question.get("questionId") or "")
        out.append(PlanComponent(
            componentId=f"{question_id}_component_1",
            componentType="narrative",
            questionId=question_id,
            requiredEntities=list(question.get("requiredEntities") or []),
            analyticsSpec=dict(question.get("analyticsSpec") or {}),
            formulaSpec=dict(question.get("formulaSpec") or {}),
            readiness=status,
        ))
    return out


def _question_node(
    question: dict[str, Any],
    *,
    parent_id: str,
    order: int,
    status_by_question: dict[str, str],
    slot_index: dict[str, list[str]],
) -> PlanNode:
    question_id = str(question.get("questionId") or "")
    status = status_by_question.get(question_id, "unknown")
    return PlanNode(
        nodeId=f"node_{question_id or parent_id + '_q_' + str(order)}",
        nodeType="question",
        title=str(question.get("intent") or question.get("question") or question.get("title") or question_id),
        parentId=parent_id,
        order=order,
        source="extracted",
        questionId=question_id,
        requiredEntities=list(question.get("requiredEntities") or []),
        components=_components_for_question(question, slot_index, status),
        readiness=status,
    )


def _section_children(section: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    children: list[tuple[str, dict[str, Any]]] = []
    for key in ("children", "chapters", "sections", "subtopics", "subsections"):
        for child in section.get(key) or []:
            if isinstance(child, dict):
                children.append((key, child))
    return children


def _section_node_type(
    section: dict[str, Any],
    *,
    depth: int,
    parent_node_type: str | None,
    child_key: str | None,
) -> str:
    if depth <= 0:
        return "topic"
    if child_key == "chapters" or section.get("chapterId"):
        return "chapter"
    if parent_node_type == "chapter" and (child_key in {"sections", "subsections"} or section.get("sectionId")):
        return "section"
    if depth == 1:
        return "subtopic"
    return "subsubtopic"


def _section_id(section: dict[str, Any], fallback: str) -> str:
    return str(
        section.get("topicId")
        or section.get("chapterId")
        or section.get("sectionId")
        or section.get("subtopicId")
        or section.get("id")
        or fallback
    )


def _build_section_node(
    section: dict[str, Any],
    *,
    parent_id: str | None,
    order: int,
    depth: int,
    status_by_question: dict[str, str],
    slot_index: dict[str, list[str]],
    valid_questions: set[str],
    parent_node_type: str | None = None,
    child_key: str | None = None,
) -> PlanNode:
    node_id = _section_id(section, f"section_{depth + 1}_{order}")
    node_type = _section_node_type(
        section,
        depth=depth,
        parent_node_type=parent_node_type,
        child_key=child_key,
    )
    node = PlanNode(
        nodeId=node_id,
        nodeType=node_type,
        title=str(section.get("title") or section.get("heading") or node_id),
        parentId=parent_id,
        order=int(section.get("order") or order),
        source="extracted",
        readiness="unknown",
    )

    child_order = 1
    for question in section.get("questions") or []:
        question_id = str(question.get("questionId") or "")
        if valid_questions and question_id not in valid_questions:
            continue
        node.children.append(_question_node(
            question,
            parent_id=node_id,
            order=child_order,
            status_by_question=status_by_question,
            slot_index=slot_index,
        ))
        child_order += 1

    for child_section_key, child_section in _section_children(section):
        node.children.append(_build_section_node(
            child_section,
            parent_id=node_id,
            order=child_order,
            depth=depth + 1,
            parent_node_type=node.nodeType,
            child_key=child_section_key,
            status_by_question=status_by_question,
            slot_index=slot_index,
            valid_questions=valid_questions,
        ))
        child_order += 1
    return node


def _build_plan_tree(blueprint: dict[str, Any], binding: BindingAST, semantic_slot_graph: dict[str, Any]) -> list[PlanNode]:
    status_by_question = _question_status(binding)
    slot_index = _component_slots(semantic_slot_graph)
    valid_questions = _question_id_set(binding)
    tree: list[PlanNode] = []

    for topic_order, topic in enumerate(blueprint.get("topics") or blueprint.get("sections") or [], start=1):
        tree.append(_build_section_node(
            topic,
            parent_id=None,
            order=topic_order,
            depth=0,
            status_by_question=status_by_question,
            slot_index=slot_index,
            valid_questions=valid_questions,
        ))

    if not tree and blueprint.get("questions"):
        general = PlanNode(nodeId="topic_general", nodeType="topic", title="General", order=1)
        for q_order, question in enumerate(blueprint.get("questions") or [], start=1):
            question_id = str(question.get("questionId") or "")
            if valid_questions and question_id not in valid_questions:
                continue
            general.children.append(_question_node(
                question,
                parent_id="topic_general",
                order=q_order,
                status_by_question=status_by_question,
                slot_index=slot_index,
            ))
        tree.append(general)
    return tree


def build_reviewed_plan(
    *,
    template_id: str,
    signature: str,
    dataset: DatasetAST,
    blueprint: dict[str, Any],
    binding: BindingAST,
    semantic_slot_graph: dict[str, Any] | None = None,
    template_ast: dict[str, Any] | None = None,
) -> ReviewedPlan:
    """Build the automatic ReviewedPlan fast path from current binder outputs."""
    graph = semantic_slot_graph or {}
    bp_meta = blueprint.get("templateMeta") or {}
    ast_meta = (template_ast or {}).get("metadata") or {}
    template_ref = TemplatePackageRef(
        templateId=template_id,
        version=str(bp_meta.get("version") or ast_meta.get("version") or "1.0.0"),
        blueprintHash=_stable_hash(blueprint),
        astHash=_stable_hash(template_ast or {}),
        semanticSlotGraphHash=_stable_hash(graph),
    )
    coverage = binding.coverage or {}
    has_errors = any(i.get("severity") == "error" for i in coverage.get("issues", []))
    has_degraded = any(q.status == "degraded" for q in binding.questionBindings)
    status = "BLOCKED" if has_errors else "DEGRADED" if has_degraded else "READY"
    binding_seed = {
        "templateId": template_id,
        "signature": signature,
        "entities": [e.to_dict() for e in binding.entityBindings],
        "questions": [q.to_dict() for q in binding.questionBindings],
    }
    binding_ast_id = f"bind_{template_id}_{_stable_hash(binding_seed)[:12]}"
    plan_id = f"rplan_{template_id}_{signature}_{_stable_hash(binding_seed)[:8]}"
    return ReviewedPlan(
        planId=plan_id,
        templatePackageRef=template_ref,
        datasetId=dataset.datasetId,
        datasetSignature=signature,
        bindingAstId=binding_ast_id,
        status=status,
        planTree=_build_plan_tree(blueprint, binding, graph),
        entityBindings=[e.to_dict() for e in binding.entityBindings],
        questionBindings=[q.to_dict() for q in binding.questionBindings],
        coverage=coverage,
        semanticSlotGraph=graph,
        auditTrail=[{
            "event": "reviewed_plan_fast_path_created",
            "source": "binding.finalize",
            "timestamp": time.time(),
        }],
    )


def _plan_dir(template_id: str, signature: str, storage_dir: str | Path | None = None) -> Path:
    safe_tpl = (template_id or "template").replace("/", "_").replace("\\", "_")
    base = Path(storage_dir) if storage_dir is not None else _DEFAULT_STORE
    return base / f"{safe_tpl}__{signature}"


def save_reviewed_plan(
    plan: ReviewedPlan,
    *,
    storage_dir: str | Path | None = None,
) -> Path:
    base = _plan_dir(plan.templatePackageRef.templateId, plan.datasetSignature, storage_dir)
    base.mkdir(parents=True, exist_ok=True)
    plan.updatedAt = time.time()
    path = base / f"{plan.planId}.json"
    path.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (base / "latest.json").write_text(json.dumps({
        "planId": plan.planId,
        "status": plan.status,
        "updatedAt": plan.updatedAt,
        "path": str(path),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_reviewed_plan(
    template_id: str,
    signature: str,
    *,
    plan_id: str | None = None,
    storage_dir: str | Path | None = None,
) -> ReviewedPlan | None:
    base = _plan_dir(template_id, signature, storage_dir)
    if plan_id is None:
        latest = base / "latest.json"
        if not latest.exists():
            return None
        plan_id = str((json.loads(latest.read_text(encoding="utf-8"))).get("planId") or "")
    path = base / f"{plan_id}.json"
    if not path.exists():
        return None
    return ReviewedPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))


def iter_plan_nodes(nodes: list[PlanNode]) -> list[PlanNode]:
    out: list[PlanNode] = []
    for node in nodes:
        out.append(node)
        out.extend(iter_plan_nodes(node.children))
    return out


def find_plan_node(plan: ReviewedPlan, node_id: str) -> PlanNode | None:
    for node in iter_plan_nodes(plan.planTree):
        if node.nodeId == node_id:
            return node
    return None


def patch_plan_node(
    plan: ReviewedPlan,
    node_id: str,
    *,
    title: str | None = None,
    enabled: bool | None = None,
    required_entities: list[dict[str, Any]] | None = None,
) -> ReviewedPlan:
    node = find_plan_node(plan, node_id)
    if node is None:
        raise KeyError(node_id)
    changes: dict[str, Any] = {}
    if title is not None and title.strip():
        node.title = title.strip()
        changes["title"] = node.title
    if enabled is not None:
        node.enabled = enabled
        if not enabled and node.nodeType == "question":
            node.readiness = "disabled"
        elif enabled and node.readiness == "disabled":
            node.readiness = "unknown"
        changes["enabled"] = enabled
    if required_entities is not None:
        node.requiredEntities = list(required_entities)
        for component in node.components:
            component.requiredEntities = list(required_entities)
        changes["requiredEntities"] = list(required_entities)
    plan.auditTrail.append({
        "event": "reviewed_plan_node_patched",
        "nodeId": node_id,
        "changes": changes,
        "timestamp": time.time(),
    })
    plan.updatedAt = time.time()
    return plan


def add_question_to_plan(
    plan: ReviewedPlan,
    *,
    parent_node_id: str,
    title: str,
    required_entities: list[dict[str, Any]] | None = None,
    analytics_spec: dict[str, Any] | None = None,
) -> PlanNode:
    parent = find_plan_node(plan, parent_node_id)
    if parent is None:
        raise KeyError(parent_node_id)
    if parent.nodeType == "question":
        raise ValueError("questions cannot contain child questions")
    existing_ids = {node.nodeId for node in iter_plan_nodes(plan.planTree)}
    base = f"node_q_manual_{_slug(title)}"
    node_id = base
    suffix = 2
    while node_id in existing_ids:
        node_id = f"{base}_{suffix}"
        suffix += 1
    question_id = node_id.replace("node_", "")
    component = PlanComponent(
        componentId=f"{question_id}_component_1",
        componentType="narrative",
        questionId=question_id,
        source="manual",
        requiredEntities=list(required_entities or []),
        analyticsSpec=dict(analytics_spec or {}),
        readiness="draft",
    )
    node = PlanNode(
        nodeId=node_id,
        nodeType="question",
        title=title.strip() or "Manual question",
        parentId=parent.nodeId,
        order=len(parent.children) + 1,
        source="manual",
        enabled=True,
        questionId=question_id,
        requiredEntities=list(required_entities or []),
        components=[component],
        readiness="draft",
    )
    parent.children.append(node)
    plan.auditTrail.append({
        "event": "reviewed_plan_question_added",
        "parentNodeId": parent.nodeId,
        "nodeId": node.nodeId,
        "timestamp": time.time(),
    })
    plan.updatedAt = time.time()
    return node


def add_component_to_plan_node(
    plan: ReviewedPlan,
    *,
    node_id: str,
    component_type: str,
    payload: dict[str, Any] | None = None,
) -> PlanComponent:
    from report_builder.binding.component_registry import (
        get_component_definition,
        normalize_component_type,
        validate_component_payload,
    )

    node = find_plan_node(plan, node_id)
    if node is None:
        raise KeyError(node_id)
    payload = dict(payload or {})
    normalized = normalize_component_type(component_type)
    definition = get_component_definition(normalized)
    if definition is None:
        raise ValueError(f"unknown component type: {component_type}")
    issues = validate_component_payload(normalized, payload, node_type=node.nodeType)
    if any(issue.get("severity") == "error" for issue in issues):
        raise ValueError("; ".join(issue.get("message", "component invalid") for issue in issues))

    existing_ids = {component.componentId for n in iter_plan_nodes(plan.planTree) for component in n.components}
    base = f"comp_{normalized}_{_slug(node.nodeId)}"
    component_id = base
    suffix = 2
    while component_id in existing_ids:
        component_id = f"{base}_{suffix}"
        suffix += 1

    slot_ids: list[str] = []
    if definition.defaultSlotBehavior == "virtual":
        slot_id = f"vslot_{component_id}"
        plan.virtualSlots.append({
            "slotId": slot_id,
            "componentId": component_id,
            "parentNodeId": node.nodeId,
            "placement": "append",
            "layoutIntent": normalized,
            "source": "manual",
        })
        slot_ids.append(slot_id)

    component = PlanComponent(
        componentId=component_id,
        componentType=normalized,
        questionId=node.questionId or "",
        source="manual",
        requiredEntities=list(payload.get("requiredEntities") or node.requiredEntities),
        analyticsSpec=dict(payload.get("analyticsSpec") or {}),
        formulaSpec=dict(payload.get("formulaSpec") or {}),
        answerStructure=dict(payload.get("answerStructure") or {"label": definition.label}),
        slotIds=slot_ids,
        readiness="draft" if issues else "ready",
    )
    node.components.append(component)
    plan.auditTrail.append({
        "event": "reviewed_plan_component_added",
        "nodeId": node.nodeId,
        "componentId": component.componentId,
        "componentType": component.componentType,
        "issues": issues,
        "timestamp": time.time(),
    })
    plan.updatedAt = time.time()
    return component


def patch_plan_component(
    plan: ReviewedPlan,
    *,
    node_id: str,
    component_id: str,
    required_entities: list[dict[str, Any]] | None = None,
    analytics_spec: dict[str, Any] | None = None,
    formula_spec: dict[str, Any] | None = None,
) -> ReviewedPlan:
    from report_builder.binding.component_registry import validate_component_payload

    node = find_plan_node(plan, node_id)
    if node is None:
        raise KeyError(node_id)
    component = next((c for c in node.components if c.componentId == component_id), None)
    if component is None:
        raise KeyError(component_id)
    changes: dict[str, Any] = {}
    if required_entities is not None:
        component.requiredEntities = list(required_entities)
        changes["requiredEntities"] = list(required_entities)
    if analytics_spec is not None:
        component.analyticsSpec = dict(analytics_spec)
        changes["analyticsSpec"] = dict(analytics_spec)
    if formula_spec is not None:
        component.formulaSpec = dict(formula_spec)
        changes["formulaSpec"] = dict(formula_spec)
    validation_payload = {
        "requiredEntities": list(component.requiredEntities),
        "analyticsSpec": dict(component.analyticsSpec),
        "formulaSpec": dict(component.formulaSpec),
    }
    validation_issues = validate_component_payload(component.componentType, validation_payload, node_type=node.nodeType)
    component.readiness = "draft" if validation_issues else "ready"
    changes["readiness"] = component.readiness
    if validation_issues:
        changes["validationIssues"] = validation_issues
    plan.auditTrail.append({
        "event": "reviewed_plan_component_patched",
        "nodeId": node_id,
        "componentId": component_id,
        "changes": changes,
        "timestamp": time.time(),
    })
    plan.updatedAt = time.time()
    return plan


def learned_entities_from_plan(plan: ReviewedPlan) -> list[dict[str, Any]]:
    learned: list[dict[str, Any]] = []
    for entity in plan.entityBindings:
        method = str(entity.get("method") or "")
        entity_id = str(entity.get("entityId") or "")
        notes = " ".join(str(n) for n in entity.get("notes") or [])
        if method == "manual" or entity_id.startswith("ent_manual_") or "officer-created" in notes:
            learned.append({
                "entityId": entity_id,
                "entityName": entity.get("entityName") or entity_id,
                "entityType": entity.get("entityType") or "dimension",
                "cardinality": entity.get("cardinality") or "oneToOne",
                "columns": entity.get("columns") or [],
                "source": "reviewed_plan",
                "planId": plan.planId,
            })
    return learned


def reviewed_plan_to_blueprint(plan: ReviewedPlan) -> dict[str, Any]:
    """Create a reusable blueprint draft from a ReviewedPlan.

    This is intentionally value-free: it carries entity definitions, topics,
    questions, required entities, answer components, and analytics/formula specs.
    """
    entities: list[dict[str, Any]] = []
    for entity in plan.entityBindings:
        entities.append({
            "entityId": entity.get("entityId"),
            "canonicalName": entity.get("entityName") or entity.get("entityId"),
            "entityType": entity.get("entityType") or "dimension",
            "cardinality": entity.get("cardinality") or "oneToOne",
            "aliases": entity.get("aliases") or [],
            "source": "reviewed_plan",
        })

    topics: list[dict[str, Any]] = []
    for topic in plan.planTree:
        questions: list[dict[str, Any]] = []
        for node in iter_plan_nodes(topic.children):
            if node.nodeType != "question" or node.enabled is False:
                continue
            components = []
            for component in node.components:
                comp_dict = {
                    "componentId": component.componentId,
                    "kind": component.componentType,
                    "source": component.source,
                    "slotIds": list(component.slotIds),
                }
                if component.formulaSpec:
                    comp_dict["formulaSpec"] = dict(component.formulaSpec)
                if component.answerStructure:
                    comp_dict.update(component.answerStructure)
                components.append(comp_dict)
            question = {
                "questionId": node.questionId or node.nodeId.replace("node_", ""),
                "intent": node.title,
                "questionType": "manual" if node.source == "manual" else "reviewed",
                "requiredEntities": list(node.requiredEntities),
                "analyticsSpec": dict(node.components[0].analyticsSpec) if node.components else {},
                "answerStructure": {"components": components},
                "source": node.source,
            }
            if node.components and node.components[0].formulaSpec:
                question["formulaSpec"] = dict(node.components[0].formulaSpec)
            questions.append(question)
        topics.append({
            "topicId": topic.nodeId,
            "title": topic.title,
            "order": topic.order,
            "questions": questions,
            "source": topic.source,
        })

    return {
        "$schema": "bharatstat/template-blueprint/v1",
        "templateMeta": {
            "templateId": plan.templatePackageRef.templateId,
            "name": f"Reviewed {plan.templatePackageRef.templateId}",
            "version": plan.templatePackageRef.version,
            "valueFree": True,
            "sourcePlanId": plan.planId,
        },
        "entities": entities,
        "topics": topics,
        "documentMap": {"source": "reviewed_plan", "planId": plan.planId},
        "learnedEntities": learned_entities_from_plan(plan),
    }


def reviewed_plan_to_template_ast(plan: ReviewedPlan) -> dict[str, Any]:
    blueprint = reviewed_plan_to_blueprint(plan)
    return {
        "$schema": "bharatstat/derived-template/v1",
        "templateMeta": {
            "templateId": plan.templatePackageRef.templateId,
            "sourcePlanId": plan.planId,
            "valueFree": True,
        },
        "blueprint": blueprint,
        "reviewedPlan": plan.to_dict(),
        "virtualSlots": list(plan.virtualSlots),
        "semanticSlotGraph": dict(plan.semanticSlotGraph),
    }


def list_learned_entities(template_id: str | None = None, *, storage_dir: str | Path | None = None) -> list[dict[str, Any]]:
    base = Path(storage_dir) if storage_dir is not None else _LEARNED_ENTITY_STORE
    if not base.exists():
        return []
    files: list[Path]
    if template_id:
        files = list((base / template_id).glob("*.learned_entities.json")) if (base / template_id).exists() else []
    else:
        files = list(base.glob("**/*.learned_entities.json"))
    out: list[dict[str, Any]] = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entity in payload.get("entities") or []:
            item = dict(entity)
            item.setdefault("templateId", payload.get("templateId"))
            item.setdefault("derivedTemplateId", payload.get("derivedTemplateId"))
            out.append(item)
    return out


def promote_reviewed_plan(
    plan: ReviewedPlan,
    *,
    name: str | None = None,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Promote a reviewed plan into a derived template sidecar package.

    This does not mutate the DB template table. It creates an auditable sidecar that
    can later be imported/promoted by the template service.
    """
    base = Path(storage_dir) if storage_dir is not None else _DERIVED_TEMPLATE_STORE
    derived_id = f"dtpl_{_slug(name or plan.planId)}_{_stable_hash(plan.to_dict())[:8]}"
    out_dir = base / derived_id
    out_dir.mkdir(parents=True, exist_ok=True)
    learned = learned_entities_from_plan(plan)
    payload = {
        "$schema": "binding.derivedTemplate.v1",
        "derivedTemplateId": derived_id,
        "name": name or f"Derived {plan.templatePackageRef.templateId}",
        "parentTemplateId": plan.templatePackageRef.templateId,
        "sourcePlanId": plan.planId,
        "status": "PROMOTED",
        "templatePackageRef": plan.templatePackageRef.to_dict(),
        "reviewedPlan": plan.to_dict(),
        "templateAst": reviewed_plan_to_template_ast(plan),
        "blueprint": reviewed_plan_to_blueprint(plan),
        "learnedEntities": learned,
        "createdAt": time.time(),
    }
    package_path = out_dir / "derived_template.json"
    package_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if learned:
        learned_base = (Path(storage_dir) / "learned_entities") if storage_dir is not None else _LEARNED_ENTITY_STORE
        learned_dir = learned_base / plan.templatePackageRef.templateId
        learned_dir.mkdir(parents=True, exist_ok=True)
        learned_path = learned_dir / f"{derived_id}.learned_entities.json"
        learned_path.write_text(json.dumps({
            "templateId": plan.templatePackageRef.templateId,
            "derivedTemplateId": derived_id,
            "planId": plan.planId,
            "entities": learned,
        }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    else:
        learned_path = None
    return {
        "derivedTemplateId": derived_id,
        "path": str(package_path),
        "learnedEntityCount": len(learned),
        "learnedEntitiesPath": str(learned_path) if learned_path else "",
    }
