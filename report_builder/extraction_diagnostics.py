"""E9 — Extraction Diagnostics + Pass Scoring.

Produces the quality scorecard for extraction: category scores, binder readiness,
pass-level diagnostics, quarantine logs, repair logs, runtime summaries, and
binder compatibility prediction.

This is the single source of truth for "is this extraction binder-ready?"

Usage:
    from report_builder.extraction_diagnostics import build_extraction_diagnostics
    diag = build_extraction_diagnostics(blueprint=bp, skeleton=ast, ...)
    print(diag.status, diag.binderReadinessScore)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DiagnosticIssue:
    severity: str = "warn"
    code: str = ""
    message: str = ""
    path: str = ""
    recommendedAction: str = ""
    sourcePhase: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.path:
            d["path"] = self.path
        if self.sourcePhase:
            d["sourcePhase"] = self.sourcePhase
        return d


@dataclass
class ExtractionCounts:
    entities: int = 0
    entitiesDropped: int = 0
    entitiesRepaired: int = 0
    measureFamilies: int = 0
    questions: int = 0
    questionsFromTemplates: int = 0
    questionsFromLLM: int = 0
    questionsDropped: int = 0
    tables: int = 0
    tablesGhost: int = 0
    charts: int = 0
    figures: int = 0
    topics: int = 0
    slotsWired: int = 0
    slotsOrphaned: int = 0
    runtimeCalls: int = 0
    fallbacks: int = 0
    cacheHits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v != 0}


@dataclass
class BinderCompatibilityPrediction:
    blueprintQAWillPass: bool = True
    expectedResolverConfidence: str = "medium"
    expectedIssues: list[str] = field(default_factory=list)
    recommendation: str = "proceed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "blueprintQAWillPass": self.blueprintQAWillPass,
            "expectedResolverConfidence": self.expectedResolverConfidence,
            "expectedIssues": list(self.expectedIssues),
            "recommendation": self.recommendation,
        }


@dataclass
class ExtractionDiagnostics:
    status: str = "VALID"
    contractVersion: str = "template.extraction.v2"
    binderReadinessScore: float = 0.0
    passScores: dict[str, float] = field(default_factory=dict)
    categoryScores: dict[str, float] = field(default_factory=dict)
    counts: ExtractionCounts = field(default_factory=ExtractionCounts)
    blockingErrors: list[DiagnosticIssue] = field(default_factory=list)
    warnings: list[DiagnosticIssue] = field(default_factory=list)
    quarantinedItems: list[dict[str, Any]] = field(default_factory=list)
    repairsApplied: list[dict[str, Any]] = field(default_factory=list)
    binderCompatibility: BinderCompatibilityPrediction = field(default_factory=BinderCompatibilityPrediction)
    runtime: dict[str, Any] = field(default_factory=dict)
    crosswalk: dict[str, Any] | None = None
    generatedAt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "contractVersion": self.contractVersion,
            "binderReadinessScore": round(self.binderReadinessScore, 3),
            "passScores": {k: round(v, 3) for k, v in self.passScores.items()},
            "categoryScores": {k: round(v, 3) for k, v in self.categoryScores.items()},
            "counts": self.counts.to_dict(),
            "blockingErrors": [e.to_dict() for e in self.blockingErrors],
            "warnings": [w.to_dict() for w in self.warnings],
            "quarantinedCount": len(self.quarantinedItems),
            "repairsCount": len(self.repairsApplied),
            "binderCompatibility": self.binderCompatibility.to_dict(),
            "runtime": self.runtime,
            "generatedAt": self.generatedAt,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Category scoring functions
# ─────────────────────────────────────────────────────────────────────────────


def score_entity_hygiene(hygiene_result: Any = None) -> float:
    """Score entity hygiene quality (0-1). Higher = cleaner entities."""
    if hygiene_result is None:
        return 0.5
    diag = hygiene_result.diagnostics if hasattr(hygiene_result, "diagnostics") else (hygiene_result if isinstance(hygiene_result, dict) else {})
    input_count = diag.get("inputCount", 0)
    entity_count = diag.get("entityCount", 0)
    quarantine_count = diag.get("quarantineCount", 0)
    if input_count == 0:
        return 0.0
    # Good: high clean ratio, noise quarantined
    survival_rate = entity_count / input_count
    quarantine_rate = quarantine_count / input_count
    # Reward: 40-70% survival is ideal (too high = not filtering enough, too low = too aggressive)
    if 0.3 <= survival_rate <= 0.8:
        score = 0.7 + (quarantine_rate * 0.3)
    elif survival_rate > 0.8:
        score = 0.5  # Probably not filtering enough
    else:
        score = survival_rate + 0.2
    return min(score, 1.0)


def score_entity_completeness(entities: list[Any] | None = None) -> float:
    """Score entity completeness (aliases, units, domains, aggregation)."""
    if not entities:
        return 0.0
    total = len(entities)
    if total == 0:
        return 0.0
    with_aliases = sum(1 for e in entities if _get(e, "aliases"))
    with_unit = sum(1 for e in entities if _get(e, "unit") and _get(e, "entityType") == "measure")
    with_domain = sum(1 for e in entities if _has_domain(e))
    with_agg = sum(1 for e in entities if _get(e, "aggregation"))
    measures = sum(1 for e in entities if _get(e, "entityType") == "measure")

    alias_score = with_aliases / total
    unit_score = with_unit / max(measures, 1)
    domain_score = with_domain / total
    agg_score = with_agg / max(measures, 1)

    return (alias_score * 0.35 + unit_score * 0.25 + domain_score * 0.25 + agg_score * 0.15)


def score_table_semantics(table_result: Any = None) -> float:
    """Score table semantic model quality."""
    if table_result is None:
        return 0.5
    tables = table_result.tables if hasattr(table_result, "tables") else (table_result.get("tables") or [] if isinstance(table_result, dict) else [])
    if not tables:
        return 0.3
    total = len(tables)
    with_groups = sum(1 for t in tables if _get(t, "columnGroups"))
    with_dims = sum(1 for t in tables if _get(t, "dimensions"))
    with_measures = sum(1 for t in tables if _get(t, "measures") or _get(t, "columnGroups"))
    with_norm = sum(1 for t in tables if _get(t, "normalizationAdvice") and _get(t, "normalizationAdvice") != "NONE")

    return (with_groups / total * 0.3 + with_dims / total * 0.25 + with_measures / total * 0.25 + with_norm / total * 0.2)


def score_unit_coverage(entities: list[Any] | None = None, statistical_context: Any = None) -> float:
    """Score unit coverage across measures."""
    if not entities:
        return 0.0
    measures = [e for e in entities if _get(e, "entityType") == "measure"]
    if not measures:
        return 0.5
    with_unit = sum(1 for m in measures if _get(m, "unit"))
    return with_unit / len(measures)


def score_question_completeness(question_result: Any = None) -> float:
    """Score question completeness (structure, spec, entities)."""
    if question_result is None:
        return 0.5
    questions = question_result.questions if hasattr(question_result, "questions") else (question_result.get("questions") or [] if isinstance(question_result, dict) else [])
    if not questions:
        return 0.0
    total = len(questions)
    with_spec = sum(1 for q in questions if _has_spec(q))
    with_structure = sum(1 for q in questions if _has_structure(q))
    with_entities = sum(1 for q in questions if _get(q, "requiredEntities"))
    with_formula = sum(1 for q in questions if _get(q, "formulaIntent"))

    return (with_spec / total * 0.3 + with_structure / total * 0.3 + with_entities / total * 0.25 + with_formula / total * 0.15)


def score_cross_reference_integrity(wiring_result: Any = None) -> float:
    """Score slot wiring integrity."""
    if wiring_result is None:
        return 0.5
    counts = wiring_result.counts if hasattr(wiring_result, "counts") else (wiring_result.get("counts") or {} if isinstance(wiring_result, dict) else {})
    issues = wiring_result.issues if hasattr(wiring_result, "issues") else (wiring_result.get("issues") or [] if isinstance(wiring_result, dict) else [])

    total_components = counts.get("components", 0)
    wired_components = counts.get("crosswalkComponents", 0)
    error_issues = sum(1 for i in issues if (i.severity if hasattr(i, "severity") else i.get("severity", "")) == "error")

    if total_components == 0:
        return 0.5
    wiring_ratio = wired_components / total_components
    error_penalty = min(error_issues * 0.15, 0.5)
    return max(wiring_ratio - error_penalty, 0.0)


def score_value_free(value_free_result: Any = None) -> float:
    """Score value-free compliance. 1.0 if no errors, 0.0 if leakages."""
    if value_free_result is None:
        return 1.0  # Assume clean if not checked
    if hasattr(value_free_result, "has_errors"):
        return 0.0 if value_free_result.has_errors else 1.0
    if hasattr(value_free_result, "leakages"):
        errors = [l for l in value_free_result.leakages if (l.severity if hasattr(l, "severity") else "error") == "error"]
        return 0.0 if errors else 1.0
    return 1.0


def score_chart_semantics(chart_result: Any = None) -> float:
    """Score chart/figure semantic quality."""
    if chart_result is None:
        return 0.5
    figures = chart_result.figures if hasattr(chart_result, "figures") else (chart_result.get("figures") or [] if isinstance(chart_result, dict) else [])
    if not figures:
        return 0.3
    total = len(figures)
    with_type = sum(1 for f in figures if _get(f, "chartType") and _get(f, "chartType") != "unknown")
    with_subject = sum(1 for f in figures if _get(f, "chartSubject"))
    with_entities = sum(1 for f in figures if _get(f, "measureRefs") or _get(f, "dimensionRef"))

    return (with_type / total * 0.4 + with_subject / total * 0.3 + with_entities / total * 0.3)


# ─────────────────────────────────────────────────────────────────────────────
# Composite scoring
# ─────────────────────────────────────────────────────────────────────────────

_CATEGORY_WEIGHTS = {
    "entityHygiene": 0.25,
    "questionCompleteness": 0.20,
    "crossReferenceIntegrity": 0.15,
    "tableSemantics": 0.15,
    "unitCoverage": 0.10,
    "entityCompleteness": 0.10,
    "valueFreeCompliance": 0.05,
}

# PIB press releases don't have data tables — redistribute weight to questions/entities
_CATEGORY_WEIGHTS_PIB = {
    "entityHygiene": 0.20,
    "questionCompleteness": 0.30,
    "crossReferenceIntegrity": 0.15,
    "tableSemantics": 0.0,         # N/A for PIB
    "unitCoverage": 0.15,
    "entityCompleteness": 0.15,
    "valueFreeCompliance": 0.05,
}


def compute_binder_readiness(category_scores: dict[str, float], doc_type: str = "") -> float:
    """Compute weighted binder readiness score (0-1).

    Uses doc-type-specific weights when available.
    """
    weights = _CATEGORY_WEIGHTS_PIB if doc_type == "pib_press_release" else _CATEGORY_WEIGHTS
    score = 0.0
    for cat, weight in weights.items():
        score += category_scores.get(cat, 0.5) * weight
    return min(score, 1.0)


def determine_status(score: float, blocking_errors: list) -> str:
    """Determine extraction status from score and blocking errors."""
    if blocking_errors:
        return "INVALID"
    if score >= 0.75:
        return "VALID"
    if score >= 0.50:
        return "VALID_WITH_WARNINGS"
    return "INVALID"


# ─────────────────────────────────────────────────────────────────────────────
# Binder compatibility prediction
# ─────────────────────────────────────────────────────────────────────────────


def predict_binder_compatibility(
    category_scores: dict[str, float],
    contract_result: Any = None,
    value_free_result: Any = None,
    doc_type: str = "",
) -> BinderCompatibilityPrediction:
    """Predict binder compatibility from category scores."""
    pred = BinderCompatibilityPrediction()

    # Check hard blocks
    vf_score = category_scores.get("valueFreeCompliance", 1.0)
    if vf_score < 1.0:
        pred.blueprintQAWillPass = False
        pred.recommendation = "invalid"
        pred.expectedIssues.append("Value leakage detected — must fix before binding")
        return pred

    if contract_result and hasattr(contract_result, "has_errors") and contract_result.has_errors:
        pred.blueprintQAWillPass = False
        pred.recommendation = "invalid"
        pred.expectedIssues.append("Extraction contract validation failed")
        return pred

    # Entity completeness → resolver confidence
    ec = category_scores.get("entityCompleteness", 0.5)
    if ec >= 0.80:
        pred.expectedResolverConfidence = "high"
    elif ec >= 0.55:
        pred.expectedResolverConfidence = "medium"
    else:
        pred.expectedResolverConfidence = "low"
        pred.expectedIssues.append("Low entity completeness — resolver confidence will be low")

    # Recommendations
    readiness = compute_binder_readiness(category_scores, doc_type=doc_type)
    if readiness >= 0.75:
        pred.recommendation = "proceed"
        pred.blueprintQAWillPass = True
    elif category_scores.get("entityCompleteness", 0) < 0.5:
        pred.recommendation = "fix_entities"
        pred.expectedIssues.append("Entities need aliases/units/valueDomain")
    elif category_scores.get("questionCompleteness", 0) < 0.5:
        pred.recommendation = "fix_questions"
        pred.expectedIssues.append("Questions need analyticsSpec/answerStructure")
    elif doc_type != "pib_press_release" and category_scores.get("tableSemantics", 0) < 0.5:
        pred.recommendation = "fix_tables"
        pred.expectedIssues.append("Tables need columnGroups/headerPath")
    else:
        pred.recommendation = "proceed"
        pred.blueprintQAWillPass = True

    return pred


# ─────────────────────────────────────────────────────────────────────────────
# S3.5 binder-executability gate
# ─────────────────────────────────────────────────────────────────────────────


def _iter_questions(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """All questions across every outline nesting level + top-level questions[]."""
    out: list[dict[str, Any]] = []

    def _walk(node: dict[str, Any]) -> None:
        for q in node.get("questions") or []:
            if isinstance(q, dict):
                out.append(q)
        for key in ("chapters", "sections", "subtopics", "subsections", "children"):
            for child in node.get(key) or []:
                if isinstance(child, dict):
                    _walk(child)

    for topic in (blueprint.get("topics") or blueprint.get("sections") or []):
        if isinstance(topic, dict):
            _walk(topic)
    out.extend(q for q in (blueprint.get("questions") or []) if isinstance(q, dict))
    return out


def _question_requires_measure(question: dict[str, Any]) -> bool:
    qtype = str(question.get("questionType") or "").lower()
    spec = question.get("analyticsSpec") or {}
    operation = str(spec.get("operation") or "").lower() if isinstance(spec, dict) else ""
    return qtype not in ("descriptive", "describe", "summary") and operation not in ("describe", "summary", "summary_stats")


def _has_measure_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("entityRef") or value.get("entityId") or value.get("column"))
    return bool(value)


def _has_measure_spec(question: dict[str, Any]) -> bool:
    spec = question.get("analyticsSpec") or {}
    if not isinstance(spec, dict):
        return False
    if _has_measure_ref(spec.get("measure")):
        return True
    measures = spec.get("measures")
    if isinstance(measures, list):
        return any(_has_measure_ref(m) for m in measures)
    return _has_measure_ref(measures)


def _has_required_measure(question: dict[str, Any]) -> bool:
    for req in question.get("requiredEntities") or []:
        if req.get("role") == "measure" and (req.get("entityId") or req.get("entityRef")):
            return True
    return False


def is_enterprise_blueprint(blueprint: dict[str, Any]) -> bool:
    """Whether a blueprint opts in to enterprise-grade S3.5 validation.

    Enterprise mode is a deliberate opt-in so legacy/gold/built-in packages keep
    their compact behaviour. A blueprint is enterprise when
    ``templateMeta.enterpriseReady`` is set (the deterministic enricher sets this)
    or when it already carries enterprise contract blocks.
    """
    if not isinstance(blueprint, dict):
        return False
    meta = blueprint.get("templateMeta") or {}
    if meta.get("enterpriseReady"):
        return True
    return any(
        blueprint.get(key)
        for key in ("officerCustomization", "binderDeliverableContract", "publicationContract", "officerWorkbench")
    )


def apply_s35_emission_gate(
    diag: "ExtractionDiagnostics",
    *,
    blueprint: dict[str, Any],
    skeleton: dict[str, Any] | None = None,
    runtime_trace: dict[str, Any] | None = None,
) -> None:
    """Apply S3.5 binder-executability blockers to final extraction diagnostics.

    Binder-executability blockers (broken refs, non-executable analytic questions,
    missing measure evidence) apply to every package. Enterprise-shape blockers
    (top-level contracts, per-question enterprise fields, provenance components, AST
    overlays) apply **only** when the blueprint opts in to enterprise mode.
    """
    if not blueprint:
        return
    enterprise_mode = is_enterprise_blueprint(blueprint)

    def _block(code: str, message: str, path: str = "", action: str = "") -> None:
        diag.blockingErrors.append(DiagnosticIssue(
            severity="error",
            code=code,
            message=message,
            path=path,
            recommendedAction=action,
            sourcePhase="S3.5",
        ))

    bp_meta = blueprint.get("templateMeta") or {}
    ast_meta = (skeleton or {}).get("metadata") or {}
    bp_tid = bp_meta.get("templateId")
    ast_tid = ast_meta.get("templateId")
    if bp_tid and ast_tid and bp_tid != ast_tid:
        _block(
            "TEMPLATE_ID_MISMATCH",
            f"template.ast metadata.templateId '{ast_tid}' differs from template.blueprint templateId '{bp_tid}'",
            path="metadata.templateId",
            action="Emit one stable templateId across AST, blueprint, slot graph, and package",
        )

    enterprise_required = (
        "officerCustomization", "dataContract", "binderDeliverableContract",
        "publicationContract", "formulaCatalog", "qualityGateProfile", "officerWorkbench",
    )
    missing_contracts = [key for key in enterprise_required if not blueprint.get(key)]
    if enterprise_mode and missing_contracts:
        _block(
            "ENTERPRISE_CONTRACTS_MISSING",
            f"Blueprint is missing enterprise contract block(s): {', '.join(missing_contracts)}",
            path="template.blueprint",
            action="Run deterministic enterprise blueprint enrichment before S3.5 diagnostics",
        )

    entities = blueprint.get("entities") or []
    evidence_required = [e for e in entities if e.get("entityType") in ("measure", "dimension", "time")]
    if enterprise_mode:
        missing_source_refs = [
            e.get("entityId") or e.get("canonicalName")
            for e in evidence_required
            if not e.get("sourceRefs") or not e.get("evidence")
        ]
    else:
        missing_source_refs = [
            e.get("entityId") or e.get("canonicalName")
            for e in evidence_required
            if not e.get("sourceRefs") and not e.get("evidence")
        ]
    if missing_source_refs:
        _block(
            "ENTITY_MISSING_SOURCE_REFS",
            f"{len(missing_source_refs)} binder entities lack sourceRefs/evidence",
            path="entities[].sourceRefs",
            action="Thread LayoutLM/pdfplumber/VLM evidence refs into every binder entity",
        )

    semantic_graph = blueprint.get("templateSemanticGraph") or {}
    if semantic_graph:
        sg_diag = semantic_graph.get("diagnostics") or {}
        if sg_diag.get("entityCount", 0) and not sg_diag.get("evidenceCount", 0):
            _block(
                "SEMANTIC_GRAPH_WITHOUT_EVIDENCE",
                "templateSemanticGraph has entities but no evidenceIndex",
                path="templateSemanticGraph.evidenceIndex",
                action="Build evidenceIndex from sourceRefs before Pass 3/4",
            )
        missing_graph_refs = [
            e.get("entityId") or e.get("name") or i
            for i, e in enumerate(semantic_graph.get("entities") or [])
            if isinstance(e, dict)
            and (e.get("entityType") or e.get("entityType_hint")) in ("measure", "dimension", "time")
            and not (e.get("evidenceRefs") or e.get("sourceRefs"))
        ]
        if missing_graph_refs:
            _block(
                "SEMANTIC_GRAPH_ENTITY_EVIDENCE_GAP",
                f"{len(missing_graph_refs)} semantic graph entit(ies) lack evidenceRefs/sourceRefs",
                path="templateSemanticGraph.entities[].evidenceRefs",
                action="Preserve sourceRefs in Pass 2.5/2.7 and index every binder-relevant graph entity",
            )

    bad_questions: list[str] = []
    missing_enterprise_question_fields: list[str] = []
    missing_provenance_components: list[str] = []
    for q in _iter_questions(blueprint):
        if _question_requires_measure(q) and (not _has_measure_spec(q) or not _has_required_measure(q)):
            bad_questions.append(q.get("questionId") or q.get("intent") or "<unknown>")
        qid = q.get("questionId") or q.get("intent") or "<unknown>"
        required_q_fields = (
            "questionText", "formulaSpec", "binderContract", "qualityGates",
            "provenanceRequirements", "customization", "answerPlan",
        )
        if any(not q.get(field) for field in required_q_fields):
            missing_enterprise_question_fields.append(str(qid))
        components = ((q.get("answerStructure") or {}).get("components") or []) if isinstance(q.get("answerStructure"), dict) else []
        has_provenance = any(
            isinstance(c, dict)
            and str(c.get("kind") or c.get("componentKind") or c.get("type") or "").lower() in ("provenance", "source_note", "evidence")
            for c in components
        )
        if not has_provenance:
            missing_provenance_components.append(str(qid))
    if bad_questions:
        _block(
            "ANALYTIC_QUESTION_NOT_EXECUTABLE",
            f"{len(bad_questions)} analytic question(s) lack executable measure spec or required measure entity",
            path="topics[].questions[]",
            action="Drop or repair questions before S3.5; S4 must not infer the measure",
        )
    if enterprise_mode and missing_enterprise_question_fields:
        _block(
            "QUESTION_ENTERPRISE_FIELDS_MISSING",
            f"{len(missing_enterprise_question_fields)} question(s) are missing enterprise binder fields",
            path="topics[].questions[]",
            action="Run question enrichment before S3.5 diagnostics",
        )
    if enterprise_mode and missing_provenance_components:
        _block(
            "QUESTION_PROVENANCE_COMPONENT_MISSING",
            f"{len(missing_provenance_components)} question(s) lack a provenance component",
            path="topics[].questions[].answerStructure.components",
            action="Add a mandatory provenance component to every question",
        )

    if enterprise_mode and skeleton:
        missing_ast = [
            key for key in ("customizationAST", "publicationAST", "officerGuideAST")
            if not skeleton.get(key)
        ]
        if missing_ast:
            _block(
                "ENTERPRISE_AST_OVERLAYS_MISSING",
                f"template.ast is missing enterprise AST overlay(s): {', '.join(missing_ast)}",
                path="template.ast",
                action="Run enterprise AST enrichment before package emission",
            )

    chart_groups = blueprint.get("chartPanelGroups") or []
    empty_chart_measures = [
        g.get("groupId") or g.get("chartId") or i
        for i, g in enumerate(chart_groups)
        if isinstance(g, dict) and not (g.get("measureEntityId") or g.get("measureRefs") or g.get("measureRef"))
    ]
    if empty_chart_measures:
        _block(
            "CHART_GROUP_MISSING_MEASURE",
            f"{len(empty_chart_measures)} chart panel group(s) have no measureEntityId/measureRefs",
            path="chartPanelGroups[].measureEntityId",
            action="Bind chart semantics to measure entities before emitting chart slots",
        )
    unbound_chart_panels = [
        c.get("chartId") or c.get("id") or i
        for i, c in enumerate(((skeleton or {}).get("chartAST") or {}).get("charts") or [])
        if isinstance(c, dict) and not (c.get("measureEntityId") or c.get("measureRefs") or c.get("measureRef"))
    ]
    if unbound_chart_panels:
        diag.warnings.append(DiagnosticIssue(
            severity="warn",
            code="UNBOUND_CHART_PANELS",
            message=f"{len(unbound_chart_panels)} chart panel(s) are renderable but not binder-grouped because no measure entity was resolved",
            path="chartAST.charts[].measureEntityId",
            recommendedAction="Bind chart panels to measure entities or keep them as ungrouped render-only panels",
            sourcePhase="S3.5",
        ))

    if diag.categoryScores.get("crossReferenceIntegrity", 1.0) < 0.8:
        _block(
            "LOW_CROSS_REFERENCE_INTEGRITY",
            "semantic slot graph cross-reference integrity is below the S3.5 threshold",
            path="semantic_slot_graph",
            action="Repair slot fillFrom/biQuery/component references before binding",
        )

    if runtime_trace:
        status_counts = runtime_trace.get("statusCounts") or {}
        if status_counts.get("failed"):
            diag.warnings.append(DiagnosticIssue(
                severity="warn",
                code="PROVIDER_CALL_FAILURES",
                message=f"{status_counts.get('failed')} provider call(s) failed and required deterministic fallback",
                sourcePhase="S3.5",
            ))
        required = int(runtime_trace.get("schemaRequiredCalls") or 0)
        enforced = int(runtime_trace.get("schemaEnforcedCalls") or 0)
        if required and enforced < required:
            diag.warnings.append(DiagnosticIssue(
                severity="warn",
                code="SCHEMA_NOT_API_ENFORCED",
                message=f"{required - enforced} schema-required provider call(s) were prompt-validated but not API-enforced",
                sourcePhase="S3.5",
            ))


# ─────────────────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────────────────


def build_extraction_diagnostics(
    blueprint: dict[str, Any] | None = None,
    skeleton: dict[str, Any] | None = None,
    contract_result: Any = None,
    value_free_result: Any = None,
    hygiene_result: Any = None,
    normalization_result: Any = None,
    table_result: Any = None,
    statistical_context: Any = None,
    enrichment_result: Any = None,
    chart_result: Any = None,
    question_result: Any = None,
    wiring_result: Any = None,
    runtime_config: Any = None,
    runtime_trace: dict[str, Any] | None = None,
    checkpoint_summary: dict[str, Any] | None = None,
) -> ExtractionDiagnostics:
    """Build complete extraction diagnostics from all phase results.

    All parameters are optional — scores default to 0.5 for missing phases.
    """
    diag = ExtractionDiagnostics()
    diag.generatedAt = datetime.now(timezone.utc).isoformat()

    # ── Document type ──
    _doc_type = ""
    if blueprint:
        _meta = blueprint.get("templateMeta") or {}
        _doc_type = _meta.get("reportType") or ""
        # Infer PIB from domain if reportType not set
        if not _doc_type and _meta.get("domain") == "labour_force":
            _doc_type = "pib_press_release"
        # Infer from title
        if not _doc_type:
            _title = (_meta.get("name") or "").lower()
            if "plfs" in _title or "labour force" in _title or "press" in _title:
                _doc_type = "pib_press_release"

    # ── Category scores ──
    entities = None
    if enrichment_result and hasattr(enrichment_result, "entities"):
        entities = enrichment_result.entities
    elif normalization_result and hasattr(normalization_result, "entities"):
        entities = normalization_result.entities

    diag.categoryScores = {
        "entityHygiene": score_entity_hygiene(hygiene_result),
        "entityCompleteness": score_entity_completeness(entities),
        "tableSemantics": score_table_semantics(table_result),
        "unitCoverage": score_unit_coverage(entities, statistical_context),
        "questionCompleteness": score_question_completeness(question_result),
        "crossReferenceIntegrity": score_cross_reference_integrity(wiring_result),
        "valueFreeCompliance": score_value_free(value_free_result),
        "chartSemantics": score_chart_semantics(chart_result),
    }

    if _doc_type == "pib_press_release" and not table_result:
        # PIB press releases can be chart/text-only. Absence of data tables should
        # not depress the displayed score or trigger fix_tables recommendations.
        diag.categoryScores["tableSemantics"] = 1.0

    # ── Binder readiness ──
    diag.binderReadinessScore = compute_binder_readiness(diag.categoryScores, doc_type=_doc_type)

    # ── Blocking errors ──
    if value_free_result and hasattr(value_free_result, "leakages"):
        for leak in value_free_result.leakages:
            if (leak.severity if hasattr(leak, "severity") else "error") == "error":
                diag.blockingErrors.append(DiagnosticIssue(
                    severity="error", code=leak.code if hasattr(leak, "code") else "VALUE_LEAKAGE",
                    message=leak.message if hasattr(leak, "message") else str(leak),
                    sourcePhase="E12",
                ))

    if contract_result and hasattr(contract_result, "errors"):
        for err in contract_result.errors:
            diag.blockingErrors.append(DiagnosticIssue(
                severity="error", code=err.code if hasattr(err, "code") else "CONTRACT_ERROR",
                message=err.message if hasattr(err, "message") else str(err),
                sourcePhase="E0",
            ))

    # Cross-reference (slot wiring) errors — e.g. BROKEN_FILLFROM — are binder
    # blockers and must surface as blocking errors on the diagnostics.
    if wiring_result is not None and hasattr(wiring_result, "issues"):
        for issue in wiring_result.issues:
            severity = issue.severity if hasattr(issue, "severity") else (issue.get("severity", "") if isinstance(issue, dict) else "")
            if severity != "error":
                continue
            diag.blockingErrors.append(DiagnosticIssue(
                severity="error",
                code=issue.code if hasattr(issue, "code") else issue.get("code", "WIRING_ERROR"),
                message=issue.message if hasattr(issue, "message") else issue.get("message", str(issue)),
                sourcePhase="E8",
            ))

    # ── Warnings from contract ──
    if contract_result and hasattr(contract_result, "warnings"):
        for w in contract_result.warnings:
            diag.warnings.append(DiagnosticIssue(
                severity="warn", code=w.code if hasattr(w, "code") else "CONTRACT_WARN",
                message=w.message if hasattr(w, "message") else str(w),
                sourcePhase="E0",
            ))

    # ── Quarantined items ──
    if hygiene_result and hasattr(hygiene_result, "quarantine"):
        for q in hygiene_result.quarantine:
            diag.quarantinedItems.append(q.to_dict() if hasattr(q, "to_dict") else {"text": str(q)})

    # ── Repairs ──
    if wiring_result and hasattr(wiring_result, "repairs"):
        for r in wiring_result.repairs:
            diag.repairsApplied.append(r.to_dict() if hasattr(r, "to_dict") else {"repair": str(r)})

    # ── Counts ──
    c = diag.counts
    if entities:
        c.entities = len(entities)
    if hygiene_result:
        h_diag = hygiene_result.diagnostics if hasattr(hygiene_result, "diagnostics") else {}
        c.entitiesDropped = h_diag.get("quarantineCount", 0)
        c.topics = h_diag.get("topicCount", 0)
    if normalization_result:
        n_diag = normalization_result.diagnostics if hasattr(normalization_result, "diagnostics") else {}
        c.measureFamilies = n_diag.get("measureFamilies", 0)
    if question_result:
        q_counts = question_result.counts if hasattr(question_result, "counts") else {}
        c.questions = q_counts.get("kept", 0)
        c.questionsFromTemplates = q_counts.get("tablePatterns", 0) + q_counts.get("chartPatterns", 0)
        c.questionsDropped = q_counts.get("dropped", 0)
    if table_result:
        t_counts = table_result.counts if hasattr(table_result, "counts") else {}
        c.tables = t_counts.get("real", 0)
        c.tablesGhost = t_counts.get("ghost", 0)
    if chart_result:
        ch_counts = chart_result.counts if hasattr(chart_result, "counts") else {}
        c.charts = ch_counts.get("compiled", 0)
        c.figures = ch_counts.get("compiled", 0)
    if wiring_result:
        w_counts = wiring_result.counts if hasattr(wiring_result, "counts") else {}
        c.slotsWired = w_counts.get("crosswalkComponents", 0)

    # ── S3.5 binder-executability gate ──
    # Applies binder blockers (broken refs, non-executable questions, missing
    # measure evidence) to every package, plus enterprise-shape blockers when the
    # blueprint opts in. Legacy/gold packages are not forced INVALID for lacking
    # enterprise structure.
    if blueprint:
        apply_s35_emission_gate(diag, blueprint=blueprint, skeleton=skeleton, runtime_trace=runtime_trace)

    # ── Status ──
    if diag.blockingErrors:
        diag.binderReadinessScore = min(diag.binderReadinessScore, 0.59)
    diag.status = determine_status(diag.binderReadinessScore, diag.blockingErrors)

    # ── Binder compatibility ──
    diag.binderCompatibility = predict_binder_compatibility(diag.categoryScores, contract_result, value_free_result, doc_type=_doc_type)
    if diag.blockingErrors:
        diag.binderCompatibility.blueprintQAWillPass = False
        diag.binderCompatibility.recommendation = "invalid"
        if "S3.5 emission gate blocked template generation" not in diag.binderCompatibility.expectedIssues:
            diag.binderCompatibility.expectedIssues.append("S3.5 emission gate blocked template generation")

    # ── Runtime summary ──
    if runtime_config:
        if hasattr(runtime_config, "to_dict"):
            diag.runtime = {"modelProfile": runtime_config.modelProfile, "enrichment": "enabled" if runtime_config.enrichmentEnabled else "disabled"}
        elif isinstance(runtime_config, dict):
            diag.runtime = runtime_config
    if checkpoint_summary:
        diag.runtime.setdefault("cache", checkpoint_summary)

    # ── Crosswalk ──
    if wiring_result and hasattr(wiring_result, "crosswalk"):
        diag.crosswalk = wiring_result.crosswalk

    return diag


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


def _has_domain(entity: Any) -> bool:
    vd = _get(entity, "valueDomain")
    if not vd:
        return False
    if isinstance(vd, dict):
        return vd.get("kind") and vd.get("kind") != "open"
    return False


def _has_spec(q: Any) -> bool:
    spec = _get(q, "analyticsSpec")
    if not spec:
        return False
    if isinstance(spec, dict):
        return bool(spec.get("operation"))
    return False


def _has_structure(q: Any) -> bool:
    ans = _get(q, "answerStructure")
    if not ans:
        return False
    if isinstance(ans, dict):
        return bool(ans.get("components"))
    return False
