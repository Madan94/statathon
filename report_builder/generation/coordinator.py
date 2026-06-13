"""S4 execution coordinator — the bridge from `ExecutionBundle` to the gold ASTs.

This is the single place that turns the binder's validated, adapted plans into
``analyticsAST`` + ``evidenceAST``. It replaces the old lossy path
(``bundle_to_planrecs`` → ``run_analytics``) which dropped ``formulaSpec`` /
``normalizationPlan`` / lineage. The coordinator consumes the full
:class:`AdaptedPlan` and routes each unit by what it actually needs:

    AdaptedPlan
      → normalize_exec        (only when normalizationPlan.type != NONE)
      → formula_exec          (SHARE/RATE/RATIO/GROWTH/CAGR/INDEX/DIFFERENCE,
                               and DIRECT with a reported_value aggregation)
      → run_analytics         (DIRECT / simple physical aggregation)
      → merged analyticsAST + evidenceAST + row_index

Doctrine: the binder decides WHAT (it already did); the coordinator only routes
HOW. It never reinterprets a question, never softens a BLOCKED plan into a number,
and keeps the output byte-compatible with the physical executor for the DIRECT
case (a per-plan ``run_analytics`` call is exactly one iteration of its loop, so a
DIRECT-only bundle yields the same ASTs as before).

The public :func:`run_execution` returns the same ``(AnalyticsAST, EvidenceAST,
row_index)`` triple as ``run_analytics`` — a drop-in for the API. The richer
:func:`run_execution_detailed` additionally exposes per-plan routing + degrade
diagnostics for the future verifier / observability, without changing the triple.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from report_builder.generation.bundle_adapter import AdaptedPlan
from report_builder.generation.config import GenerationConfig, load_profile
from report_builder.generation.executor import run_analytics
from report_builder.generation.formula_exec import compute_formula
from report_builder.generation.normalize_exec import apply_normalization
from report_builder.generation.schema import (
    AnalyticsAST,
    EvidenceAST,
    ExecutionRec,
)

logger = logging.getLogger(__name__)

# Formula families that must be computed by ``formula_exec`` (the physical executor
# has no expression evaluator). DIRECT is physical *unless* its aggregation is the
# deterministic ``reported_value`` collapse, which formula_exec owns (profile policy).
_FORMULA_TYPES = {"SHARE", "RATE", "RATIO", "GROWTH", "CAGR", "INDEX", "DIFFERENCE"}

# Plan statuses the coordinator will execute (BLOCKED is refused, never softened).
_RUNNABLE = {"EXECUTABLE", "DEGRADED"}

# Map a formula/normalize status → a controlled ExecutionRec status (EXEC_STATUSES).
# A degraded plan still produced a value, so its execution is "ok"; the degrade is
# preserved in the PlanOutcome diagnostics, not hidden, but the AST stays valid.
_EXEC_STATUS = {
    "ok": "ok",
    "degraded": "ok",
    "empty": "empty",
    "blocked": "skipped",
    "error": "error",
    "skipped": "skipped",
}


@dataclass
class PlanOutcome:
    """Per-plan routing + result record (observability; not part of the gold ASTs)."""

    planId: str
    questionId: str
    engine: str                       # "pandas" | "formula:<TYPE>" | "skipped"
    status: str                       # ok | degraded | empty | blocked | error | skipped
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "planId": self.planId,
            "questionId": self.questionId,
            "engine": self.engine,
            "status": self.status,
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class CoordinatorResult:
    """The merged ASTs plus per-plan routing/degrade trace."""

    analytics: AnalyticsAST
    evidence: EvidenceAST
    row_index: dict[str, list[int]] = field(default_factory=dict)
    outcomes: list[PlanOutcome] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def as_tuple(self) -> tuple[AnalyticsAST, EvidenceAST, dict[str, list[int]]]:
        return self.analytics, self.evidence, self.row_index


# ─────────────────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────────────────


def _needs_formula_exec(plan: AdaptedPlan) -> bool:
    """True when this plan must be computed by ``formula_exec`` rather than physically."""
    ftype = (plan.formulaSpec.type or "DIRECT").upper()
    if ftype in _FORMULA_TYPES:
        return True
    if (plan.planRec.measure.agg or "").lower() == "reported_value":
        return True
    return False


def _merge_analytics(dst: AnalyticsAST, src: AnalyticsAST) -> None:
    dst.plans.extend(src.plans)
    dst.executions.extend(src.executions)
    dst.aggregations.extend(src.aggregations)
    dst.rankings.extend(src.rankings)
    dst.trends.extend(src.trends)
    dst.metrics.extend(src.metrics)


# ─────────────────────────────────────────────────────────────────────────────
# Coordinator
# ─────────────────────────────────────────────────────────────────────────────


def run_execution_detailed(
    adapted: list[AdaptedPlan],
    df: pd.DataFrame,
    *,
    question_meta: dict[str, dict[str, Any]] | None = None,
    profile: GenerationConfig | None = None,
) -> CoordinatorResult:
    """Execute every adapted plan and merge into one analyticsAST + evidenceAST.

    Each plan is, in order: refused if not runnable (BLOCKED), reshaped by
    ``normalize_exec`` when its ``normalizationPlan`` is not NONE, then routed to
    ``formula_exec`` or the physical ``run_analytics`` and merged. Per-plan routing
    and degrade diagnostics are recorded on the returned :class:`CoordinatorResult`.
    """
    profile = profile or load_profile()
    question_meta = question_meta or {}
    base = df.reset_index(drop=True) if df is not None else pd.DataFrame()

    analytics = AnalyticsAST()
    evidence = EvidenceAST()
    row_index: dict[str, list[int]] = {}
    outcomes: list[PlanOutcome] = []
    all_diags: list[str] = []

    for plan in adapted:
        qid = plan.questionId or plan.planRec.questionId
        plan_id = plan.planRec.planId
        diags: list[str] = []

        # 1. Refuse a non-runnable plan (defensive — the adapter should not emit BLOCKED).
        if (plan.status or "").upper() not in _RUNNABLE:
            analytics.plans.append(plan.planRec)
            analytics.executions.append(ExecutionRec(
                executionId=f"exec_{qid}", planRef=plan_id, engine="skipped",
                rowsScanned=0, ms=0, status="skipped",
            ))
            outcomes.append(PlanOutcome(plan_id, qid, "skipped", "blocked",
                                        [f"plan status {plan.status} — refused"]))
            all_diags.append(f"{plan_id}: refused ({plan.status})")
            continue

        # 2. Normalize first when the plan asks for a reshape.
        frame = base
        if (plan.normalizationPlan.type or "NONE").upper() != "NONE":
            nres = apply_normalization(plan, base)
            frame = nres.frame
            diags.extend(nres.diagnostics)

        # 3. Route by formula need.
        t0 = time.perf_counter()
        if _needs_formula_exec(plan):
            ftype = (plan.formulaSpec.type or "DIRECT").upper()
            fres = compute_formula(plan, frame, profile=profile)
            analytics.plans.append(plan.planRec)
            analytics.aggregations.extend(fres.aggregations)
            analytics.rankings.extend(fres.rankings)
            analytics.trends.extend(fres.trends)
            analytics.metrics.extend(fres.metrics)
            evidence.evidence.extend(fres.evidence)
            row_index.update(fres.row_index)
            ms = int((time.perf_counter() - t0) * 1000)
            analytics.executions.append(ExecutionRec(
                executionId=f"exec_{qid}", planRef=plan_id, engine="formula",
                rowsScanned=int(len(frame)), ms=ms, status=_EXEC_STATUS.get(fres.status, "ok"),
            ))
            diags.extend(fres.diagnostics)
            outcomes.append(PlanOutcome(plan_id, qid, f"formula:{ftype}", fres.status, diags))
        else:
            a, e, ri = run_analytics([plan.planRec], frame, question_meta=question_meta)
            _merge_analytics(analytics, a)
            evidence.evidence.extend(e.evidence)
            row_index.update(ri)
            status = a.executions[0].status if a.executions else "empty"
            outcomes.append(PlanOutcome(plan_id, qid, "pandas", status, diags))

        all_diags.extend(f"{plan_id}: {d}" for d in diags)

    logger.info(
        "[coordinator] executed %d plan(s) → %d agg / %d rank / %d trend / %d metric (%d degraded-diag)",
        len(adapted), len(analytics.aggregations), len(analytics.rankings),
        len(analytics.trends), len(analytics.metrics), len(all_diags),
    )
    return CoordinatorResult(analytics, evidence, row_index, outcomes, all_diags)


def run_execution(
    adapted: list[AdaptedPlan],
    df: pd.DataFrame,
    *,
    question_meta: dict[str, dict[str, Any]] | None = None,
    profile: GenerationConfig | None = None,
) -> tuple[AnalyticsAST, EvidenceAST, dict[str, list[int]]]:
    """Drop-in for ``run_analytics``: returns ``(analyticsAST, evidenceAST, row_index)``.

    Routes through the coordinator (normalize → formula/physical) and discards the
    per-plan trace. Use :func:`run_execution_detailed` when you need routing/diagnostics.
    """
    return run_execution_detailed(
        adapted, df, question_meta=question_meta, profile=profile,
    ).as_tuple()
