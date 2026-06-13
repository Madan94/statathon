"""S4a-gold — ExecutionBundle → generation plans adapter (the gold-conformant path).

This is the **gold** replacement for `planner_adapter.build_plans`, which re-derives
plans from the blueprint + a rebuilt `BindingAST`. Instead, this adapter consumes the
team's frozen, validated **`ExecutionBundle`** (`binding.executionBundle.v1`) — "the S4
team's ONLY input contract" — so generation runs on the same resolved plans the binder
produced, never on re-interpreted internals.

What it does (Phase 2 scope):
  1. **Map** each `QuestionExecutionPlan` → the render-shape `AnalyticsPlanRec` the
     executor already understands (operation / measure / groupBy / filters / sort / topN).
  2. **Fan out multi-measure** questions: the binder collapses `analyticsSpec.measure`
     to a single column, but the full list survives on `resolvedRoles.measures`. We emit
     one plan per measure with a **stable identity** `plan_<questionId>__<measure_slug>`
     so values can never land in the wrong table column / chart series.
  3. **Preserve** everything the later phases need but `AnalyticsPlanRec` has no room for:
     `formulaSpec` (Phase 3 `formula_exec`), `normalizationPlan` (Phase 4),
     `outputContract.components[]` + per-measure lineage (Phase 5 provenance).

What it deliberately does NOT do (out of Phase 2 scope):
  - It does **not** compute formula math (SHARE/RATE/RATIO/GROWTH/CAGR/INDEX) — that is
    `formula_exec` (Phase 3). The structured `formulaSpec` is carried through untouched.
  - It does **not** gate the whole bundle on `NOT_READY` — that is the S4 coordinator's
    responsibility (§10). It *does* refuse to emit a runnable plan for any **BLOCKED**
    plan, because an `AnalyticsPlanRec` is an execution instruction and BLOCKED plans
    must never be executed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from report_builder.binding.execution_contracts import (
    ExecutionBundle,
    FormulaSpec,
    LineageRef,
    NormalizationPlan,
    QuestionExecutionPlan,
)
from report_builder.generation.planner_adapter import _filter_expr, _norm, _slug
from report_builder.generation.schema import AnalyticsPlanRec, PlanMeasure

logger = logging.getLogger(__name__)

# Team `analyticsSpec.operation` vocabulary → render `OPERATIONS` bucket.
# Formula operations (share/ratio/rate/index) still aggregate at a group grain; the
# quotient itself is computed later by `formula_exec`, so the *bucket* is group_aggregate.
# Time formulas (growth/cagr) map to the time-series bucket.
_OPERATION_BUCKET = {
    "group_aggregate": "group_aggregate",
    "aggregate": "group_aggregate",
    "comparison": "group_aggregate",
    "distribution": "group_aggregate",
    "share": "group_aggregate",
    "ratio": "group_aggregate",
    "rate": "group_aggregate",
    "index": "group_aggregate",
    "rank": "rank",
    "ranking": "rank",
    "trend": "trend",
    "timeseries": "trend",
    "growth": "trend",
    "cagr": "trend",
    "metric": "metric",
    "kpi": "metric",
    "single_value": "metric",
}

# Plan statuses that are runnable (BLOCKED is never emitted).
_RUNNABLE = {"EXECUTABLE", "DEGRADED"}


@dataclass
class AdaptedPlan:
    """One executable unit: a render-shape plan + the gold metadata later phases need.

    `planRec` is what the existing executor consumes. The rest travels alongside so the
    S4 coordinator (Phase 3) can route by `formulaSpec.type`, and S5/S6 can place the
    value in the right slot and trace its provenance — without re-reading the bundle.
    """

    planRec: AnalyticsPlanRec                 # render-shape execution plan
    questionId: str = ""
    sourcePlanId: str = ""                    # the originating QuestionExecutionPlan.planId
    status: str = "EXECUTABLE"                # EXECUTABLE | DEGRADED (BLOCKED never emitted)
    fannedOut: bool = False                   # True when this came from multi-measure fan-out
    # Fan-out identity / slot mapping
    measureColumn: str = ""
    measureSlug: str = ""
    measureLabel: str = ""                    # human label for the slot (best-effort)
    componentRef: str | None = None           # outputContract component this measure maps to
    timeColumn: str = ""                       # resolved time/period column (GROWTH/CAGR/trend)
    # Carried gold metadata (untouched — for Phases 3-5)
    formulaSpec: FormulaSpec = field(default_factory=FormulaSpec)
    normalizationPlan: NormalizationPlan = field(default_factory=NormalizationPlan)
    outputContract: dict[str, Any] = field(default_factory=dict)
    evidenceRequirements: dict[str, Any] = field(default_factory=dict)
    lineage: LineageRef = field(default_factory=LineageRef)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "planRec": self.planRec.to_dict(),
            "questionId": self.questionId,
            "sourcePlanId": self.sourcePlanId,
            "status": self.status,
            "fannedOut": self.fannedOut,
            "measureColumn": self.measureColumn,
            "measureSlug": self.measureSlug,
            "measureLabel": self.measureLabel,
            "componentRef": self.componentRef,
            "timeColumn": self.timeColumn,
            "formulaSpec": self.formulaSpec.to_dict(),
            "normalizationPlan": self.normalizationPlan.to_dict(),
            "outputContract": dict(self.outputContract),
            "evidenceRequirements": dict(self.evidenceRequirements),
            "lineage": self.lineage.to_dict(),
            "diagnostics": list(self.diagnostics),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _measure_columns(plan: QuestionExecutionPlan) -> list[str]:
    """The full ordered measure list, deduped.

    Prefer `resolvedRoles.measures` (the full list the binder kept); fall back to the
    single collapsed `analyticsSpec.measure.column` so a plan is never measure-less.
    """
    measures = [m for m in (plan.resolvedRoles.measures or []) if m]
    if not measures:
        spec_col = ((plan.analyticsSpec.get("measure") or {}).get("column") or "").strip()
        if spec_col:
            measures = [spec_col]
    # dedupe, order-preserving
    seen: set[str] = set()
    out: list[str] = []
    for m in measures:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _dimension_columns(plan: QuestionExecutionPlan) -> list[str]:
    dims = [d for d in (plan.resolvedRoles.dimensions or []) if d]
    if not dims:
        for g in plan.analyticsSpec.get("groupBy") or []:
            col = (g or {}).get("column")
            if col and col not in dims:
                dims.append(col)
    return dims


def _filter_exprs(plan: QuestionExecutionPlan) -> tuple[list[str], list[str]]:
    """Render applied filters as expr strings. Returns (exprs, filter_columns)."""
    exprs: list[str] = []
    cols: list[str] = []
    for f in plan.resolvedRoles.filters or []:
        if f.column and getattr(f, "filterApplied", True):
            exprs.append(_filter_expr(f.column, f.op, f.value))
            cols.append(f.column)
    return exprs, cols


def _match_component(measure_col: str, components: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Best-effort map a measure column → its outputContract component (ref, label).

    Matches on an explicit column/measure reference first, then on a label whose slug
    equals the measure slug. Returns (componentRef, label) — either may be None.
    """
    target = _norm(measure_col)
    target_slug = _slug(measure_col)
    for c in components or []:
        if not isinstance(c, dict):
            continue
        ref = c.get("componentId") or c.get("id") or c.get("ref")
        # explicit references the binder/blueprint may carry
        for key in ("column", "columnExpr", "measure", "measureRef", "entityRef"):
            val = c.get(key)
            if val and _norm(val) == target:
                return ref, c.get("label") or c.get("title") or measure_col
        label = c.get("label") or c.get("title")
        if label and _slug(label) == target_slug:
            return ref, label
    return None, None


def _per_measure_lineage(plan: QuestionExecutionPlan, measure_col: str,
                         dims: list[str], filter_cols: list[str]) -> LineageRef:
    """Lineage for one fanned measure: ITS column + shared dims/filters/time."""
    cols = [measure_col, *dims, *filter_cols]
    time_col = plan.resolvedRoles.time.column
    if time_col:
        cols.append(time_col)
    # dedupe order-preserving
    seen: set[str] = set()
    src_cols: list[str] = []
    for c in cols:
        if c and c not in seen:
            seen.add(c)
            src_cols.append(c)
    base = plan.lineage
    return LineageRef(
        sourceQuestionId=base.sourceQuestionId or plan.questionId,
        sourceEntityIds=list(base.sourceEntityIds),
        sourceColumnIds=src_cols,
        sourceTableId=base.sourceTableId,
        headerPaths=[list(p) for p in base.headerPaths],
        transformations=list(base.transformations),
    )


# ─────────────────────────────────────────────────────────────────────────────
# The adapter
# ─────────────────────────────────────────────────────────────────────────────


def adapt_plan(plan: QuestionExecutionPlan) -> list[AdaptedPlan]:
    """Adapt one `QuestionExecutionPlan` → 1..N `AdaptedPlan` (fan out per measure).

    A BLOCKED plan yields **no** AdaptedPlan (it must never be executed). One measure ⇒
    one plan keyed `plan_<qid>`; multiple measures ⇒ one plan each, keyed
    `plan_<qid>__<measure_slug>`.
    """
    if plan.status not in _RUNNABLE:
        logger.info("[bundle_adapter] skipping %s plan %s (not runnable)", plan.status, plan.planId)
        return []

    qid = plan.questionId or "q"
    spec = plan.analyticsSpec or {}
    spec_measure = spec.get("measure") or {}
    agg = _norm(spec_measure.get("agg")) or "mean"
    weight_col = plan.formulaSpec.weightColumn or None

    operation = _OPERATION_BUCKET.get(
        _norm(spec.get("operation")),
        "group_aggregate" if _dimension_columns(plan) else "metric",
    )

    measures = _measure_columns(plan)
    dims = _dimension_columns(plan)
    filter_exprs, filter_cols = _filter_exprs(plan)
    components = plan.outputContract.get("components") or []

    # topN
    top_n = spec.get("topN")
    top_n = int(top_n) if isinstance(top_n, (int, float)) and not isinstance(top_n, bool) else None

    multi = len(measures) > 1
    out: list[AdaptedPlan] = []

    # A measure-less plan still yields one plan (e.g. a pure count metric).
    measure_iter: list[str] = measures or [""]

    for measure_col in measure_iter:
        slug = _slug(measure_col) if measure_col else ""
        plan_id = f"plan_{qid}__{slug}" if (multi and slug) else f"plan_{qid}"

        # sort: gold sorts by the measure column, not the literal token "measure".
        spec_sort = spec.get("sort") or {}
        sort_by = spec_sort.get("by")
        if not sort_by or _norm(sort_by) == "measure":
            sort_by = measure_col
        sort = {"by": sort_by, "order": _norm(spec_sort.get("order")) or "desc"} if measure_col else {}

        plan_rec = AnalyticsPlanRec(
            planId=plan_id,
            questionId=qid,
            operation=operation,
            measure=PlanMeasure(columnExpr=measure_col, agg=agg, weightColumn=weight_col),
            groupBy=list(dims),
            filters=list(filter_exprs),
            sort=sort,
            topN=top_n,
        )

        comp_ref, comp_label = _match_component(measure_col, components)
        out.append(AdaptedPlan(
            planRec=plan_rec,
            questionId=qid,
            sourcePlanId=plan.planId,
            status=plan.status,
            fannedOut=multi,
            measureColumn=measure_col,
            measureSlug=slug,
            measureLabel=comp_label or measure_col,
            componentRef=comp_ref,
            timeColumn=plan.resolvedRoles.time.column or "",
            formulaSpec=plan.formulaSpec,
            normalizationPlan=plan.normalizationPlan,
            outputContract=dict(plan.outputContract),
            evidenceRequirements=dict(plan.evidenceRequirements),
            lineage=_per_measure_lineage(plan, measure_col, dims, filter_cols),
            diagnostics=list(plan.diagnostics),
        ))
    return out


def adapt_bundle(bundle: ExecutionBundle, *, include_degraded: bool = True) -> list[AdaptedPlan]:
    """Adapt every runnable plan in an `ExecutionBundle` → `AdaptedPlan`s.

    BLOCKED plans are skipped (never executed). DEGRADED plans are included by default
    (they run with caveats per §10); pass `include_degraded=False` to emit only
    EXECUTABLE plans. Bundle-level `NOT_READY` gating is the coordinator's job (§10).
    """
    adapted: list[AdaptedPlan] = []
    for plan in bundle.plans:
        if not include_degraded and plan.status == "DEGRADED":
            continue
        adapted.extend(adapt_plan(plan))
    logger.info(
        "[bundle_adapter] adapted %d plan(s) → %d executable unit(s) (bundle status=%s)",
        len(bundle.plans), len(adapted), bundle.status,
    )
    return adapted


def bundle_to_planrecs(bundle: ExecutionBundle, *, include_degraded: bool = True) -> list[AnalyticsPlanRec]:
    """Convenience: the render-shape `AnalyticsPlanRec` list (drops the carried metadata).

    Matches the INTEGRATION_PLAN §4 signature. Use `adapt_bundle` when you need the
    formula/lineage/slot metadata (the coordinator and S5/S6 do).
    """
    return [ap.planRec for ap in adapt_bundle(bundle, include_degraded=include_degraded)]
