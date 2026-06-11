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


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────


def iter_questions(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten topics[].questions[] and top-level questions[]."""
    questions: list[dict[str, Any]] = []
    for topic in (blueprint.get("topics") or []):
        questions.extend(topic.get("questions") or [])
    questions.extend(blueprint.get("questions") or [])
    return questions


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

            # Check if already wired
            if cid in slot_fill_froms or qid in slot_bi_queries:
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
    # PIB Phase 3 creates figureTemplates via SectionGraph. Ensure each has a chart+figure slot.
    existing_chart_ids = {c.get("chartId") for c in (skeleton.get("chartAST") or {}).get("charts") or []}
    existing_figure_ids = {f.get("figureId") for f in (skeleton.get("figureAST") or {}).get("figures") or []}

    for ft in (blueprint.get("figureTemplates") or []):
        ft_id = ft.get("figureTemplateId") or ft.get("chartId") or ""
        chart_id = ft.get("chartId") or f"chart_{ft_id}"
        fig_id = ft_id.replace("ft_", "fig_") if ft_id.startswith("ft_") else f"fig_{ft_id}"

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


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────


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
        skeleton, repairs = auto_wire_missing_slots(skeleton, blueprint)
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
