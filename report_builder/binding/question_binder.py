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


def _iter_section_questions(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively collect questions from a topic/section and any nested children."""
    out: list[dict[str, Any]] = list(section.get("questions") or [])
    for key in ("subtopics", "sections", "children", "subsections"):
        for child in section.get(key) or []:
            if isinstance(child, dict):
                out.extend(_iter_section_questions(child))
    return out


def _iter_questions(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten topics[].questions[] recursively (or a top-level questions[])."""
    if blueprint.get("questions"):
        return list(blueprint["questions"])
    out: list[dict[str, Any]] = []
    for topic in (blueprint.get("topics") or blueprint.get("sections") or []):
        out.extend(_iter_section_questions(topic))
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
        source_analytics_spec = bp_q.get("analyticsSpec") or {}
        answer_structure = bp_q.get("answerStructure") or bp_q.get("outputContract") or {}
        output_components = answer_structure.get("components", []) if isinstance(answer_structure, dict) else []
        required_entities = bp_q.get("requiredEntities") or []
        question_text = bp_q.get("questionText") or bp_q.get("intent", "")
        question_type = bp_q.get("questionType", "comparison")

        # ── Resolve analyticsSpec to execution-ready columns ──
        _resolved_measure = qb.resolvedRoles.measures[0] if qb.resolvedRoles.measures else ""
        _resolved_dims = qb.resolvedRoles.dimensions
        _raw_agg = source_analytics_spec.get("measure", {}).get("agg", "sum") if isinstance(source_analytics_spec.get("measure"), dict) else "sum"
        _unit = ""
        for _col in dataset.columns:
            if _col.name == _resolved_measure and _col.unit:
                _unit = _col.unit
                break
        # For rates/percentages, override agg to reported_value (cannot sum rates)
        _resolved_agg = _raw_agg
        if _unit in ("percent", "per_1000", "index", "ratio") and _raw_agg == "sum":
            _resolved_agg = "reported_value"

        analytics_spec: dict[str, Any] = {
            "operation": source_analytics_spec.get("operation", "group_aggregate"),
            "measure": {"column": _resolved_measure, "agg": _resolved_agg, "unit": _unit} if _resolved_measure else {},
            "groupBy": [{"column": d} for d in _resolved_dims],
            "filters": [{"column": f.column, "op": f.op, "value": f.value} for f in qb.resolvedRoles.filters],
            "sort": source_analytics_spec.get("sort") or {"by": "measure", "order": "desc"},
            "topN": source_analytics_spec.get("topN"),
        }
        if qb.resolvedRoles.time.column:
            analytics_spec["time"] = {"column": qb.resolvedRoles.time.column, "periods": qb.resolvedRoles.time.periods}

        # ── Determine formula type ──
        operation = analytics_spec.get("operation", "group_aggregate")
        formula_type = _infer_formula_type(operation, question_text, question_type)

        # ── Build formulaSpec ──
        formula = FormulaSpec(type=formula_type)
        diagnostics: list[str] = []

        if formula_type == "GROWTH":
            measures = qb.resolvedRoles.measures
            time_periods = qb.resolvedRoles.time.periods
            if time_periods.get("current") and time_periods.get("prior"):
                # Time periods are explicitly resolved — safe
                formula.timeWindow = time_periods
                # Try to match columns to periods via name
                current_col = next((m for m in measures if time_periods["current"] in m), measures[-1] if measures else "")
                prior_col = next((m for m in measures if time_periods["prior"] in m), measures[0] if measures else "")
                formula.numeratorColumn = current_col
                formula.denominatorColumn = prior_col
            elif len(measures) >= 2:
                # UNSAFE: guessing period order from column names
                # Try to parse year from column names
                import re as _re_period
                _year_re = _re_period.compile(r'(\d{4})')
                years = []
                for m in measures:
                    match = _year_re.search(m)
                    if match:
                        years.append((int(match.group(1)), m))
                if len(years) >= 2:
                    years.sort()
                    formula.denominatorColumn = years[0][1]  # prior (earlier year)
                    formula.numeratorColumn = years[-1][1]   # current (later year)
                    formula.timeWindow = {"prior": str(years[0][0]), "current": str(years[-1][0])}
                else:
                    # Cannot determine period order — DEGRADE the plan
                    diagnostics.append("GROWTH_PERIODS_UNCERTAIN: cannot determine current/prior from column names")
                    formula.numeratorColumn = measures[-1]
                    formula.denominatorColumn = measures[0]
            else:
                diagnostics.append("GROWTH_MISSING_PERIODS: need at least 2 measure columns for growth calculation")
            formula.multiplier = 100.0
            formula.unitConversion = "percent"

        elif formula_type == "SHARE":
            if qb.resolvedRoles.measures:
                formula.numeratorColumn = qb.resolvedRoles.measures[0]
            else:
                diagnostics.append("SHARE_MISSING_NUMERATOR: no measure column for share calculation")
            formula.multiplier = 100.0
            formula.unitConversion = "percent"

        elif formula_type == "RATE":
            if qb.resolvedRoles.measures:
                formula.numeratorColumn = qb.resolvedRoles.measures[0]
            else:
                diagnostics.append("RATE_MISSING_NUMERATOR: no measure column for rate calculation")
            formula.multiplier = 1000.0  # per 1000 default for MoSPI

        # ── Determine normalization ──
        norm_plan = _infer_normalization(qb, dataset)

        # ── Build outputContract ──
        output_contract = {}
        if output_components:
            output_contract = {"components": output_components}
        else:
            diagnostics.append("OUTPUT_CONTRACT_MISSING: no answerStructure.components in blueprint question")

        # ── Build lineage ──
        all_columns = qb.resolvedRoles.measures + qb.resolvedRoles.dimensions
        if qb.resolvedRoles.time.column:
            all_columns.append(qb.resolvedRoles.time.column)
        for f in qb.resolvedRoles.filters:
            if f.column and f.column not in all_columns:
                all_columns.append(f.column)

        lineage = LineageRef(
            sourceQuestionId=qb.questionId,
            sourceEntityIds=[r.get("entityId", r.get("entityRef", "")) for r in required_entities],
            sourceColumnIds=all_columns,
        )

        # ── Determine final plan status ──
        plan_status = "EXECUTABLE" if qb.status == "executable" else "DEGRADED"
        if any("MISSING" in d or "UNCERTAIN" in d for d in diagnostics):
            plan_status = "DEGRADED"

        plan = QuestionExecutionPlan(
            planId=f"plan_{qb.questionId}",
            questionId=qb.questionId,
            questionText=question_text,
            status=plan_status,
            analyticsSpec=analytics_spec,
            sourceAnalyticsSpec=dict(source_analytics_spec),
            resolvedRoles=qb.resolvedRoles,
            normalizationPlan=norm_plan,
            formulaSpec=formula,
            outputContract=output_contract,
            lineage=lineage,
            diagnostics=diagnostics,
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
    """Infer FormulaSpec.type CONSERVATIVELY from operation, question text, and type.

    MoSPI-safe: defaults to DIRECT unless there is STRONG evidence for a derived formula.
    "distribution of reserves by state" = DIRECT grouped values, NOT percentage share.
    Only use SHARE when text explicitly says "share", "proportion", "percentage of total".
    """
    text_low = question_text.lower()

    # Explicit operation mappings (from blueprint analyticsSpec — these are trusted)
    if operation in ("growth", "yoy_change", "year_over_year"):
        return "GROWTH"
    if operation == "cagr":
        return "CAGR"
    if operation == "share":
        return "SHARE"
    if operation == "index":
        return "INDEX"
    if operation == "ratio":
        return "RATIO"
    if operation == "rate":
        return "RATE"

    # Conservative keyword detection — ONLY strong signals
    # GROWTH: must explicitly mention growth/change/yoy
    if any(k in text_low for k in ("growth rate", "year-over-year", "yoy change", "annual change", "change over previous")):
        return "GROWTH"

    # SHARE: must explicitly ask for share/proportion/% of total — NOT "distribution"
    # "distribution" alone means "how is it distributed" = grouped values = DIRECT
    if any(k in text_low for k in ("share of", "proportion of", "percentage of total", "% of total", "as a share")):
        return "SHARE"

    # RATE: must explicitly mention per-1000/per-lakh rate calculation
    if any(k in text_low for k in ("per 1000", "per lakh", "per 100000", "rate per")):
        return "RATE"

    # CAGR/INDEX are rare — only explicit mentions
    if "cagr" in text_low or "compound annual growth" in text_low:
        return "CAGR"
    if any(k in text_low for k in ("index value", "base year index", "index number")):
        return "INDEX"

    # RATIO: explicit "ratio of X to Y"
    if "ratio of" in text_low or "relative to" in text_low:
        return "RATIO"

    # DEFAULT: everything else is DIRECT (safe for MoSPI)
    # "distribution", "top states", "comparison", "ranking" are all DIRECT grouped queries
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
