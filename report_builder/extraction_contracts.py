"""E0 — Extraction Contract + Schema Versioning.

Defines the formal contract layer for the MoSPI Template Compiler.
This is the compile target: every extraction phase must produce output
that passes this contract before template files are emitted.

The contract validates blueprint structure, entity quality, question
completeness, and cross-reference integrity WITHOUT modifying extraction
behavior. It is a validator, not a transformer.

Usage:
    from report_builder.extraction_contracts import validate_extraction_contract
    result = validate_extraction_contract(blueprint_dict, mode=ExtractionMode.STRICT)
    if result.has_errors:
        raise ExtractionContractError(result)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Contract version
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_CONTRACT_VERSION = "template.extraction.v2"
BINDER_MIN_BLUEPRINT_VERSION = "bharatstat/template-blueprint/v1"

# ─────────────────────────────────────────────────────────────────────────────
# Compatibility modes
# ─────────────────────────────────────────────────────────────────────────────


class ExtractionMode(Enum):
    STRICT = "strict"    # Production: structural failures are errors
    WARN = "warn"        # Development: failures become warnings where safe
    LEGACY = "legacy"    # Old outputs tolerated with backfill defaults


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DiagnosticIssue:
    """One contract validation issue."""
    severity: str = "warn"              # error | warn | info
    code: str = ""
    message: str = ""
    path: str = ""                      # JSON path to the offending field
    recommendedAction: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path:
            d["path"] = self.path
        if self.recommendedAction:
            d["recommendedAction"] = self.recommendedAction
        return d


@dataclass
class ExtractionValidationResult:
    """Result of contract validation."""
    status: str = "VALID"               # VALID | VALID_WITH_WARNINGS | INVALID
    mode: str = "strict"
    errors: list[DiagnosticIssue] = field(default_factory=list)
    warnings: list[DiagnosticIssue] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    contractVersion: str = EXTRACTION_CONTRACT_VERSION

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "contractVersion": self.contractVersion,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "scores": dict(self.scores),
            "errorCount": len(self.errors),
            "warningCount": len(self.warnings),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Pass contracts
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ExtractionPassContract:
    """Declares runtime/cache/model behavior for one extraction pass."""
    passName: str = ""
    deterministic: bool = True
    modelTask: str | None = None
    cacheable: bool = True
    requiresVision: bool = False
    fallbackAllowed: bool = True
    valueLeakageRisk: str = "none"      # none | low | medium | high

    def to_dict(self) -> dict[str, Any]:
        return {
            "passName": self.passName,
            "deterministic": self.deterministic,
            "modelTask": self.modelTask,
            "cacheable": self.cacheable,
            "requiresVision": self.requiresVision,
            "fallbackAllowed": self.fallbackAllowed,
            "valueLeakageRisk": self.valueLeakageRisk,
        }


def default_pass_contracts() -> list[ExtractionPassContract]:
    """Return pass contracts for all extraction passes."""
    return [
        ExtractionPassContract(
            passName="pass0_text_tables",
            deterministic=True,
            modelTask=None,
            cacheable=True,
            requiresVision=False,
            valueLeakageRisk="none",
        ),
        ExtractionPassContract(
            passName="pass1_layout",
            deterministic=False,
            modelTask=None,
            cacheable=True,
            requiresVision=False,
            fallbackAllowed=True,
            valueLeakageRisk="none",
        ),
        ExtractionPassContract(
            passName="pass2_vlm_entities",
            deterministic=False,
            modelTask="entity_extraction",
            cacheable=True,
            requiresVision=True,
            fallbackAllowed=True,
            valueLeakageRisk="medium",
        ),
        ExtractionPassContract(
            passName="pass2_5_semantic_graph",
            deterministic=True,
            modelTask=None,
            cacheable=True,
            requiresVision=False,
            valueLeakageRisk="low",
        ),
        ExtractionPassContract(
            passName="pass3_questions",
            deterministic=False,
            modelTask="question_generation",
            cacheable=True,
            requiresVision=True,
            fallbackAllowed=True,
            valueLeakageRisk="low",
        ),
        ExtractionPassContract(
            passName="pass4_assembly",
            deterministic=True,
            modelTask=None,
            cacheable=True,
            requiresVision=False,
            valueLeakageRisk="none",
        ),
        ExtractionPassContract(
            passName="pass4_5_validation",
            deterministic=True,
            modelTask=None,
            cacheable=False,
            requiresVision=False,
            valueLeakageRisk="none",
        ),
        ExtractionPassContract(
            passName="pass5_optional_enrichment",
            deterministic=False,
            modelTask="semantic_enrichment",
            cacheable=False,
            requiresVision=False,
            fallbackAllowed=True,
            valueLeakageRisk="low",
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Source and runtime trace references
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SourceRef:
    """Where an entity/signal was found in the source document."""
    sourceType: str = ""                # table_header | chart_axis | vlm_entity | heading | caption
    tableId: str | None = None
    figureId: str | None = None
    regionRef: str | None = None
    page: int | None = None
    bbox: list[float] = field(default_factory=list)
    headerPath: list[str] = field(default_factory=list)
    physicalColumn: str | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"sourceType": self.sourceType}
        if self.tableId:
            d["tableId"] = self.tableId
        if self.figureId:
            d["figureId"] = self.figureId
        if self.regionRef:
            d["regionRef"] = self.regionRef
        if self.page is not None:
            d["page"] = self.page
        if self.bbox:
            d["bbox"] = list(self.bbox)
        if self.headerPath:
            d["headerPath"] = list(self.headerPath)
        if self.physicalColumn:
            d["physicalColumn"] = self.physicalColumn
        if self.confidence is not None:
            d["confidence"] = self.confidence
        return d


@dataclass
class RuntimeTraceRef:
    """Lightweight reference to a model call trace (for TemplateSemanticGraph).
    
    Full call ledger (R7) will populate these; for now they're structural placeholders.
    """
    traceId: str = ""
    task: str = ""
    provider: str | None = None
    model: str | None = None
    cacheHit: bool | None = None
    fallbackUsed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"traceId": self.traceId, "task": self.task}
        if self.provider:
            d["provider"] = self.provider
        if self.model:
            d["model"] = self.model
        if self.cacheHit is not None:
            d["cacheHit"] = self.cacheHit
        if self.fallbackUsed is not None:
            d["fallbackUsed"] = self.fallbackUsed
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Entity contract
# ─────────────────────────────────────────────────────────────────────────────

VALID_ENTITY_TYPES = frozenset({"measure", "dimension", "time", "filter", "metadata"})
VALID_SCOPES = frozenset({"indicator", "classifier", "geography", "temporal", "structural"})


@dataclass
class ExtractionEntityContract:
    """The full entity shape extraction must produce for binder readiness."""
    entityId: str = ""
    canonicalName: str = ""
    entityType: str = ""
    aliases: list[str] = field(default_factory=list)
    unit: str | None = None
    format: str | None = None
    valueDomain: dict[str, Any] = field(default_factory=dict)
    aggregation: str | None = None
    scope: str = "indicator"
    cardinalityHint: str = ""
    sourceRefs: list[dict[str, Any]] = field(default_factory=list)
    roleEvidence: list[dict[str, Any]] = field(default_factory=list)
    riskFlags: list[dict[str, Any]] = field(default_factory=list)
    familyRef: str | None = None
    normalizationHints: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    runtimeTraceRefs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entityId": self.entityId,
            "canonicalName": self.canonicalName,
            "entityType": self.entityType,
            "aliases": list(self.aliases),
            "unit": self.unit,
            "format": self.format,
            "valueDomain": dict(self.valueDomain),
            "aggregation": self.aggregation,
            "scope": self.scope,
            "cardinalityHint": self.cardinalityHint,
            "sourceRefs": list(self.sourceRefs),
            "roleEvidence": list(self.roleEvidence),
            "riskFlags": list(self.riskFlags),
            "familyRef": self.familyRef,
            "normalizationHints": dict(self.normalizationHints),
            "confidence": self.confidence,
            "runtimeTraceRefs": list(self.runtimeTraceRefs),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Question contract
# ─────────────────────────────────────────────────────────────────────────────

VALID_QUESTION_TYPES = frozenset({
    "comparison", "trend", "composition", "ranking", "summary", "descriptive",
})


@dataclass
class ExtractionQuestionContract:
    """Every question must be compilable to QuestionExecutionPlan."""
    questionId: str = ""
    intent: str = ""
    questionType: str = ""
    requiredEntities: list[dict[str, Any]] = field(default_factory=list)
    analyticsSpec: dict[str, Any] = field(default_factory=dict)
    answerStructure: dict[str, Any] = field(default_factory=dict)
    sourceTable: str | None = None
    generationMethod: str = ""          # table_pattern | llm | manual
    priority: int = 3
    formulaIntent: dict[str, Any] | None = None
    runtimeTraceRefs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "questionId": self.questionId,
            "intent": self.intent,
            "questionType": self.questionType,
            "requiredEntities": list(self.requiredEntities),
            "analyticsSpec": dict(self.analyticsSpec),
            "answerStructure": dict(self.answerStructure),
            "sourceTable": self.sourceTable,
            "generationMethod": self.generationMethod,
            "priority": self.priority,
            "formulaIntent": self.formulaIntent,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Blueprint contract
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ExtractionBlueprintContract:
    """The complete template.blueprint.json shape."""
    schema: str = BINDER_MIN_BLUEPRINT_VERSION
    contractVersion: str = EXTRACTION_CONTRACT_VERSION
    templateMeta: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    measureFamilies: list[dict[str, Any]] = field(default_factory=list)
    topics: list[dict[str, Any]] = field(default_factory=list)
    tableTemplates: list[dict[str, Any]] = field(default_factory=list)
    figureTemplates: list[dict[str, Any]] = field(default_factory=list)
    glossary: dict[str, Any] = field(default_factory=dict)
    palette: dict[str, Any] = field(default_factory=dict)
    renderProfile: dict[str, Any] = field(default_factory=dict)
    documentMap: dict[str, Any] = field(default_factory=dict)
    templateSemanticGraph: dict[str, Any] = field(default_factory=dict)
    statisticalContext: dict[str, Any] = field(default_factory=dict)
    extractionDiagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": self.schema,
            "contractVersion": self.contractVersion,
            "templateMeta": self.templateMeta,
            "entities": self.entities,
            "measureFamilies": self.measureFamilies,
            "topics": self.topics,
            "tableTemplates": self.tableTemplates,
            "figureTemplates": self.figureTemplates,
            "glossary": self.glossary,
            "palette": self.palette,
            "renderProfile": self.renderProfile,
            "documentMap": self.documentMap,
            "templateSemanticGraph": self.templateSemanticGraph,
            "statisticalContext": self.statisticalContext,
            "extractionDiagnostics": self.extractionDiagnostics,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────

_SEQUENTIAL_ID_RE = re.compile(r'^ent_\d{2,}$')


def blueprint_entity_ids(blueprint: dict[str, Any]) -> set[str]:
    """Return set of all entity IDs in a blueprint."""
    ids: set[str] = set()
    for ent in (blueprint.get("entities") or []):
        eid = ent.get("entityId") or ""
        if eid:
            ids.add(eid)
    return ids


def iter_blueprint_questions(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten topics[].questions[] and top-level questions[]."""
    questions: list[dict[str, Any]] = []
    for topic in (blueprint.get("topics") or []):
        questions.extend(topic.get("questions") or [])
    questions.extend(blueprint.get("questions") or [])
    return questions


def _question_requires_measure(question: dict[str, Any]) -> bool:
    qtype = str(question.get("questionType") or "")
    spec = question.get("analyticsSpec") or {}
    operation = str(spec.get("operation") or "").lower() if isinstance(spec, dict) else ""
    if qtype in ("descriptive", "summary"):
        return False
    if operation in ("describe", "summary", "summary_stats"):
        return False
    return True


def _has_measure_spec(question: dict[str, Any]) -> bool:
    spec = question.get("analyticsSpec") or {}
    if not isinstance(spec, dict):
        return False
    measure = spec.get("measure")
    if _has_measure_ref(measure):
        return True
    measures = spec.get("measures")
    if isinstance(measures, list):
        return any(_has_measure_ref(m) for m in measures)
    return _has_measure_ref(measures)


def _has_measure_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("entityRef") or value.get("entityId") or value.get("column"))
    return bool(value)


def _has_required_measure(question: dict[str, Any]) -> bool:
    for req in question.get("requiredEntities") or []:
        if req.get("role") == "measure" and (req.get("entityId") or req.get("entityRef")):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Main validator
# ─────────────────────────────────────────────────────────────────────────────


def validate_extraction_contract(
    blueprint: dict[str, Any],
    mode: ExtractionMode = ExtractionMode.STRICT,
) -> ExtractionValidationResult:
    """Validate a blueprint dict against the extraction contract.

    Args:
        blueprint: The template.blueprint.json dict to validate.
        mode: Validation strictness (STRICT/WARN/LEGACY).

    Returns:
        ExtractionValidationResult with status, errors, warnings, and scores.
    """
    result = ExtractionValidationResult(mode=mode.value)
    entities = blueprint.get("entities") or []
    entity_ids = blueprint_entity_ids(blueprint)
    questions = iter_blueprint_questions(blueprint)
    template_meta = blueprint.get("templateMeta") or {}

    # Helper to add issue with mode-aware severity
    def _issue(code: str, message: str, path: str = "", action: str = "", force_error: bool = False):
        if force_error or mode == ExtractionMode.STRICT:
            result.errors.append(DiagnosticIssue(
                severity="error", code=code, message=message,
                path=path, recommendedAction=action,
            ))
        else:
            result.warnings.append(DiagnosticIssue(
                severity="warn", code=code, message=message,
                path=path, recommendedAction=action,
            ))

    def _warn(code: str, message: str, path: str = "", action: str = ""):
        result.warnings.append(DiagnosticIssue(
            severity="warn", code=code, message=message,
            path=path, recommendedAction=action,
        ))

    # ── 1. Schema ──
    schema = blueprint.get("$schema") or ""
    if not schema and mode == ExtractionMode.STRICT:
        _warn("MISSING_SCHEMA", "No $schema field in blueprint", path="$schema")

    # ── 2. Template metadata ──
    if not template_meta:
        _issue("MISSING_TEMPLATE_META", "templateMeta is required", path="templateMeta",
               action="Add templateMeta with templateId, name, domain")
    else:
        if not template_meta.get("templateId"):
            _warn("MISSING_TEMPLATE_ID", "templateMeta.templateId is empty", path="templateMeta.templateId")
        if template_meta.get("name") in ("Document", "", None):
            _warn("GENERIC_TEMPLATE_NAME", "templateMeta.name is generic — should identify the report",
                  path="templateMeta.name", action="Set specific report name")
        if template_meta.get("domain") in ("general", "", None):
            _warn("GENERIC_DOMAIN", "templateMeta.domain is 'general' — should be specific (energy, labour_force, etc.)",
                  path="templateMeta.domain", action="Set domain from document content")

    # ── 3. Entities ──
    if not entities:
        _issue("NO_ENTITIES", "Blueprint has zero entities", path="entities",
               action="Extraction must produce at least core entities", force_error=True)
    else:
        measures_without_unit = 0
        entities_without_aliases = 0
        sequential_ids = 0
        invalid_types = 0
        domain_type_drift = 0

        for i, ent in enumerate(entities):
            eid = ent.get("entityId") or ""
            ename = ent.get("canonicalName") or ""
            etype = ent.get("entityType") or ""
            aliases = ent.get("aliases") or []
            unit = ent.get("unit")
            vd = ent.get("valueDomain") or {}

            if not eid:
                _issue("ENTITY_MISSING_ID", f"Entity at index {i} has no entityId",
                       path=f"entities[{i}].entityId", force_error=True)
            elif _SEQUENTIAL_ID_RE.match(eid):
                sequential_ids += 1

            if not ename:
                _issue("ENTITY_MISSING_NAME", f"Entity '{eid}' has no canonicalName",
                       path=f"entities[{i}].canonicalName", force_error=True)

            if etype and etype not in VALID_ENTITY_TYPES:
                invalid_types += 1

            if etype == "measure" and not unit:
                measures_without_unit += 1

            if etype in ("measure", "dimension") and not aliases:
                entities_without_aliases += 1

            # valueDomain schema drift: old outputs use "domainType" instead of "kind"
            if "domainType" in vd and "kind" not in vd:
                domain_type_drift += 1

        if sequential_ids > 0:
            _issue("SEQUENTIAL_ENTITY_IDS",
                   f"{sequential_ids} entities use sequential numeric IDs (ent_0XX) — should be semantic",
                   path="entities[].entityId",
                   action="Use semantic IDs: ent_proved_reserves, ent_state_ut, etc.")

        if measures_without_unit > 0:
            _warn("MEASURES_MISSING_UNIT",
                  f"{measures_without_unit} measure entities have no unit",
                  path="entities[].unit",
                  action="Infer unit from table title or header context")

        if entities_without_aliases > 0:
            _warn("ENTITIES_MISSING_ALIASES",
                  f"{entities_without_aliases} measure/dimension entities have empty aliases",
                  path="entities[].aliases",
                  action="Generate aliases from name variants and table headers")

        if invalid_types > 0:
            _warn("INVALID_ENTITY_TYPES",
                  f"{invalid_types} entities have non-standard entityType",
                  path="entities[].entityType")

        if domain_type_drift > 0:
            _warn("VALUEDOMAIN_SCHEMA_DRIFT",
                  f"{domain_type_drift} entities use 'domainType' instead of 'kind' in valueDomain",
                  path="entities[].valueDomain",
                  action="Use valueDomain.kind (ratio|categorical|ordinal|count)")

    # ── 4. Topics and questions ──
    topics = blueprint.get("topics") or []
    if not topics and not blueprint.get("questions"):
        _issue("NO_TOPICS_OR_QUESTIONS", "Blueprint has no topics or questions",
               path="topics", action="Generate questions from table semantics", force_error=True)

    if not questions:
        _issue("NO_QUESTIONS", "Blueprint has zero questions",
               path="topics[].questions", force_error=True)
    else:
        missing_analytics = 0
        missing_answer_structure = 0
        missing_components = 0
        missing_measure_spec = 0
        missing_measure_entity = 0
        broken_entity_refs = 0
        weak_intents = 0

        for q in questions:
            qid = q.get("questionId") or ""
            intent = q.get("intent") or q.get("questionText") or ""
            qtype = q.get("questionType") or ""
            req_ents = q.get("requiredEntities") or []
            aspec = q.get("analyticsSpec") or {}
            ans = q.get("answerStructure") or q.get("outputContract") or {}
            components = ans.get("components") or [] if isinstance(ans, dict) else []

            # Check entity refs
            for req in req_ents:
                ref_id = req.get("entityId") or req.get("entityRef") or ""
                if ref_id and ref_id not in entity_ids:
                    broken_entity_refs += 1

            # Non-descriptive questions need analyticsSpec
            if qtype not in ("descriptive", "summary", ""):
                if not aspec.get("operation"):
                    missing_analytics += 1
                if _question_requires_measure(q):
                    if not _has_measure_spec(q):
                        missing_measure_spec += 1
                    if not _has_required_measure(q):
                        missing_measure_entity += 1

            # Answer structure
            if not ans:
                missing_answer_structure += 1
            elif not components:
                missing_components += 1

            # Intent quality
            if len(intent.split()) < 5:
                weak_intents += 1

        if broken_entity_refs > 0:
            _issue("BROKEN_ENTITY_REFS",
                   f"{broken_entity_refs} requiredEntities reference non-existent entity IDs",
                   path="topics[].questions[].requiredEntities[].entityId",
                   action="Ensure all entity refs point to entities in blueprint.entities[]",
                   force_error=True)

        if missing_analytics > 0:
            _issue("MISSING_ANALYTICS_SPEC",
                   f"{missing_analytics} non-descriptive questions have no analyticsSpec.operation",
                   path="topics[].questions[].analyticsSpec",
                   action="Add operation (group_aggregate, trend, etc.)")

        if missing_measure_spec > 0:
            _issue("MISSING_MEASURE_SPEC",
                   f"{missing_measure_spec} analytic questions have no executable analyticsSpec.measure/measures",
                   path="topics[].questions[].analyticsSpec.measure",
                   action="Add measure entity refs before binding")

        if missing_measure_entity > 0:
            _issue("MISSING_MEASURE_ENTITY",
                   f"{missing_measure_entity} analytic questions have no requiredEntities role='measure'",
                   path="topics[].questions[].requiredEntities",
                   action="Add the measure entity required by S3 binding")

        if missing_answer_structure > 0:
            _issue("MISSING_ANSWER_STRUCTURE",
                   f"{missing_answer_structure} questions have no answerStructure",
                   path="topics[].questions[].answerStructure")

        if missing_components > 0:
            _issue("MISSING_ANSWER_COMPONENTS",
                   f"{missing_components} questions have answerStructure but empty components[]",
                   path="topics[].questions[].answerStructure.components",
                   action="Add at least one component (narrative, table, or chart)")

        if weak_intents > 0:
            _warn("WEAK_QUESTION_INTENTS",
                  f"{weak_intents} questions have short/generic intent (< 5 words)",
                  path="topics[].questions[].intent",
                  action="Make intents specific and analytical")

    # ── 5. Table/figure templates ──
    table_templates = blueprint.get("tableTemplates") or blueprint.get("tableStructures") or []
    figure_templates = blueprint.get("figureTemplates") or []
    if not table_templates and questions:
        _warn("NO_TABLE_TEMPLATES", "No tableTemplates despite having questions",
              path="tableTemplates")

    # ── 6. Statistical context ──
    stat_ctx = blueprint.get("statisticalContext") or {}
    if not stat_ctx:
        _warn("MISSING_STATISTICAL_CONTEXT", "No statisticalContext in blueprint",
              path="statisticalContext",
              action="Add sourceDocument, domain, referenceDate from extraction")

    # ── 7. Glossary / palette / renderProfile ──
    if not blueprint.get("glossary"):
        _warn("MISSING_GLOSSARY", "No glossary in blueprint", path="glossary")

    # ── 8. Compute scores ──
    total_entities = len(entities)
    total_questions = len(questions)

    result.scores = {
        "entityCount": total_entities,
        "questionCount": total_questions,
        "tableTemplateCount": len(table_templates),
        "figureTemplateCount": len(figure_templates),
        "entityHygiene": 1.0 - (sequential_ids / max(total_entities, 1)) if entities else 0.0,
        "questionCompleteness": 1.0 - (missing_analytics / max(total_questions, 1)) if questions else 0.0,
        "answerStructureCompleteness": 1.0 - (missing_answer_structure / max(total_questions, 1)) if questions else 0.0,
        "crossReferenceIntegrity": 1.0 - (broken_entity_refs / max(total_questions * 2, 1)) if questions else 0.0,
    }

    # ── Determine status ──
    if result.errors:
        result.status = "INVALID"
    elif result.warnings:
        result.status = "VALID_WITH_WARNINGS"
    else:
        result.status = "VALID"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# JSON Schema export (basic)
# ─────────────────────────────────────────────────────────────────────────────


def export_json_schema() -> dict[str, Any]:
    """Return a basic JSON schema describing the blueprint contract.

    Not a full JSON Schema validator — a structural reference for documentation.
    """
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "BharatStat Template Blueprint",
        "description": "Value-free analytic brain for MoSPI template extraction",
        "version": EXTRACTION_CONTRACT_VERSION,
        "type": "object",
        "required": ["templateMeta", "entities", "topics"],
        "properties": {
            "$schema": {"type": "string", "const": BINDER_MIN_BLUEPRINT_VERSION},
            "contractVersion": {"type": "string"},
            "templateMeta": {
                "type": "object",
                "required": ["templateId", "name", "domain"],
                "properties": {
                    "templateId": {"type": "string"},
                    "name": {"type": "string"},
                    "domain": {"type": "string"},
                    "locale": {"type": "string"},
                    "version": {"type": "string"},
                    "valueFree": {"type": "boolean", "const": True},
                    "proseFree": {"type": "boolean", "const": True},
                    "sourceDocument": {"type": "string"},
                },
            },
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["entityId", "canonicalName", "entityType"],
                    "properties": {
                        "entityId": {"type": "string", "pattern": "^ent_[a-z_]+$"},
                        "canonicalName": {"type": "string"},
                        "entityType": {"type": "string", "enum": list(VALID_ENTITY_TYPES)},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "unit": {"type": ["string", "null"]},
                        "valueDomain": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["ratio", "categorical", "ordinal", "count"]},
                            },
                        },
                    },
                },
            },
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topicId": {"type": "string"},
                        "title": {"type": "string"},
                        "questions": {"type": "array"},
                    },
                },
            },
        },
    }
