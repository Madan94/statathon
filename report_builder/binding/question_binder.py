"""S3 — Question binder.

Resolves each blueprint **question** into concrete dataset columns grouped by
analytic role, producing a :class:`QuestionBinding`:

    resolvedRoles = { measures[], dimensions[], filters[], time }

Inputs:
    * blueprint ``questions`` — each with ``requiredEntities[{entityId, role,
      required, defaultMember?, periodRole?}]`` and an ``analyticsSpec``.
    * ``entity_bindings`` — the S1/S2 entity→column bindings (indexed by id).
    * ``dataset`` — the S0 :class:`DatasetAST` (for time columns + distinct values).
    * optional ``df`` — to read true distinct values for filter resolution
      (falls back to the profile's ``sampleValues`` when absent).

Status (decision-driven):
    * **blocked**  — a *required non-time* entity is unresolved (missing measure
      or grouping). Never silently dropped.
    * **degraded** — time required but no time column (→ snapshot, ``timeResolved
      =False``), OR a default-member filter could not be applied (→ widened,
      ``filterApplied=False``).
    * **executable** — everything resolved.

Time + periods are **human-verified**: when a time column exists, periods are
*proposed* from its distinct values but flagged for confirmation in S2.
Deterministic and offline.
"""
from __future__ import annotations

import logging
from typing import Any

from report_builder.binding.schema import (
    DatasetAST,
    EntityBinding,
    QuestionBinding,
    ResolvedFilter,
    ResolvedRoles,
    ResolvedTime,
)
from report_builder.binding.value_resolver import resolve_filter_value

logger = logging.getLogger(__name__)

_RESOLVED_STATUSES = ("proposed", "confirmed", "overridden")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _index_bindings(bindings: list[EntityBinding]) -> dict[str, EntityBinding]:
    """Index bindings for lookup by entityId *or* canonical entity name.

    Questions reference entities by id on the Gemini path
    (``requiredEntities[].entityId``) but by **name** on the programmatic-fallback
    path (``requiredEntities[].entityRef`` = the entity's display name). Indexing
    both shapes lets S3 resolve either; ids win over names on any collision.
    """
    idx: dict[str, EntityBinding] = {}
    for b in bindings:
        if b.entityName:
            idx.setdefault(b.entityName.strip().lower(), b)
    for b in bindings:  # second pass: entityId takes precedence over a name clash
        if b.entityId:
            idx[b.entityId] = b
    return idx


def _is_resolved(b: EntityBinding | None) -> bool:
    return b is not None and b.status in _RESOLVED_STATUSES and bool(b.columns)


def _distinct_values(
    column: str, dataset: DatasetAST, df: Any | None
) -> list[Any]:
    if df is not None and column in getattr(df, "columns", []):
        return [v for v in df[column].dropna().unique().tolist()]
    prof = dataset.column(column)
    return list(prof.sampleValues) if prof else []


def _filter_specs(analytics_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index analyticsSpec.filters by entityRef → {op, valueFrom}.

    Keyed by the raw ref and a lowercased alias so a filter declared by entity
    *name* still matches a requiredEntity declared by id (and vice versa).
    """
    out: dict[str, dict[str, Any]] = {}
    for f in (analytics_spec.get("filters") or []):
        ref = f.get("entityRef") or f.get("entityId")
        if ref:
            spec = {"op": f.get("op", "eq"), "valueFrom": f.get("valueFrom")}
            out[str(ref)] = spec
            out.setdefault(str(ref).strip().lower(), spec)
    return out


def _propose_periods(time_col_values: list[Any]) -> dict[str, Any]:
    """Propose {current, prior} from a time column's distinct values (human-verified)."""
    vals = sorted({str(v) for v in time_col_values})
    periods: dict[str, Any] = {}
    if vals:
        periods["current"] = vals[-1]
    if len(vals) >= 2:
        periods["prior"] = vals[-2]
    return periods


# ─────────────────────────────────────────────────────────────────────────────
# Per-question binding
# ─────────────────────────────────────────────────────────────────────────────


def bind_question(
    question: dict[str, Any],
    bindings_by_id: dict[str, EntityBinding],
    dataset: DatasetAST,
    *,
    df: Any | None = None,
) -> QuestionBinding:
    """Resolve one blueprint question into a :class:`QuestionBinding` (S3)."""
    qid = str(question.get("questionId") or "")
    required = question.get("requiredEntities") or []
    spec = question.get("analyticsSpec") or {}
    filter_specs = _filter_specs(spec)

    roles = ResolvedRoles()
    unresolved: list[str] = []
    notes: list[str] = []
    blocked = False
    degraded = False

    for req in required:
        ent_id = str(req.get("entityId") or req.get("entityRef") or "")
        role = str(req.get("role") or "")
        is_required = bool(req.get("required", True))
        # Resolve by entityId (Gemini path) or by display name (programmatic
        # fallback emits requiredEntities[].entityRef = the entity's name).
        binding = bindings_by_id.get(ent_id) or bindings_by_id.get(ent_id.strip().lower())
        resolved = _is_resolved(binding)

        # ---- time is special: missing → snapshot (degrade), not block ----
        if role == "time":
            if resolved and binding is not None:
                time_col = binding.column_names[0]
                periods = _propose_periods(_distinct_values(time_col, dataset, df))
                roles.time = ResolvedTime(column=time_col, periods=periods, timeResolved=True)
                notes.append(f"time periods proposed from '{time_col}' (confirm in review)")
            else:
                roles.time = ResolvedTime(column=None, periods={}, timeResolved=False)
                degraded = True
                notes.append("no time column — snapshot mode (timeResolved=false)")
                if is_required:
                    unresolved.append(ent_id)
            continue

        # ---- non-time roles ----
        if not resolved or binding is None:
            if is_required:
                unresolved.append(ent_id)
                blocked = True
                notes.append(f"required {role or 'entity'} '{ent_id}' unresolved")
            else:
                notes.append(f"optional {role or 'entity'} '{ent_id}' unresolved — skipped")
            continue

        cols = binding.column_names
        if binding.cardinality != "oneToOne":
            notes.append(
                f"'{ent_id}' is {binding.cardinality} ({len(cols)} cols) — reshape at execution"
            )

        if role == "measure":
            roles.measures.extend(c for c in cols if c not in roles.measures)
        elif role == "grouping":
            roles.dimensions.extend(c for c in cols if c not in roles.dimensions)
        elif role == "filter":
            fspec = (
                filter_specs.get(ent_id)
                or filter_specs.get(ent_id.strip().lower())
                or (filter_specs.get((binding.entityName or "").strip().lower()) if binding else None)
                or {}
            )
            op = str(fspec.get("op") or req.get("op") or "eq")
            canonical = (
                req.get("defaultMember")
                if (fspec.get("valueFrom") == "defaultMember" or req.get("defaultMember") is not None)
                else req.get("value")
            )
            filter_col = cols[0]
            value, applied = resolve_filter_value(
                canonical, _distinct_values(filter_col, dataset, df)
            )
            roles.filters.append(
                ResolvedFilter(column=filter_col, op=op, value=value, filterApplied=applied)
            )
            if not applied:
                degraded = True
                notes.append(
                    f"filter '{ent_id}'={canonical!r} not found in '{filter_col}' — widened"
                )
        else:
            # unknown / metadata role — record as dimension for grouping safety
            roles.dimensions.extend(c for c in cols if c not in roles.dimensions)

    if blocked:
        status = "blocked"
    elif degraded:
        status = "degraded"
    else:
        status = "executable"

    return QuestionBinding(
        questionId=qid,
        status=status,
        resolvedRoles=roles,
        unresolvedEntities=unresolved,
        notes=notes,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def _iter_questions(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten topics[].questions[] (or a top-level questions[])."""
    if blueprint.get("questions"):
        return list(blueprint["questions"])
    out: list[dict[str, Any]] = []
    for topic in (blueprint.get("topics") or []):
        out.extend(topic.get("questions") or [])
    return out


def bind_questions(
    blueprint: dict[str, Any],
    entity_bindings: list[EntityBinding],
    dataset: DatasetAST,
    *,
    df: Any | None = None,
) -> list[QuestionBinding]:
    """Resolve every question in a blueprint (S3)."""
    bindings_by_id = _index_bindings(entity_bindings)
    questions = _iter_questions(blueprint)
    results = [
        bind_question(q, bindings_by_id, dataset, df=df) for q in questions
    ]
    logger.info(
        "[question_binder] %d questions: %d executable, %d degraded, %d blocked",
        len(results),
        sum(1 for r in results if r.status == "executable"),
        sum(1 for r in results if r.status == "degraded"),
        sum(1 for r in results if r.status == "blocked"),
    )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# S3 Plan Compiler — produces QuestionExecutionPlan[] from QuestionBinding[]
# ─────────────────────────────────────────────────────────────────────────────


def compile_execution_plans(
    blueprint: dict[str, Any],
    question_bindings: list[QuestionBinding],
    dataset: DatasetAST,
) -> "list[Any]":
    """Compile QuestionBinding[] into QuestionExecutionPlan[] (S3 → S3.5 handoff).

    For each non-blocked question:
    - Resolves analyticsSpec fields to actual column names
    - Determines normalizationPlan (wide-to-long if measure is a column group)
    - Derives formulaSpec from operation type + question text
    - Attaches outputContract from blueprint answerStructure
    - Builds lineage (question → entities → columns → source)

    Returns QuestionExecutionPlan instances ready for the readiness gate.
    """
    from report_builder.binding.execution_contracts import (
        FormulaSpec,
        LineageRef,
        NormalizationPlan,
        QuestionExecutionPlan,
    )

    # Index questions by ID for lookup
    bp_questions: dict[str, dict[str, Any]] = {}
    for topic in (blueprint.get("topics") or []):
        for q in (topic.get("questions") or []):
            qid = q.get("questionId", "")
            if qid:
                bp_questions[qid] = q
    for q in (blueprint.get("questions") or []):
        qid = q.get("questionId", "")
        if qid:
            bp_questions[qid] = q

    plans: list[QuestionExecutionPlan] = []

    for qb in question_bindings:
        if qb.status == "blocked":
            continue

        bp_q = bp_questions.get(qb.questionId, {})
        analytics_spec = bp_q.get("analyticsSpec") or {}
        answer_structure = bp_q.get("answerStructure") or {}
        output_components = answer_structure.get("components", [])
        required_entities = bp_q.get("requiredEntities") or []
        question_text = bp_q.get("questionText") or bp_q.get("intent", "")
        question_type = bp_q.get("questionType", "comparison")

        # ── Determine formula type ──
        operation = analytics_spec.get("operation", "group_aggregate")
        formula_type = _infer_formula_type(operation, question_text, question_type)

        # ── Build formulaSpec ──
        formula = FormulaSpec(type=formula_type)
        if formula_type == "GROWTH" and len(qb.resolvedRoles.measures) >= 2:
            # Assume first is prior, second is current (or vice versa)
            measures = qb.resolvedRoles.measures
            formula.numeratorColumn = measures[-1]  # current
            formula.denominatorColumn = measures[0]  # prior
            formula.multiplier = 100.0
            formula.unitConversion = "percent"
            formula.timeWindow = qb.resolvedRoles.time.periods
        elif formula_type == "SHARE":
            # Share = numerator / total
            if qb.resolvedRoles.measures:
                formula.numeratorColumn = qb.resolvedRoles.measures[0]
            formula.multiplier = 100.0
            formula.unitConversion = "percent"
        elif formula_type == "RATE":
            if qb.resolvedRoles.measures:
                formula.numeratorColumn = qb.resolvedRoles.measures[0]
            formula.multiplier = 1000.0  # per 1000 default for MoSPI

        # ── Determine normalization ──
        norm_plan = _infer_normalization(qb, dataset)

        # ── Build outputContract ──
        output_contract = {}
        if output_components:
            output_contract = {"components": output_components}

        # ── Build lineage ──
        lineage = LineageRef(
            sourceQuestionId=qb.questionId,
            sourceEntityIds=[r.get("entityId", r.get("entityRef", "")) for r in required_entities],
            sourceColumnIds=qb.resolvedRoles.measures + qb.resolvedRoles.dimensions,
        )

        plan = QuestionExecutionPlan(
            planId=f"plan_{qb.questionId}",
            questionId=qb.questionId,
            questionText=question_text,
            status="EXECUTABLE" if qb.status == "executable" else "DEGRADED",
            analyticsSpec=analytics_spec,
            resolvedRoles=qb.resolvedRoles,
            normalizationPlan=norm_plan,
            formulaSpec=formula,
            outputContract=output_contract,
            lineage=lineage,
        )
        plans.append(plan)

    logger.info(
        "[plan_compiler] Compiled %d plans: %d EXECUTABLE, %d DEGRADED",
        len(plans),
        sum(1 for p in plans if p.status == "EXECUTABLE"),
        sum(1 for p in plans if p.status == "DEGRADED"),
    )
    return plans


def _infer_formula_type(operation: str, question_text: str, question_type: str) -> str:
    """Infer FormulaSpec.type from operation, question text, and type."""
    text_low = question_text.lower()

    # Explicit operation mappings
    if operation in ("growth", "yoy_change"):
        return "GROWTH"
    if operation == "cagr":
        return "CAGR"
    if operation == "share":
        return "SHARE"
    if operation == "index":
        return "INDEX"
    if operation == "ratio":
        return "RATIO"

    # Keyword detection from question text
    if any(k in text_low for k in ("growth", "year-over-year", "yoy", "change over")):
        return "GROWTH"
    if any(k in text_low for k in ("share", "distribution", "proportion", "percentage distribution")):
        return "SHARE"
    if any(k in text_low for k in ("per 1000", "per lakh", "rate per")):
        return "RATE"
    if any(k in text_low for k in ("cagr", "compound annual")):
        return "CAGR"
    if any(k in text_low for k in ("index", "base year")):
        return "INDEX"
    if any(k in text_low for k in ("ratio of", "relative to")):
        return "RATIO"

    # Question type fallback
    if question_type == "trend" and "compare" not in text_low:
        return "GROWTH"

    return "DIRECT"


def _infer_normalization(qb: QuestionBinding, dataset: DatasetAST) -> "Any":
    """Infer NormalizationPlan from resolved roles and dataset shape."""
    from report_builder.binding.execution_contracts import NormalizationPlan

    # Check if any measure column belongs to a column group (wide table)
    for measure_col in qb.resolvedRoles.measures:
        for group in dataset.columnGroups:
            if measure_col in group.members:
                # This measure is part of a wide group — needs melt for time-series queries
                if group.kind == "periodGroup":
                    id_vars = [c.name for c in dataset.columns if c.role == "dimension"]
                    return NormalizationPlan(
                        type="WIDE_TO_LONG",
                        idVars=id_vars,
                        valueVar="value",
                        memberVar="period",
                        memberLabels=group.members,
                    )
                elif group.kind == "measureGroup":
                    id_vars = [c.name for c in dataset.columns if c.role == "dimension"]
                    return NormalizationPlan(
                        type="WIDE_TO_LONG",
                        idVars=id_vars,
                        valueVar="value",
                        memberVar=group.stem or "category",
                        memberLabels=group.members,
                    )

    return NormalizationPlan(type="NONE")
