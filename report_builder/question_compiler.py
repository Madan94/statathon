"""E7 — Question Compiler + Deterministic Templates.

Generates binder-ready questions deterministically from table semantics (E3),
measure families (E2), enriched entities (E6), and chart semantics (E11).

Design: deterministic-first, LLM-second.
- 60%+ questions from table/chart patterns (guaranteed quality)
- LLM enrichment is optional (E7 does NOT call LLM itself)
- Every question has: requiredEntities, analyticsSpec, answerStructure, formulaIntent

Usage:
    from report_builder.question_compiler import compile_questions
    result = compile_questions(tables=tables, entities=entities, families=families, figures=figures)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from report_builder.entity_id_generator import generate_question_id


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AnswerComponentPlan:
    componentId: str = ""
    kind: str = "narrative"         # narrative | table | chart | metric_card
    order: int = 1
    outputContract: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "componentId": self.componentId,
            "kind": self.kind,
            "order": self.order,
            "outputContract": dict(self.outputContract),
        }


@dataclass
class QuestionPlan:
    questionId: str = ""
    intent: str = ""
    questionType: str = "comparison"
    priority: int = 2
    requiredEntities: list[dict[str, Any]] = field(default_factory=list)
    analyticsSpec: dict[str, Any] = field(default_factory=dict)
    answerStructure: dict[str, Any] = field(default_factory=dict)
    sourceTable: str | None = None
    sourceFigure: str | None = None
    generationMethod: str = "table_pattern"
    formulaIntent: dict[str, Any] | None = None
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "questionId": self.questionId,
            "intent": self.intent,
            "questionType": self.questionType,
            "priority": self.priority,
            "requiredEntities": list(self.requiredEntities),
            "analyticsSpec": dict(self.analyticsSpec),
            "answerStructure": dict(self.answerStructure),
            "generationMethod": self.generationMethod,
        }
        if self.sourceTable:
            d["sourceTable"] = self.sourceTable
        if self.sourceFigure:
            d["sourceFigure"] = self.sourceFigure
        if self.formulaIntent:
            d["formulaIntent"] = dict(self.formulaIntent)
        return d


@dataclass
class QuestionDiagnostic:
    questionId: str = ""
    severity: str = "warn"
    code: str = ""
    message: str = ""
    recommendedAction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"questionId": self.questionId, "severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class QuestionCompileResult:
    questions: list[QuestionPlan] = field(default_factory=list)
    droppedQuestions: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[QuestionDiagnostic] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"questionCount": len(self.questions), "droppedCount": len(self.droppedQuestions), "counts": dict(self.counts)}


# ─────────────────────────────────────────────────────────────────────────────
# Question budget
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_BUDGET = {"per_table": 4, "per_topic": 8, "per_blueprint": 30, "priority_cutoff": 4}


# ─────────────────────────────────────────────────────────────────────────────
# Answer structure builder
# ─────────────────────────────────────────────────────────────────────────────


def _build_answer_structure(
    question_id: str,
    question_type: str,
    source_table: str | None,
    source_figure: Any | None,
    chart_type: str | None = None,
    measure_ref: str | None = None,
    dimension_ref: str | None = None,
    table_template_ref: str | None = None,
) -> dict[str, Any]:
    """Build answerStructure with narrative + table + chart components."""
    components: list[dict[str, Any]] = []
    order = 1

    # 1. Narrative always
    components.append({
        "componentId": f"{question_id}_c{order}",
        "kind": "narrative",
        "order": order,
        "outputContract": {"type": "prose", "maxWords": 90},
    })
    order += 1

    # 2. Table if source table exists
    if source_table:
        tc: dict[str, Any] = {"type": "table"}
        if table_template_ref:
            tc["tableTemplateRef"] = table_template_ref
        components.append({
            "componentId": f"{question_id}_c{order}",
            "kind": "table",
            "order": order,
            "outputContract": tc,
        })
        order += 1

    # 3. Chart based on question type or source figure
    resolved_chart = chart_type
    if not resolved_chart:
        if question_type == "composition":
            resolved_chart = "pie"
        elif question_type in ("comparison", "ranking"):
            resolved_chart = "bar"
        elif question_type == "trend":
            resolved_chart = "line"

    if resolved_chart:
        cc: dict[str, Any] = {"type": "chart", "chartType": resolved_chart}
        if dimension_ref:
            cc["xAxis"] = dimension_ref
        if measure_ref:
            cc["yAxis"] = measure_ref
        components.append({
            "componentId": f"{question_id}_c{order}",
            "kind": "chart",
            "order": order,
            "outputContract": cc,
        })

    return {"components": components}


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic table patterns
# ─────────────────────────────────────────────────────────────────────────────


def _questions_from_table(table: Any, entities: list[Any] | None, families: list[Any] | None) -> list[QuestionPlan]:
    """Generate deterministic questions from one table semantic model."""
    questions: list[QuestionPlan] = []

    table_id = _get(table, "tableId") or ""
    dimensions = _get(table, "dimensions") or []
    measures = _get(table, "measures") or []
    time_dim = _get(table, "timeDimension")
    col_groups = _get(table, "columnGroups") or []
    norm_advice = _get(table, "normalizationAdvice") or "NONE"
    title = _get(table, "tableTitle") or ""

    # If measures is empty but column groups exist, use group labels as measures
    if not measures and col_groups:
        for g in col_groups:
            label = g.label if hasattr(g, "label") else (g.get("label") or "")
            if label:
                measures.append(label)

    # Find primary dimension and measure
    dim_ref = _find_entity_ref(dimensions[0], entities) if dimensions else None
    primary_measure = measures[0] if measures else None
    measure_ref = _find_entity_ref(primary_measure, entities) if primary_measure else None

    # Detect periods
    periods: list[str] = []
    for g in col_groups:
        g_periods = g.periods if hasattr(g, "periods") else (g.get("periods") or [])
        periods.extend(g_periods)
    periods = sorted(set(periods))
    current_period = periods[-1] if periods else None
    prior_period = periods[-2] if len(periods) >= 2 else None

    # ── Pattern 1: Current-period comparison ──
    if dim_ref and measure_ref:
        intent = f"Compare {primary_measure} across {dimensions[0]} for {current_period or 'current period'}"
        qid = generate_question_id(intent, table_id)
        req_ents = [
            {"entityId": measure_ref, "role": "measure", "required": True},
            {"entityId": dim_ref, "role": "grouping", "required": True},
        ]
        if time_dim and current_period:
            req_ents.append({"entityId": time_dim, "role": "time", "required": False, "defaultMember": current_period})

        q = QuestionPlan(
            questionId=qid,
            intent=intent,
            questionType="comparison",
            priority=1,
            requiredEntities=req_ents,
            analyticsSpec={
                "operation": "group_aggregate",
                "measure": {"entityRef": measure_ref, "agg": "sum"},
                "groupBy": [{"entityRef": dim_ref}],
                "sort": {"by": "measure", "order": "desc"},
            },
            sourceTable=table_id,
            generationMethod="table_pattern",
            formulaIntent={"type": "DIRECT"},
        )
        q.answerStructure = _build_answer_structure(qid, "comparison", table_id, None, "bar", measure_ref, dim_ref)
        questions.append(q)

    # ── Pattern 2: Top-N ranking ──
    if dim_ref and measure_ref:
        intent = f"Top {dimensions[0]} by {primary_measure} in {current_period or 'current period'}"
        qid = generate_question_id(intent, table_id)
        req_ents = [
            {"entityId": measure_ref, "role": "measure", "required": True},
            {"entityId": dim_ref, "role": "grouping", "required": True},
        ]
        if time_dim and current_period:
            req_ents.append({"entityId": time_dim, "role": "time", "required": False, "defaultMember": current_period})

        q = QuestionPlan(
            questionId=qid,
            intent=intent,
            questionType="ranking",
            priority=2,
            requiredEntities=req_ents,
            analyticsSpec={
                "operation": "group_aggregate",
                "measure": {"entityRef": measure_ref, "agg": "sum"},
                "groupBy": [{"entityRef": dim_ref}],
                "sort": {"by": "measure", "order": "desc"},
                "topN": 10,
            },
            sourceTable=table_id,
            generationMethod="table_pattern",
            formulaIntent={"type": "DIRECT"},
        )
        q.answerStructure = _build_answer_structure(qid, "ranking", table_id, None, "bar", measure_ref, dim_ref)
        questions.append(q)

    # ── Pattern 3: YoY growth ──
    if dim_ref and measure_ref and current_period and prior_period:
        intent = f"Year-over-year change in {primary_measure} across {dimensions[0]} from {prior_period} to {current_period}"
        qid = generate_question_id(intent, table_id)
        req_ents = [
            {"entityId": measure_ref, "role": "measure", "required": True},
            {"entityId": dim_ref, "role": "grouping", "required": True},
        ]
        if time_dim:
            req_ents.append({"entityId": time_dim, "role": "time", "required": True})

        q = QuestionPlan(
            questionId=qid,
            intent=intent,
            questionType="trend",
            priority=3,
            requiredEntities=req_ents,
            analyticsSpec={
                "operation": "growth",
                "measure": {"entityRef": measure_ref},
                "groupBy": [{"entityRef": dim_ref}],
            },
            sourceTable=table_id,
            generationMethod="table_pattern",
            formulaIntent={"type": "GROWTH", "periods": {"current": current_period, "prior": prior_period}, "requiresPriorPeriod": True},
        )
        q.answerStructure = _build_answer_structure(qid, "trend", table_id, None, "grouped_bar", measure_ref, dim_ref)
        questions.append(q)

    # ── Pattern 4: Composition (if measure family exists) ──
    if families:
        for family in families:
            f_id = family.familyId if hasattr(family, "familyId") else (family.get("familyId") or "")
            base = family.baseConcept if hasattr(family, "baseConcept") else (family.get("baseConcept") or "")
            cat_dim = family.categoryDimension if hasattr(family, "categoryDimension") else (family.get("categoryDimension") or "")
            members = family.members if hasattr(family, "members") else (family.get("members") or [])

            if len(members) >= 2 and dim_ref:
                intent = f"Composition of {base} by category for {dimensions[0]}"
                qid = generate_question_id(intent, table_id)
                member_refs = []
                for m in members:
                    ref = m.entityRef if hasattr(m, "entityRef") else (m.get("entityRef") or "")
                    is_total = m.isTotal if hasattr(m, "isTotal") else (m.get("isTotal") or False)
                    if ref and not is_total:
                        member_refs.append(ref)

                req_ents = [{"entityId": r, "role": "measure", "required": True} for r in member_refs[:3]]
                if dim_ref:
                    req_ents.append({"entityId": dim_ref, "role": "grouping", "required": True})

                q = QuestionPlan(
                    questionId=qid,
                    intent=intent,
                    questionType="composition",
                    priority=2,
                    requiredEntities=req_ents,
                    analyticsSpec={
                        "operation": "multi_measure_composition",
                        "measures": [{"entityRef": r} for r in member_refs[:3]],
                        "groupBy": [{"entityRef": dim_ref}] if dim_ref else [],
                    },
                    sourceTable=table_id,
                    generationMethod="table_pattern",
                    formulaIntent={"type": "DIRECT", "composition": True},
                )
                q.answerStructure = _build_answer_structure(qid, "composition", table_id, None, "stacked_bar", member_refs[0] if member_refs else None, dim_ref)
                questions.append(q)
                break  # One composition per table

    return questions


# ─────────────────────────────────────────────────────────────────────────────
# Chart-derived questions
# ─────────────────────────────────────────────────────────────────────────────


def _questions_from_figures(figures: list[Any], entities: list[Any] | None) -> list[QuestionPlan]:
    """Generate questions from chart semantic models."""
    questions: list[QuestionPlan] = []

    for fig in figures:
        chart_type = _get(fig, "chartType") or "unknown"
        subject = _get(fig, "chartSubject") or ""
        fig_id = _get(fig, "figureTemplateId") or ""
        measure_refs = _get(fig, "measureRefs") or []
        dim_ref = _get(fig, "dimensionRef")
        cat_ref = _get(fig, "categoryEntityRef")

        if chart_type == "unknown" or not subject:
            continue

        # Determine question type from chart type
        if chart_type == "pie":
            qtype = "composition"
        elif chart_type in ("bar", "grouped_bar"):
            qtype = "comparison"
        elif chart_type == "line":
            qtype = "trend"
        elif chart_type == "map":
            qtype = "comparison"
        else:
            qtype = "comparison"

        intent = f"Show {subject}"
        qid = generate_question_id(intent)

        req_ents: list[dict[str, Any]] = []
        if measure_refs:
            req_ents.append({"entityId": measure_refs[0], "role": "measure", "required": True})
        if dim_ref:
            req_ents.append({"entityId": dim_ref, "role": "grouping", "required": True})
        if cat_ref:
            req_ents.append({"entityId": cat_ref, "role": "grouping", "required": True})

        if not req_ents:
            continue

        q = QuestionPlan(
            questionId=qid,
            intent=intent,
            questionType=qtype,
            priority=3,
            requiredEntities=req_ents,
            analyticsSpec={
                "operation": "group_aggregate",
                "measure": {"entityRef": measure_refs[0]} if measure_refs else {},
                "groupBy": [{"entityRef": dim_ref or cat_ref or ""}],
            },
            sourceFigure=fig_id,
            generationMethod="chart_pattern",
            formulaIntent={"type": "DIRECT"},
        )
        q.answerStructure = _build_answer_structure(
            qid, qtype, None, fig, chart_type,
            measure_refs[0] if measure_refs else None, dim_ref,
        )
        questions.append(q)

    return questions


# ─────────────────────────────────────────────────────────────────────────────
# Dedup + budget
# ─────────────────────────────────────────────────────────────────────────────


def _dedup_questions(questions: list[QuestionPlan]) -> list[QuestionPlan]:
    """Deduplicate by operation + measure + groupBy + questionType signature."""
    seen: set[str] = set()
    deduped: list[QuestionPlan] = []

    for q in questions:
        spec = q.analyticsSpec
        op = spec.get("operation", "")
        measure = str(spec.get("measure", ""))
        group_by = str(spec.get("groupBy", ""))
        top_n = str(spec.get("topN", ""))
        sig = f"{q.questionType}|{op}|{measure}|{group_by}|{top_n}"

        if sig not in seen:
            seen.add(sig)
            deduped.append(q)

    return deduped


def _apply_budget(questions: list[QuestionPlan], budget: dict[str, int] | None = None) -> tuple[list[QuestionPlan], list[dict[str, Any]]]:
    """Apply question budget. Returns (kept, dropped)."""
    b = budget or DEFAULT_BUDGET
    max_total = b.get("per_blueprint", 30)
    priority_cutoff = b.get("priority_cutoff", 4)

    # Filter by priority
    eligible = [q for q in questions if q.priority <= priority_cutoff]
    dropped = [{"questionId": q.questionId, "reason": "priority_too_low"} for q in questions if q.priority > priority_cutoff]

    # Sort: table_pattern first, then chart_pattern, then by priority
    method_order = {"table_pattern": 0, "chart_pattern": 1, "llm": 2, "repair": 3}
    eligible.sort(key=lambda q: (method_order.get(q.generationMethod, 9), q.priority))

    kept = eligible[:max_total]
    for q in eligible[max_total:]:
        dropped.append({"questionId": q.questionId, "reason": "budget_exceeded"})

    return kept, dropped


# ─────────────────────────────────────────────────────────────────────────────
# Validation + repair
# ─────────────────────────────────────────────────────────────────────────────

_VALID_QTYPES = frozenset({"comparison", "trend", "composition", "ranking", "summary", "descriptive"})
_VALID_KINDS = frozenset({"narrative", "table", "chart", "metric_card"})


def validate_question(question: QuestionPlan, entity_ids: set[str]) -> list[QuestionDiagnostic]:
    """Validate one question. Returns diagnostics (empty = valid)."""
    diags: list[QuestionDiagnostic] = []
    qid = question.questionId

    if not qid:
        diags.append(QuestionDiagnostic(qid, "error", "MISSING_QID", "No questionId"))
    if len(question.intent.split()) < 4:
        diags.append(QuestionDiagnostic(qid, "warn", "WEAK_INTENT", "Intent too short"))
    if question.questionType not in _VALID_QTYPES:
        diags.append(QuestionDiagnostic(qid, "warn", "INVALID_QTYPE", f"Unknown type: {question.questionType}"))

    # Entity refs
    for req in question.requiredEntities:
        eid = req.get("entityId", "")
        if eid and eid not in entity_ids:
            diags.append(QuestionDiagnostic(qid, "error", "BROKEN_ENTITY_REF", f"Entity {eid} not found"))

    has_measure = any(r.get("role") == "measure" for r in question.requiredEntities)
    if not has_measure and question.questionType not in ("descriptive", "summary"):
        diags.append(QuestionDiagnostic(qid, "warn", "NO_MEASURE", "No measure entity"))

    # AnalyticsSpec
    if not question.analyticsSpec.get("operation"):
        diags.append(QuestionDiagnostic(qid, "error", "MISSING_OPERATION", "No analyticsSpec.operation"))

    # AnswerStructure
    components = (question.answerStructure.get("components") or [])
    if not components:
        diags.append(QuestionDiagnostic(qid, "error", "NO_COMPONENTS", "Empty answerStructure.components"))
    for comp in components:
        if not comp.get("componentId"):
            diags.append(QuestionDiagnostic(qid, "warn", "MISSING_CID", "Component missing componentId"))
        if comp.get("kind") not in _VALID_KINDS:
            diags.append(QuestionDiagnostic(qid, "warn", "INVALID_KIND", f"Unknown kind: {comp.get('kind')}"))
        if not comp.get("outputContract"):
            diags.append(QuestionDiagnostic(qid, "warn", "MISSING_OUTPUT_CONTRACT", "No outputContract"))

    return diags


def repair_question(question: QuestionPlan) -> QuestionPlan:
    """Auto-repair common issues in a question."""
    # Fix missing componentIds
    for i, comp in enumerate(question.answerStructure.get("components") or []):
        if not comp.get("componentId"):
            comp["componentId"] = f"{question.questionId}_c{i+1}"

    # Fix missing outputContract
    for comp in (question.answerStructure.get("components") or []):
        if not comp.get("outputContract"):
            kind = comp.get("kind", "narrative")
            if kind == "narrative":
                comp["outputContract"] = {"type": "prose", "maxWords": 90}
            elif kind == "table":
                comp["outputContract"] = {"type": "table"}
            elif kind == "chart":
                comp["outputContract"] = {"type": "chart", "chartType": "bar"}
            elif kind == "metric_card":
                comp["outputContract"] = {"type": "metric"}

    # Fix missing sort for ranking
    if question.questionType == "ranking" and "sort" not in question.analyticsSpec:
        question.analyticsSpec["sort"] = {"by": "measure", "order": "desc"}

    # Fix missing questionId
    if not question.questionId:
        question.questionId = generate_question_id(question.intent)

    question.generationMethod = "repair" if not question.generationMethod else question.generationMethod
    return question


# ─────────────────────────────────────────────────────────────────────────────
# Main compiler
# ─────────────────────────────────────────────────────────────────────────────


def compile_questions(
    tables: list[Any] | None = None,
    entities: list[Any] | None = None,
    measure_families: list[Any] | None = None,
    figures: list[Any] | None = None,
    topics: list[Any] | None = None,
    budget: dict[str, int] | None = None,
) -> QuestionCompileResult:
    """Compile deterministic questions from semantic models.

    Args:
        tables: TableSemanticModel list from E3.
        entities: Enriched entities from E6.
        measure_families: MeasureFamily list from E2.
        figures: FigureSemanticModel list from E11.
        topics: Optional topic nodes for context.
        budget: Question budget overrides.

    Returns:
        QuestionCompileResult with questions, dropped, diagnostics.
    """
    result = QuestionCompileResult()
    all_questions: list[QuestionPlan] = []

    # 1. Generate from tables
    table_questions = 0
    if tables:
        for table in tables:
            qs = _questions_from_table(table, entities, measure_families)
            all_questions.extend(qs)
            table_questions += len(qs)

    # 2. Generate from charts
    chart_questions = 0
    if figures:
        qs = _questions_from_figures(figures, entities)
        all_questions.extend(qs)
        chart_questions = len(qs)

    # 3. Deduplicate
    before_dedup = len(all_questions)
    all_questions = _dedup_questions(all_questions)

    # 4. Apply budget
    kept, dropped = _apply_budget(all_questions, budget)
    result.droppedQuestions = dropped

    # 5. Validate + repair
    entity_ids = set()
    if entities:
        for e in entities:
            eid = _get(e, "entityId") or ""
            if eid:
                entity_ids.add(eid)

    for q in kept:
        q = repair_question(q)
        diags = validate_question(q, entity_ids)
        result.diagnostics.extend(diags)
        result.questions.append(q)

    # 6. Counts
    result.counts = {
        "tablePatterns": table_questions,
        "chartPatterns": chart_questions,
        "totalGenerated": before_dedup,
        "afterDedup": len(all_questions),
        "kept": len(result.questions),
        "dropped": len(result.droppedQuestions),
        "withErrors": sum(1 for d in result.diagnostics if d.severity == "error"),
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


def _find_entity_ref(name: str | None, entities: list[Any] | None) -> str | None:
    """Find entity ID by canonical name or alias match."""
    if not name or not entities:
        return None
    name_lower = name.lower().strip()
    # Normalize slashes/spaces for matching
    name_norm = re.sub(r'[\s/]+', '', name_lower)

    for e in entities:
        eid = _get(e, "entityId") or ""
        ename = (_get(e, "canonicalName") or "").lower().strip()
        ename_norm = re.sub(r'[\s/]+', '', ename)
        aliases = _get(e, "aliases") or []

        # Exact match
        if ename == name_lower or ename_norm == name_norm:
            return eid
        # Alias match
        for a in aliases:
            if a and (a.lower().strip() == name_lower or re.sub(r'[\s/]+', '', a.lower()) == name_norm):
                return eid

    # Partial match (name contains entity name or vice versa)
    for e in entities:
        eid = _get(e, "entityId") or ""
        ename = (_get(e, "canonicalName") or "").lower().strip()
        if ename and (ename in name_lower or name_lower in ename):
            return eid
    return None
