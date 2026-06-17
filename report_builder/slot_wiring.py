"""E8 — Slot Wiring Validator + Layout Policy.

Validates and repairs cross-references between:
  ① template.ast.json (render skeleton)
  ② template.blueprint.json (analytic brain)

Every question/component must have a matching empty render slot.
This proves the analytic brain can actually fill the render skeleton.

Usage:
    from report_builder.slot_wiring import wire_template, validate_wiring
    result = wire_template(skeleton, blueprint, auto_repair=True)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WiringIssue:
    severity: str = "warn"          # error | warn | info
    code: str = ""
    message: str = ""
    path: str = ""
    questionId: str | None = None
    componentId: str | None = None
    slotId: str | None = None
    recommendedAction: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.path:
            d["path"] = self.path
        if self.questionId:
            d["questionId"] = self.questionId
        if self.componentId:
            d["componentId"] = self.componentId
        if self.slotId:
            d["slotId"] = self.slotId
        return d


@dataclass
class SlotPlacement:
    questionId: str = ""
    componentId: str = ""
    componentKind: str = ""
    targetAst: str = ""             # contentAST | tableAST | chartAST | figureAST | metricAST
    targetId: str = ""
    order: int = 0
    sectionRef: str | None = None
    source: str = "auto_created"    # existing | auto_created | inferred
    confidence: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return {"questionId": self.questionId, "componentId": self.componentId, "componentKind": self.componentKind, "targetAst": self.targetAst, "targetId": self.targetId, "source": self.source}


@dataclass
class SlotWiringResult:
    skeleton: dict[str, Any] = field(default_factory=dict)
    blueprint: dict[str, Any] = field(default_factory=dict)
    issues: list[WiringIssue] = field(default_factory=list)
    repairs: list[SlotPlacement] = field(default_factory=list)
    crosswalk: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issueCount": len(self.issues),
            "repairCount": len(self.repairs),
            "crosswalk": self.crosswalk,
            "counts": dict(self.counts),
            "errors": sum(1 for i in self.issues if i.severity == "error"),
            "warnings": sum(1 for i in self.issues if i.severity == "warn"),
        }

@dataclass
class SemanticSlot:
    """Persisted bridge from a render AST slot to a blueprint component/question."""

    slotId: str
    astBlockId: str
    astKind: str = "content"
    topicId: str | None = None
    chapterId: str | None = None
    sectionId: str | None = None
    questionId: str | None = None
    componentId: str | None = None
    componentKind: str = ""
    fillFrom: str | None = None
    source: str = "existing"          # existing | auto_created | inferred | figureTemplate_wire
    confidence: float = 0.8
    lineageRequired: bool = True
    slotPolicies: dict[str, Any] = field(default_factory=lambda: {"fillFromMustReference": "componentId"})

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "slotId": self.slotId,
            "astBlockId": self.astBlockId,
            "astKind": self.astKind,
            "source": self.source,
            "confidence": self.confidence,
        }
        if self.topicId:
            d["topicId"] = self.topicId
        if self.chapterId:
            d["chapterId"] = self.chapterId
        if self.sectionId:
            d["sectionId"] = self.sectionId
        if self.questionId:
            d["questionId"] = self.questionId
        if self.componentId:
            d["componentId"] = self.componentId
        if self.componentKind:
            d["componentKind"] = self.componentKind
        if self.fillFrom:
            d["fillFrom"] = self.fillFrom
        d["lineageRequired"] = self.lineageRequired
        d["slotPolicies"] = dict(self.slotPolicies)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SemanticSlot":
        return cls(
            slotId=str(d.get("slotId") or ""),
            astBlockId=str(d.get("astBlockId") or ""),
            astKind=str(d.get("astKind") or "content"),
            topicId=d.get("topicId"),
            chapterId=d.get("chapterId"),
            sectionId=d.get("sectionId"),
            questionId=d.get("questionId"),
            componentId=d.get("componentId"),
            componentKind=str(d.get("componentKind") or ""),
            fillFrom=d.get("fillFrom"),
            source=str(d.get("source") or "existing"),
            confidence=float(d.get("confidence") or 0.0),
            lineageRequired=bool(d.get("lineageRequired", True)),
            slotPolicies=dict(d.get("slotPolicies") or {"fillFromMustReference": "componentId"}),
        )


@dataclass
class SemanticSlotGraph:
    """Sidecar graph that makes AST-blueprint wiring durable for binder/review."""

    templateId: str = ""
    schema: str = "bharatstat/semantic-slot-graph/v1"
    slots: list[SemanticSlot] = field(default_factory=list)
    issues: list[WiringIssue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": self.schema,
            "templateId": self.templateId,
            "slots": [s.to_dict() for s in self.slots],
            "issues": [i.to_dict() for i in self.issues],
            "counts": dict(self.counts),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SemanticSlotGraph":
        return cls(
            templateId=str(d.get("templateId") or ""),
            schema=str(d.get("$schema") or d.get("schema") or "bharatstat/semantic-slot-graph/v1"),
            slots=[SemanticSlot.from_dict(s) for s in (d.get("slots") or [])],
            issues=[WiringIssue(**i) for i in (d.get("issues") or [])],
            counts={str(k): int(v) for k, v in (d.get("counts") or {}).items()},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────


def iter_questions(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten questions from every outline nesting level + top-level questions[].

    The blueprint may nest questions under chapters/sections/subtopics (enterprise
    packages) as well as directly under topics. Walk every nesting key so the slot
    graph, fillFrom validation and component counts see ALL questions and cannot
    silently drop nested ones.
    """
    questions: list[dict[str, Any]] = []

    def _walk(node: dict[str, Any]) -> None:
        for q in node.get("questions") or []:
            if isinstance(q, dict):
                questions.append(q)
        for key in ("chapters", "sections", "subtopics", "subsections", "children"):
            for child in node.get(key) or []:
                if isinstance(child, dict):
                    _walk(child)

    for topic in (blueprint.get("topics") or []):
        if isinstance(topic, dict):
            _walk(topic)
    questions.extend(blueprint.get("questions") or [])
    return questions


def iter_question_contexts(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Like ``iter_questions`` but each entry carries its outline lineage
    (topicId / chapterId / sectionId) so slots can record where they belong."""
    out: list[dict[str, Any]] = []

    def _walk(node: dict[str, Any], ctx: dict[str, Any]) -> None:
        node_ctx = dict(ctx)
        for key in ("topicId", "chapterId", "sectionId", "subtopicId"):
            if node.get(key):
                node_ctx[key] = node[key]
        for q in node.get("questions") or []:
            if isinstance(q, dict):
                entry = dict(node_ctx)
                entry["question"] = q
                entry["questionId"] = q.get("questionId") or q.get("id")
                out.append(entry)
        for key in ("chapters", "sections", "subtopics", "subsections", "children"):
            for child in node.get(key) or []:
                if isinstance(child, dict):
                    _walk(child, node_ctx)

    for topic in (blueprint.get("topics") or []):
        if isinstance(topic, dict):
            _walk(topic, {})
    return out


def iter_components(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Return answerStructure.components from a question."""
    ans = question.get("answerStructure") or question.get("outputContract") or {}
    return ans.get("components") or [] if isinstance(ans, dict) else []


def collect_skeleton_slots(skeleton: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collect all addressable slots from skeleton ASTs.

    Returns dict keyed by slot identifier (blockId/tableId/chartId/figureId)
    with metadata about each slot.
    """
    slots: dict[str, dict[str, Any]] = {}

    # Content blocks
    content = skeleton.get("contentAST") or {}
    for block in (content.get("blocks") or []) + (content.get("paragraphs") or []):
        bid = block.get("blockId") or block.get("id") or ""
        if bid:
            slots[bid] = {
                "type": "content", "id": bid,
                "biQuery": block.get("biQuery"),
                "fillFrom": (block.get("slot") or {}).get("fillFrom"),
            }

    # Tables
    table_ast = skeleton.get("tableAST") or {}
    for table in (table_ast.get("tables") or []):
        tid = table.get("tableId") or table.get("id") or ""
        if tid:
            slots[tid] = {
                "type": "table", "id": tid,
                "biQuery": table.get("biQuery"),
                "fillFrom": (table.get("slot") or {}).get("fillFrom"),
                "templateRef": table.get("templateRef"),
            }

    # Charts
    chart_ast = skeleton.get("chartAST") or {}
    for chart in (chart_ast.get("charts") or []):
        cid = chart.get("chartId") or chart.get("id") or ""
        if cid:
            slots[cid] = {
                "type": "chart", "id": cid,
                "biQuery": chart.get("biQuery"),
                "fillFrom": (chart.get("slot") or {}).get("fillFrom"),
                "measureEntityId": chart.get("measureEntityId"),
                "dimensionEntityId": chart.get("dimensionEntityId"),
                "entityRefs": list(chart.get("entityRefs") or []),
            }

    # Figures
    figure_ast = skeleton.get("figureAST") or {}
    for fig in (figure_ast.get("figures") or []):
        fid = fig.get("figureId") or fig.get("id") or ""
        if fid:
            slots[fid] = {
                "type": "figure", "id": fid,
                "biQuery": fig.get("biQuery"),
                "fillFrom": (fig.get("slot") or {}).get("fillFrom"),
            }

    # Metrics
    metric_ast = skeleton.get("metricAST") or {}
    for metric in (metric_ast.get("metrics") or []):
        mid = metric.get("metricId") or metric.get("id") or ""
        if mid:
            slots[mid] = {
                "type": "metric", "id": mid,
                "biQuery": metric.get("biQuery"),
                "fillFrom": (metric.get("slot") or {}).get("fillFrom"),
            }

    return slots


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────


def validate_wiring(skeleton: dict[str, Any], blueprint: dict[str, Any]) -> list[WiringIssue]:
    """Validate cross-references between skeleton and blueprint.

    Checks:
    1. Every question component has a matching slot
    2. Every biQuery points to existing question
    3. Every slot.fillFrom points to existing component
    4. Every table component has valid tableTemplateRef
    5. Every chart component has valid target
    6. Every tableTemplate has matching table slot (warn)
    7. Every figureTemplate has matching figure/chart slot (warn)
    8. No orphan slots (slots with biQuery pointing to missing question)
    9. No orphan questions (questions without any slot)
    10. Component IDs unique
    11. Question IDs unique
    """
    issues: list[WiringIssue] = []
    questions = iter_questions(blueprint)
    slots = collect_skeleton_slots(skeleton)

    # Build lookup sets
    question_ids = {q.get("questionId") or "" for q in questions if q.get("questionId")}
    component_ids: set[str] = set()
    all_component_ids: list[str] = []

    for q in questions:
        for comp in iter_components(q):
            cid = comp.get("componentId") or ""
            if cid:
                all_component_ids.append(cid)
                component_ids.add(cid)

    # Table template IDs
    table_template_ids = set()
    for tt in (blueprint.get("tableTemplates") or blueprint.get("tableStructures") or []):
        tid = tt.get("tableId") or tt.get("tableTemplateId") or ""
        if tid:
            table_template_ids.add(tid)

    # Figure template IDs
    figure_template_ids = set()
    for ft in (blueprint.get("figureTemplates") or []):
        fid = ft.get("figureTemplateId") or ft.get("figureId") or ""
        if fid:
            figure_template_ids.add(fid)

    # ── Check 1: Components have matching slots ──
    slot_fill_froms = {s["fillFrom"] for s in slots.values() if s.get("fillFrom")}
    slot_bi_queries = {s["biQuery"] for s in slots.values() if s.get("biQuery")}

    for q in questions:
        qid = q.get("questionId") or ""
        has_any_slot = qid in slot_bi_queries
        for comp in iter_components(q):
            cid = comp.get("componentId") or ""
            if cid and cid not in slot_fill_froms and qid not in slot_bi_queries:
                issues.append(WiringIssue(
                    severity="warn", code="MISSING_SLOT_FOR_COMPONENT",
                    message=f"Component '{cid}' has no matching slot in skeleton",
                    questionId=qid, componentId=cid,
                    recommendedAction="Auto-wire will create empty slot",
                ))

    # ── Check 2: biQuery refs resolve ──
    for slot_id, slot_info in slots.items():
        bq = slot_info.get("biQuery")
        if bq and bq not in question_ids:
            issues.append(WiringIssue(
                severity="error", code="ORPHAN_BIQUERY",
                message=f"Slot '{slot_id}' has biQuery='{bq}' which doesn't exist",
                slotId=slot_id,
            ))

    # ── Check 3: fillFrom refs resolve ──
    for slot_id, slot_info in slots.items():
        ff = slot_info.get("fillFrom")
        if ff and ff not in component_ids:
            issues.append(WiringIssue(
                severity="error", code="BROKEN_FILLFROM",
                message=f"Slot '{slot_id}' has fillFrom='{ff}' which doesn't exist",
                slotId=slot_id,
            ))

    # ── Check 4: Table template refs ──
    for q in questions:
        for comp in iter_components(q):
            oc = comp.get("outputContract") or {}
            tt_ref = oc.get("tableTemplateRef")
            if tt_ref and tt_ref not in table_template_ids:
                issues.append(WiringIssue(
                    severity="warn", code="TABLE_TEMPLATE_MISSING",
                    message=f"tableTemplateRef '{tt_ref}' not in blueprint.tableTemplates",
                    questionId=q.get("questionId"), componentId=comp.get("componentId"),
                ))

    # ── Check 10: Unique component IDs ──
    seen_cids: set[str] = set()
    for cid in all_component_ids:
        if cid in seen_cids:
            issues.append(WiringIssue(severity="warn", code="DUPLICATE_COMPONENT_ID", message=f"Duplicate componentId: {cid}", componentId=cid))
        seen_cids.add(cid)

    # ── Check 11: Unique question IDs ──
    seen_qids: set[str] = set()
    for q in questions:
        qid = q.get("questionId") or ""
        if qid in seen_qids:
            issues.append(WiringIssue(severity="warn", code="DUPLICATE_QUESTION_ID", message=f"Duplicate questionId: {qid}", questionId=qid))
        seen_qids.add(qid)

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# Auto-wiring (repair)
# ─────────────────────────────────────────────────────────────────────────────


def auto_wire_missing_slots(
    skeleton: dict[str, Any],
    blueprint: dict[str, Any],
) -> tuple[dict[str, Any], list[SlotPlacement]]:
    """Create missing empty slots for all question components.

    Returns (updated_skeleton, list_of_placements_created).
    """
    questions = iter_questions(blueprint)
    slots = collect_skeleton_slots(skeleton)
    slot_fill_froms = {s["fillFrom"] for s in slots.values() if s.get("fillFrom")}
    slot_bi_queries = {s["biQuery"] for s in slots.values() if s.get("biQuery")}

    repairs: list[SlotPlacement] = []

    # Ensure AST sections exist
    skeleton.setdefault("contentAST", {}).setdefault("blocks", [])
    skeleton.setdefault("tableAST", {}).setdefault("tables", [])
    skeleton.setdefault("chartAST", {}).setdefault("charts", [])
    skeleton.setdefault("figureAST", {}).setdefault("figures", [])

    for q in questions:
        qid = q.get("questionId") or ""
        for comp in iter_components(q):
            cid = comp.get("componentId") or ""
            kind = comp.get("kind") or "narrative"
            oc = comp.get("outputContract") or {}

            # Check if already wired. Keyed on the component id only: a question may
            # already have one component slot (e.g. a repaired chart) while a sibling
            # component (its narrative) still needs a slot, so we must not skip the
            # whole question just because its biQuery is referenced somewhere.
            if cid in slot_fill_froms:
                continue

            reused = _try_reuse_existing_slot(skeleton, slots, q, comp, kind)
            if reused:
                repairs.append(reused)
                slot_fill_froms.add(cid)
                slot_bi_queries.add(qid)
                continue

            # Create appropriate slot
            placement = SlotPlacement(
                questionId=qid, componentId=cid, componentKind=kind,
                source="auto_created", confidence=0.8,
            )

            if kind == "narrative":
                block_id = f"p_{cid}"
                skeleton["contentAST"]["blocks"].append({
                    "blockId": block_id,
                    "kind": "paragraph",
                    "content": "",
                    "biQuery": qid,
                    "slot": {"fillFrom": cid, "status": "empty"},
                })
                placement.targetAst = "contentAST"
                placement.targetId = block_id

            elif kind == "table":
                table_id = f"table_{cid}"
                table_entry: dict[str, Any] = {
                    "tableId": table_id,
                    "biQuery": qid,
                    "rows": [],
                    "slot": {"fillFrom": cid, "status": "empty"},
                }
                tt_ref = oc.get("tableTemplateRef")
                if tt_ref:
                    table_entry["templateRef"] = tt_ref
                skeleton["tableAST"]["tables"].append(table_entry)
                placement.targetAst = "tableAST"
                placement.targetId = table_id

            elif kind == "chart":
                chart_id = f"chart_{cid}"
                chart_type = oc.get("chartType") or "bar"
                skeleton["chartAST"]["charts"].append({
                    "chartId": chart_id,
                    "biQuery": qid,
                    "chartType": chart_type,
                    "series": [],
                    "slot": {"fillFrom": cid, "status": "empty"},
                })
                placement.targetAst = "chartAST"
                placement.targetId = chart_id

            elif kind == "metric_card":
                block_id = f"metric_{cid}"
                skeleton["contentAST"]["blocks"].append({
                    "blockId": block_id,
                    "kind": "metric",
                    "content": "",
                    "biQuery": qid,
                    "slot": {"fillFrom": cid, "status": "empty"},
                })
                placement.targetAst = "contentAST"
                placement.targetId = block_id

            elif kind in ("infographic", "figure", "visual_summary"):
                # PIB visual panels → create both chart + figure skeleton entries
                chart_id = f"chart_{cid}"
                fig_id = f"fig_{cid}"
                chart_type = oc.get("chartType") or "infographic_panel"
                ft_ref = oc.get("figureTemplateRef") or ""
                skeleton["chartAST"]["charts"].append({
                    "chartId": chart_id,
                    "biQuery": qid,
                    "chartType": chart_type,
                    "series": [],
                    "slot": {"fillFrom": cid, "status": "empty"},
                })
                skeleton["figureAST"].setdefault("figures", [])
                skeleton["figureAST"]["figures"].append({
                    "figureId": fig_id,
                    "templateRef": ft_ref,
                    "chartRef": chart_id,
                    "caption": "",
                    "captionTemplate": "",
                    "slot": {"fillFrom": cid, "status": "empty"},
                })
                placement.targetAst = "chartAST"
                placement.targetId = chart_id

            repairs.append(placement)

    # ── Wire figureTemplates without matching AST slots ──
    # PIB Phase 3 creates many figureTemplates via SectionGraph. Only materialize
    # those referenced by a question/component; otherwise chart-heavy PDFs create
    # dozens of empty render slots unrelated to the reviewed plan. If the blueprint
    # has no questions yet, keep the legacy fallback and materialize all.
    existing_chart_ids = {c.get("chartId") for c in (skeleton.get("chartAST") or {}).get("charts") or []}
    existing_figure_ids = {f.get("figureId") for f in (skeleton.get("figureAST") or {}).get("figures") or []}
    referenced_figures: set[str] = set()
    for q in questions:
        source_figure = q.get("sourceFigure") or q.get("figureTemplateRef")
        if source_figure:
            referenced_figures.add(str(source_figure))
        for comp in iter_components(q):
            oc = comp.get("outputContract") or {}
            refs = comp.get("refs") or {}
            for ref in (
                oc.get("figureTemplateRef"), oc.get("figureRef"), oc.get("chartRef"),
                refs.get("figureTemplateRef"), refs.get("figureRef"), refs.get("chartRef"),
            ):
                if ref:
                    referenced_figures.add(str(ref))

    for ft in (blueprint.get("figureTemplates") or []):
        ft_id = ft.get("figureTemplateId") or ft.get("chartId") or ""
        chart_id = ft.get("chartId") or f"chart_{ft_id}"
        fig_id = ft_id.replace("ft_", "fig_") if ft_id.startswith("ft_") else f"fig_{ft_id}"

        if questions and ft_id not in referenced_figures and chart_id not in referenced_figures and fig_id not in referenced_figures:
            continue

        if chart_id not in existing_chart_ids:
            skeleton["chartAST"]["charts"].append({
                "chartId": chart_id,
                "biQuery": "",
                "chartType": ft.get("chartType") or "infographic_panel",
                "series": [],
                "slot": {"status": "empty"},
            })
            existing_chart_ids.add(chart_id)
            repairs.append(SlotPlacement(
                componentKind="chart", targetAst="chartAST", targetId=chart_id,
                source="figureTemplate_wire",
            ))

        if fig_id not in existing_figure_ids:
            skeleton["figureAST"]["figures"].append({
                "figureId": fig_id,
                "templateRef": ft_id,
                "chartRef": chart_id,
                "caption": "",
                "captionTemplate": ft.get("captionTemplate") or "",
                "slot": {"status": "empty"},
            })
            existing_figure_ids.add(fig_id)
            repairs.append(SlotPlacement(
                componentKind="figure", targetAst="figureAST", targetId=fig_id,
                source="figureTemplate_wire",
            ))

    return skeleton, repairs


def _question_measure_dimension(q: dict[str, Any], comp: dict[str, Any]) -> tuple[str, str]:
    oc = comp.get("outputContract") or {}
    measure = oc.get("yAxis") or q.get("measureEntityId") or ""
    dimension = oc.get("xAxis") or q.get("dimensionEntityId") or ""
    for req in q.get("requiredEntities") or []:
        role = req.get("role")
        eid = req.get("entityId") or req.get("entityRef") or ""
        if role == "measure" and not measure:
            measure = eid
        if role in ("grouping", "dimension") and not dimension:
            dimension = eid
    return str(measure or ""), str(dimension or "")


def _try_reuse_existing_slot(
    skeleton: dict[str, Any],
    slots: dict[str, dict[str, Any]],
    q: dict[str, Any],
    comp: dict[str, Any],
    kind: str,
) -> SlotPlacement | None:
    """Attach a component to an existing value-free slot when semantics match."""
    cid = comp.get("componentId") or ""
    qid = q.get("questionId") or ""
    if not cid or not qid:
        return None
    if kind != "chart":
        return None

    measure, dimension = _question_measure_dimension(q, comp)
    if not measure and not dimension:
        return None

    chart_ast = skeleton.get("chartAST") or {}
    charts = chart_ast.get("charts") or []
    for chart in charts:
        chart_id = chart.get("chartId") or chart.get("id") or ""
        if not chart_id:
            continue
        if (chart.get("slot") or {}).get("fillFrom") or chart.get("biQuery"):
            continue
        entity_refs = set(chart.get("entityRefs") or [])
        chart_measure = chart.get("measureEntityId")
        chart_dimension = chart.get("dimensionEntityId")
        measure_match = bool(measure and (measure == chart_measure or measure in entity_refs))
        # If the raw chart has no dimension metadata yet, a measure match is still
        # strong enough to reuse it. This avoids creating duplicate generated chart
        # slots for curated questions whose chart panels already exist in the PDF.
        has_panel_filters = bool(chart.get("filters"))
        dimension_match = bool(
            not dimension
            or not chart_dimension
            or dimension == chart_dimension
            or dimension in entity_refs
            or (measure_match and has_panel_filters)
        )
        if measure_match and dimension_match:
            chart["biQuery"] = qid
            chart.setdefault("slot", {})["fillFrom"] = cid
            chart.setdefault("slot", {})["status"] = "empty"
            return SlotPlacement(
                questionId=qid,
                componentId=cid,
                componentKind=kind,
                targetAst="chartAST",
                targetId=chart_id,
                source="existing_semantic_match",
                confidence=0.85,
            )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Crosswalk builder
# ─────────────────────────────────────────────────────────────────────────────


def build_crosswalk(skeleton: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    """Build question/component/slot crosswalk mapping."""
    questions = iter_questions(blueprint)
    slots = collect_skeleton_slots(skeleton)

    # Invert: fillFrom → slotId
    fillfrom_to_slot: dict[str, str] = {}
    biquery_to_slots: dict[str, list[str]] = {}
    for slot_id, info in slots.items():
        ff = info.get("fillFrom")
        if ff:
            fillfrom_to_slot[ff] = slot_id
        bq = info.get("biQuery")
        if bq:
            biquery_to_slots.setdefault(bq, []).append(slot_id)

    question_to_slots: dict[str, list[str]] = {}
    component_to_slot: dict[str, str] = {}
    slot_to_component: dict[str, str] = {}

    for q in questions:
        qid = q.get("questionId") or ""
        q_slots: list[str] = list(biquery_to_slots.get(qid, []))

        for comp in iter_components(q):
            cid = comp.get("componentId") or ""
            if cid in fillfrom_to_slot:
                slot_id = fillfrom_to_slot[cid]
                component_to_slot[cid] = slot_id
                slot_to_component[slot_id] = cid
                if slot_id not in q_slots:
                    q_slots.append(slot_id)

        if q_slots:
            question_to_slots[qid] = q_slots

    return {
        "questionToSlots": question_to_slots,
        "componentToSlot": component_to_slot,
        "slotToComponent": slot_to_component,
        "figureToQuestion": {
            info["id"]: info["biQuery"]
            for info in slots.values()
            if info.get("type") == "figure" and info.get("biQuery")
        },
        "chartToQuestion": {
            info["id"]: info["biQuery"]
            for info in slots.values()
            if info.get("type") == "chart" and info.get("biQuery")
        },
    }


def build_semantic_slot_graph(
    skeleton: dict[str, Any],
    blueprint: dict[str, Any],
    wiring_result: SlotWiringResult | None = None,
    *,
    template_id: str | None = None,
) -> SemanticSlotGraph:
    """Build a durable slot graph from the current skeleton/blueprint wiring.

    ``SlotWiringResult`` is intentionally compact and diagnostic-oriented. The
    binder needs a persisted graph it can extend with virtual slots during review.
    This projection keeps one row per addressable AST slot that is connected to a
    blueprint question or component.
    """
    questions = iter_questions(blueprint)
    slots = collect_skeleton_slots(skeleton)
    crosswalk = wiring_result.crosswalk if wiring_result is not None else build_crosswalk(skeleton, blueprint)
    repair_by_target = {
        r.targetId: r for r in (wiring_result.repairs if wiring_result is not None else [])
        if r.targetId
    }

    topic_by_question: dict[str, str] = {}
    component_meta: dict[str, dict[str, str]] = {}
    # Walk EVERY outline level (topic → chapter → section → question) so nested
    # enterprise blueprints carry full lineage onto their slots.
    for ctx in iter_question_contexts(blueprint):
        question = ctx.get("question") or {}
        question_id = str(ctx.get("questionId") or "")
        topic_id = str(ctx.get("topicId") or "")
        chapter_id = str(ctx.get("chapterId") or "")
        section_id = str(ctx.get("sectionId") or "")
        if question_id:
            topic_by_question[question_id] = topic_id
        for comp in iter_components(question):
            component_id = str(comp.get("componentId") or "")
            if component_id:
                component_meta[component_id] = {
                    "questionId": question_id,
                    "topicId": topic_id,
                    "chapterId": chapter_id,
                    "sectionId": section_id,
                    "componentKind": str(comp.get("kind") or comp.get("componentKind") or ""),
                }

    slot_to_component = crosswalk.get("slotToComponent") or {}
    question_to_slots = crosswalk.get("questionToSlots") or {}
    question_by_slot: dict[str, str] = {}
    for question_id, slot_ids in question_to_slots.items():
        for slot_id in slot_ids or []:
            question_by_slot[str(slot_id)] = str(question_id)

    semantic_slots: list[SemanticSlot] = []
    seen: set[str] = set()
    for ast_block_id, slot_info in slots.items():
        component_id = str(slot_to_component.get(ast_block_id) or "")
        meta = component_meta.get(component_id, {})
        question_id = meta.get("questionId") or question_by_slot.get(ast_block_id) or str(slot_info.get("biQuery") or "")
        if not component_id and not question_id:
            continue

        repair = repair_by_target.get(ast_block_id)
        source = repair.source if repair is not None else "existing"
        confidence = repair.confidence if repair is not None else 0.9
        slot_id = f"slot_{component_id or question_id or ast_block_id}"
        if slot_id in seen:
            slot_id = f"{slot_id}_{ast_block_id}"
        seen.add(slot_id)

        semantic_slots.append(SemanticSlot(
            slotId=slot_id,
            astBlockId=ast_block_id,
            astKind=str(slot_info.get("type") or "content"),
            topicId=meta.get("topicId") or topic_by_question.get(question_id),
            chapterId=meta.get("chapterId") or None,
            sectionId=meta.get("sectionId") or None,
            questionId=question_id or None,
            componentId=component_id or None,
            componentKind=meta.get("componentKind") or "",
            fillFrom=str(slot_info.get("fillFrom") or component_id or "") or None,
            source=source,
            confidence=confidence,
        ))

    manifest_template_id = template_id or str(
        (blueprint.get("templateMeta") or {}).get("templateId")
        or (skeleton.get("metadata") or {}).get("templateId")
        or ""
    )
    issues = wiring_result.issues if wiring_result is not None else validate_wiring(skeleton, blueprint)
    counts = dict(wiring_result.counts if wiring_result is not None else {})
    counts["semanticSlots"] = len(semantic_slots)
    return SemanticSlotGraph(
        templateId=manifest_template_id,
        slots=semantic_slots,
        issues=issues,
        counts=counts,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────


_AST_KIND_FOR_SLOT = {
    "narrative": "content",
    "metric": "content",
    "metric_card": "content",
    "formula_metric": "content",
    "provenance": "content",
    "table": "table",
    "chart": "chart",
    "figure": "figure",
}


def repair_stale_fillfrom_refs(
    skeleton: dict[str, Any],
    blueprint: dict[str, Any],
) -> tuple[dict[str, Any], list[SlotPlacement]]:
    """Relink stale ``slot.fillFrom`` refs (old component ids) to current component ids.

    Older extraction passes wrote physical chart/table slots with local ids such as
    ``sp03_q01_c2``. After question reconciliation the blueprint component ids become
    semantic ids such as ``q_worker_population_ratio_gender_c2``. When a slot's
    ``biQuery`` still resolves and exactly one component of the matching kind exists
    under that question, repair the edge instead of leaving a BROKEN_FILLFROM.
    """
    questions = iter_questions(blueprint)
    component_ids: set[str] = set()
    components_by_question: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        qid = str(q.get("questionId") or "")
        comps = list(iter_components(q))
        components_by_question[qid] = comps
        for comp in comps:
            cid = comp.get("componentId") or ""
            if cid:
                component_ids.add(cid)

    repairs: list[SlotPlacement] = []

    def _walk(nodes: list[dict[str, Any]], ast_kind: str) -> None:
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            slot = node.get("slot") or {}
            fill_from = str(slot.get("fillFrom") or "")
            qid = str(node.get("biQuery") or "")
            if not fill_from or fill_from in component_ids or not qid:
                continue
            candidates = [
                c for c in components_by_question.get(qid, [])
                if _AST_KIND_FOR_SLOT.get(str(c.get("kind") or "narrative"), "content") == ast_kind
            ]
            if len(candidates) != 1:
                continue
            new_cid = str(candidates[0].get("componentId") or "")
            if not new_cid:
                continue
            node.setdefault("slot", {})["fillFrom"] = new_cid
            repairs.append(SlotPlacement(
                questionId=qid,
                componentId=new_cid,
                componentKind=str(candidates[0].get("kind") or ""),
                targetAst=f"{ast_kind}AST",
                targetId=str(node.get("chartId") or node.get("tableId") or node.get("figureId") or node.get("blockId") or ""),
                source="stale_fillfrom_repair",
                confidence=0.9,
            ))

    content = skeleton.get("contentAST") or {}
    _walk((content.get("blocks") or []) + (content.get("paragraphs") or []), "content")
    _walk((skeleton.get("tableAST") or {}).get("tables") or [], "table")
    _walk((skeleton.get("chartAST") or {}).get("charts") or [], "chart")
    _walk((skeleton.get("figureAST") or {}).get("figures") or [], "figure")

    return skeleton, repairs


def wire_template(
    skeleton: dict[str, Any],
    blueprint: dict[str, Any],
    auto_repair: bool = True,
) -> SlotWiringResult:
    """Main entry: validate, repair, and build crosswalk.

    Args:
        skeleton: template.ast.json dict
        blueprint: template.blueprint.json dict
        auto_repair: If True, create missing slots automatically.

    Returns:
        SlotWiringResult with updated skeleton, issues, repairs, crosswalk.
    """
    result = SlotWiringResult(skeleton=skeleton, blueprint=blueprint)

    # 1. Initial validation
    initial_issues = validate_wiring(skeleton, blueprint)

    # 2. Auto-repair if enabled
    repairs: list[SlotPlacement] = []
    if auto_repair:
        # 2a. Relink stale fillFrom refs (old component ids → current component ids)
        # BEFORE creating new slots, so an existing physical chart/table panel is
        # relinked instead of leaving a BROKEN_FILLFROM and creating a duplicate.
        skeleton, stale_repairs = repair_stale_fillfrom_refs(skeleton, blueprint)
        repairs.extend(stale_repairs)
        # 2b. Create any still-missing component slots.
        skeleton, created = auto_wire_missing_slots(skeleton, blueprint)
        repairs.extend(created)
        result.skeleton = skeleton
        result.repairs = repairs

    # 3. Re-validate after repair
    final_issues = validate_wiring(skeleton, blueprint)
    result.issues = final_issues

    # 4. Build crosswalk
    result.crosswalk = build_crosswalk(skeleton, blueprint)

    # 5. Counts
    questions = iter_questions(blueprint)
    total_components = sum(len(iter_components(q)) for q in questions)
    result.counts = {
        "questions": len(questions),
        "components": total_components,
        "slotsCreated": len(repairs),
        "issuesBefore": len(initial_issues),
        "issuesAfter": len(final_issues),
        "crosswalkQuestions": len(result.crosswalk.get("questionToSlots", {})),
        "crosswalkComponents": len(result.crosswalk.get("componentToSlot", {})),
    }

    return result
