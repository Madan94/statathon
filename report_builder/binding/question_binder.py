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
    return {b.entityId: b for b in bindings}


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
    """Index analyticsSpec.filters by entityRef → {op, valueFrom}."""
    out: dict[str, dict[str, Any]] = {}
    for f in (analytics_spec.get("filters") or []):
        ref = f.get("entityRef") or f.get("entityId")
        if ref:
            out[str(ref)] = {"op": f.get("op", "eq"), "valueFrom": f.get("valueFrom")}
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
        binding = bindings_by_id.get(ent_id)
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
            fspec = filter_specs.get(ent_id, {})
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
