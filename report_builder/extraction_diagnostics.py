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

    # ── Status ──
    diag.status = determine_status(diag.binderReadinessScore, diag.blockingErrors)

    # ── Binder compatibility ──
    diag.binderCompatibility = predict_binder_compatibility(diag.categoryScores, contract_result, value_free_result, doc_type=_doc_type)

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
