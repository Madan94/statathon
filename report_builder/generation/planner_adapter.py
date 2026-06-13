"""S4a — Plan adapter: blueprint ``analyticsSpec`` + binding ``resolvedRoles`` → plan.

The binding phase already resolved **every entity to a dataset column** for every
question and a human confirmed it. So — unlike the NL-driven
``deep_bi.AnalyticsPlanner`` — this adapter never has to *find* columns: it merges
two known inputs into a deterministic, declarative compute plan.

    ② blueprint.analyticsSpec   →  WHAT: operation, agg, sort, topN
    bindingAST.resolvedRoles    →  WHICH columns: measures / dimensions / filters / time
    datasetAST                  →  HOW: weight column, dtypes
                                 ↓
                          AnalyticsPlanRec   (gold ``analyticsAST.plans[]`` shape)

The plan is the single source of truth the executor (S4b) follows without
re-deciding anything, so a number can always be traced plan → execution → rows.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from report_builder.binding.schema import BindingAST, DatasetAST, QuestionBinding
from report_builder.generation.schema import AnalyticsPlanRec, PlanMeasure

logger = logging.getLogger(__name__)

# Aggregations that need a survey weight/multiplier column to be correct.
_WEIGHTED_AGGS = {"weighted_ratio", "weighted_mean", "weighted_sum"}

# Heuristics for spotting a survey weight column (PLFS "multiplier", generic "weight").
_WEIGHT_HINTS = ("weight", "mult", "wt", "wgt", "multiplier")

# questionType / operation → the canonical analytic operation bucket.
_OPERATION_ALIASES = {
    "group_aggregate": "group_aggregate",
    "aggregate": "group_aggregate",
    "comparison": "group_aggregate",
    "distribution": "group_aggregate",
    "rank": "rank",
    "ranking": "rank",
    "trend": "trend",
    "timeseries": "trend",
    "metric": "metric",
    "kpi": "metric",
    "single_value": "metric",
}


def _norm(text: Any) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm(text)).strip("_")


# ─────────────────────────────────────────────────────────────────────────────
# Entity → column resolution
# ─────────────────────────────────────────────────────────────────────────────


def _entity_index(binding: BindingAST, blueprint_entities: list[dict[str, Any]] | None) -> dict[str, str]:
    """Map an entity *id OR canonical name OR alias* → entityId.

    Noisy blueprints sometimes reference entities by name in ``analyticsSpec``
    (a known extraction residual). This index lets the adapter accept either, so
    a name like ``"Worker Population Ratio"`` still resolves to ``ent_wpr``.
    """
    idx: dict[str, str] = {}
    for b in binding.entityBindings:
        idx[b.entityId] = b.entityId
        if b.entityName:
            idx[_norm(b.entityName)] = b.entityId
    for e in blueprint_entities or []:
        eid = e.get("entityId")
        if not eid:
            continue
        idx[eid] = eid
        if e.get("canonicalName"):
            idx[_norm(e["canonicalName"])] = eid
        for alias in e.get("aliases") or []:
            idx.setdefault(_norm(alias), eid)
    return idx


def _resolve_entity_id(ref: Any, entity_index: dict[str, str]) -> str | None:
    if ref is None:
        return None
    ref = str(ref)
    if ref in entity_index:
        return entity_index[ref]
    return entity_index.get(_norm(ref))


def _entity_column(entity_id: str | None, binding: BindingAST) -> str | None:
    """The first bound dataset column for an entity (None if derived/unbound)."""
    if not entity_id:
        return None
    b = binding.binding_for(entity_id)
    if b and b.columns:
        return b.columns[0].column
    return None


def _find_weight_column(dataset: DatasetAST | None) -> str | None:
    if dataset is None:
        return None
    for col in dataset.columns:
        name = _norm(col.name)
        if any(h in name for h in _WEIGHT_HINTS):
            return col.name
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Filter expression rendering
# ─────────────────────────────────────────────────────────────────────────────

_OP_SYMBOL = {"eq": "==", "ne": "!=", "ge": ">=", "le": "<=", "gt": ">", "lt": "<"}


def _filter_expr(column: str, op: str, value: Any) -> str:
    """Render a resolved filter as a stable expr string, e.g. ``age>=15``.

    Gold uses bare ``>=`` style for numerics; equality on a categorical member is
    rendered as ``col=='Member'`` so the executor can apply it unambiguously.
    """
    sym = _OP_SYMBOL.get(str(op or "eq").lower(), "==")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{column}{sym}{value}"
    return f"{column}{sym}'{value}'"


# ─────────────────────────────────────────────────────────────────────────────
# The adapter
# ─────────────────────────────────────────────────────────────────────────────


def build_plan(
    question: dict[str, Any],
    question_binding: QuestionBinding | dict[str, Any],
    binding: BindingAST,
    dataset: DatasetAST | None = None,
    *,
    blueprint_entities: list[dict[str, Any]] | None = None,
) -> AnalyticsPlanRec:
    """Build one ``AnalyticsPlanRec`` (gold shape) for a single question.

    Resolution order for each column role, most-trusted first:
      1. the **binding's** ``resolvedRoles`` (human-confirmed columns), then
      2. the **blueprint's** ``analyticsSpec`` entityRefs mapped via entity bindings.
    The binding wins because it reflects the *actual* dataset and human sign-off.
    """
    if isinstance(question_binding, dict):
        question_binding = QuestionBinding.from_dict(question_binding)

    qid = question.get("questionId") or question_binding.questionId or "q"
    spec = question.get("analyticsSpec") or {}
    roles = question_binding.resolvedRoles
    entity_index = _entity_index(binding, blueprint_entities)

    # ── operation ──
    operation = _OPERATION_ALIASES.get(
        _norm(spec.get("operation")) or _norm(question.get("questionType")),
        "group_aggregate" if (roles.dimensions or spec.get("groupBy")) else "metric",
    )

    # ── measure column + agg ──
    spec_measure = spec.get("measure") or {}
    agg = _norm(spec_measure.get("agg")) or "mean"
    measure_col = (
        (roles.measures[0] if roles.measures else None)
        or _entity_column(_resolve_entity_id(spec_measure.get("entityRef"), entity_index), binding)
        or ""
    )
    weight_col = _find_weight_column(dataset) if agg in _WEIGHTED_AGGS else None
    measure = PlanMeasure(columnExpr=measure_col, agg=agg, weightColumn=weight_col)

    # ── groupBy columns ──
    group_cols: list[str] = list(roles.dimensions)
    if not group_cols:
        for g in spec.get("groupBy") or []:
            col = _entity_column(_resolve_entity_id(g.get("entityRef"), entity_index), binding)
            if col and col not in group_cols:
                group_cols.append(col)

    # ── filters → expr strings ──
    filters: list[str] = []
    for f in roles.filters:
        if f.column and getattr(f, "filterApplied", True):
            filters.append(_filter_expr(f.column, f.op, f.value))
    if not filters:
        # Fall back to the blueprint's declared filters (column via entity binding).
        for f in spec.get("filters") or []:
            col = _entity_column(_resolve_entity_id(f.get("entityRef"), entity_index), binding)
            val = f.get("value")
            if col and val is not None:
                filters.append(_filter_expr(col, f.get("op") or "eq", val))

    # ── sort ──
    spec_sort = spec.get("sort") or {}
    sort_by = spec_sort.get("by")
    # Gold sorts by the measure column name, not the literal token "measure".
    if not sort_by or _norm(sort_by) == "measure":
        sort_by = measure_col
    sort = {"by": sort_by, "order": _norm(spec_sort.get("order")) or "desc"} if measure_col else {}

    # ── topN ──
    top_n = spec.get("topN")
    top_n = int(top_n) if isinstance(top_n, (int, float)) and not isinstance(top_n, bool) else None

    plan = AnalyticsPlanRec(
        planId=f"plan_{qid}",
        questionId=qid,
        operation=operation,
        measure=measure,
        groupBy=group_cols,
        filters=filters,
        sort=sort,
        topN=top_n,
    )

    if not measure_col:
        logger.warning("[plan] question %s has no resolvable measure column", qid)
    return plan


def build_plans(
    blueprint: dict[str, Any],
    binding: BindingAST,
    dataset: DatasetAST | None = None,
) -> list[AnalyticsPlanRec]:
    """Build plans for every *executable / degraded* question in a blueprint.

    Blocked questions (coverage gate) are skipped — they have no resolvable
    columns and must not enter the report.
    """
    qb_by_id = {qb.questionId: qb for qb in binding.questionBindings}
    entities = blueprint.get("entities") or []
    plans: list[AnalyticsPlanRec] = []
    for topic in blueprint.get("topics") or []:
        for q in topic.get("questions") or []:
            qid = q.get("questionId")
            qb = qb_by_id.get(qid)
            if qb is None or qb.status == "blocked":
                continue
            plans.append(build_plan(q, qb, binding, dataset, blueprint_entities=entities))
    return plans
