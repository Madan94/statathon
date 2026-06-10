"""Tests for the gold ExecutionBundle → generation plans adapter.

Proves the gold-conformance contract for Phase 2:
- generation plans are sourced from `ExecutionBundle.plans` (no blueprint/BindingAST rebuild)
- multi-measure questions fan out with stable identity `plan_<qid>__<measure_slug>`
- BLOCKED plans are never emitted; DEGRADED are included (gated by flag)
- formulaSpec / normalizationPlan / outputContract / per-measure lineage are preserved
- aggregations (incl. `reported_value`) are carried faithfully, not silently rewritten
"""
from __future__ import annotations

import pytest

from report_builder.binding.execution_contracts import (
    ExecutionBundle,
    FormulaSpec,
    LineageRef,
    NormalizationPlan,
    QuestionExecutionPlan,
)
from report_builder.binding.schema import ResolvedFilter, ResolvedRoles, ResolvedTime
from report_builder.generation.bundle_adapter import (
    AdaptedPlan,
    adapt_bundle,
    adapt_plan,
    bundle_to_planrecs,
)
from report_builder.generation.schema import AnalyticsPlanRec


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _qplan(
    *,
    qid: str,
    status: str = "EXECUTABLE",
    measures: list[str],
    dimensions: list[str] | None = None,
    operation: str = "group_aggregate",
    agg: str = "sum",
    filters: list[ResolvedFilter] | None = None,
    formula: FormulaSpec | None = None,
    normalization: NormalizationPlan | None = None,
    output_components: list[dict] | None = None,
    time_col: str | None = None,
) -> QuestionExecutionPlan:
    spec = {
        "operation": operation,
        "measure": {"column": measures[0] if measures else "", "agg": agg, "unit": ""},
        "groupBy": [{"column": d} for d in (dimensions or [])],
        "filters": [{"column": f.column, "op": f.op, "value": f.value} for f in (filters or [])],
        "sort": {"by": "measure", "order": "desc"},
        "topN": None,
    }
    roles = ResolvedRoles(
        measures=list(measures),
        dimensions=list(dimensions or []),
        filters=list(filters or []),
        time=ResolvedTime(column=time_col) if time_col else ResolvedTime(),
    )
    return QuestionExecutionPlan(
        planId=f"plan_{qid}",
        questionId=qid,
        status=status,
        analyticsSpec=spec,
        resolvedRoles=roles,
        formulaSpec=formula or FormulaSpec(type="DIRECT"),
        normalizationPlan=normalization or NormalizationPlan(type="NONE"),
        outputContract={"components": output_components or []},
        lineage=LineageRef(sourceQuestionId=qid, sourceColumnIds=list(measures)),
    )


def _bundle(*plans: QuestionExecutionPlan, status: str = "READY") -> ExecutionBundle:
    return ExecutionBundle(templateId="tpl_t", datasetId="ds_1", status=status, plans=list(plans))


# ─────────────────────────────────────────────────────────────────────────────
# Bundle-sourced (not rebuilt) + shape
# ─────────────────────────────────────────────────────────────────────────────

class TestBundleIsTheSource:
    def test_planrec_taken_from_bundle_no_blueprint_needed(self):
        """The adapter needs ONLY the bundle — no blueprint/BindingAST rebuild."""
        qp = _qplan(qid="q_lfpr", measures=["LFPR"], dimensions=["State_UT"], agg="mean")
        recs = bundle_to_planrecs(_bundle(qp))
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec, AnalyticsPlanRec)
        # values come straight from the plan's analyticsSpec / resolvedRoles
        assert rec.questionId == "q_lfpr"
        assert rec.measure.columnExpr == "LFPR"
        assert rec.measure.agg == "mean"
        assert rec.groupBy == ["State_UT"]
        assert rec.operation == "group_aggregate"

    def test_reported_value_agg_carried_faithfully(self):
        """`reported_value` must survive the mapping (no silent rewrite to mean)."""
        qp = _qplan(qid="q_ur", measures=["UR"], dimensions=["State_UT"], agg="reported_value")
        rec = bundle_to_planrecs(_bundle(qp))[0]
        assert rec.measure.agg == "reported_value"

    def test_weight_column_from_formulaspec(self):
        qp = _qplan(qid="q_w", measures=["wage"], dimensions=["sector"], agg="weighted_mean",
                    formula=FormulaSpec(type="DIRECT", weightColumn="mult"))
        rec = bundle_to_planrecs(_bundle(qp))[0]
        assert rec.measure.weightColumn == "mult"

    def test_filters_rendered_and_filterapplied_respected(self):
        applied = ResolvedFilter(column="age", op="ge", value=15, filterApplied=True)
        widened = ResolvedFilter(column="sector", op="eq", value="Rural", filterApplied=False)
        qp = _qplan(qid="q_f", measures=["LFPR"], dimensions=["State_UT"],
                    filters=[applied, widened])
        rec = bundle_to_planrecs(_bundle(qp))[0]
        assert "age>=15" in rec.filters
        assert not any("sector" in f for f in rec.filters), "widened filter must be dropped"


# ─────────────────────────────────────────────────────────────────────────────
# Multi-measure fan-out + stable identity
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiMeasureFanout:
    def test_four_measures_fan_out_with_stable_ids(self):
        qp = _qplan(
            qid="q_coal_composition",
            measures=["Proved_Reserves", "Indicated_Reserves", "Inferred_Reserves", "Total_Reserves"],
            dimensions=["State"],
            agg="sum",
        )
        adapted = adapt_plan(qp)
        assert len(adapted) == 4
        ids = [a.planRec.planId for a in adapted]
        assert ids == [
            "plan_q_coal_composition__proved_reserves",
            "plan_q_coal_composition__indicated_reserves",
            "plan_q_coal_composition__inferred_reserves",
            "plan_q_coal_composition__total_reserves",
        ]
        # each carries its own measure + flag
        for a in adapted:
            assert a.fannedOut is True
            assert a.planRec.measure.columnExpr == a.measureColumn
            assert a.measureSlug and a.measureSlug in a.planRec.planId

    def test_fanned_lineage_is_per_measure(self):
        qp = _qplan(
            qid="q_x", measures=["A_val", "B_val"], dimensions=["State"],
            filters=[ResolvedFilter(column="Year", op="eq", value=2024, filterApplied=True)],
        )
        adapted = adapt_plan(qp)
        a_plan = next(a for a in adapted if a.measureColumn == "A_val")
        b_plan = next(a for a in adapted if a.measureColumn == "B_val")
        # A's lineage has A_val but NOT B_val; shared dims/filters present in both
        assert "A_val" in a_plan.lineage.sourceColumnIds
        assert "B_val" not in a_plan.lineage.sourceColumnIds
        assert "State" in a_plan.lineage.sourceColumnIds
        assert "Year" in a_plan.lineage.sourceColumnIds
        assert "B_val" in b_plan.lineage.sourceColumnIds
        assert "A_val" not in b_plan.lineage.sourceColumnIds

    def test_single_measure_no_fanout_suffix(self):
        qp = _qplan(qid="q_single", measures=["LFPR"], dimensions=["State_UT"])
        adapted = adapt_plan(qp)
        assert len(adapted) == 1
        assert adapted[0].planRec.planId == "plan_q_single"
        assert adapted[0].fannedOut is False

    def test_component_mapping_where_available(self):
        comps = [
            {"componentId": "c_proved", "kind": "table", "label": "Proved Reserves"},
            {"componentId": "c_total", "kind": "table", "column": "Total_Reserves"},
        ]
        qp = _qplan(qid="q_map", measures=["Proved_Reserves", "Total_Reserves"],
                    dimensions=["State"], output_components=comps)
        adapted = adapt_plan(qp)
        proved = next(a for a in adapted if a.measureColumn == "Proved_Reserves")
        total = next(a for a in adapted if a.measureColumn == "Total_Reserves")
        # label-slug match
        assert proved.componentRef == "c_proved"
        assert proved.measureLabel == "Proved Reserves"
        # explicit column match
        assert total.componentRef == "c_total"


# ─────────────────────────────────────────────────────────────────────────────
# Status discipline + metadata preservation
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusAndPreservation:
    def test_blocked_plan_never_emitted(self):
        blocked = _qplan(qid="q_blocked", status="BLOCKED", measures=["x"], dimensions=["d"])
        ok = _qplan(qid="q_ok", measures=["y"], dimensions=["d"])
        adapted = adapt_bundle(_bundle(blocked, ok))
        qids = {a.questionId for a in adapted}
        assert "q_blocked" not in qids
        assert "q_ok" in qids

    def test_degraded_included_by_default_excluded_by_flag(self):
        degraded = _qplan(qid="q_deg", status="DEGRADED", measures=["x"], dimensions=["d"])
        assert len(adapt_bundle(_bundle(degraded))) == 1
        assert len(adapt_bundle(_bundle(degraded), include_degraded=False)) == 0

    def test_formula_and_normalization_preserved(self):
        qp = _qplan(
            qid="q_share", measures=["part"], dimensions=["State"], operation="share",
            formula=FormulaSpec(type="SHARE", numeratorColumn="part", denominatorColumn="whole", multiplier=100.0),
            normalization=NormalizationPlan(type="WIDE_TO_LONG", idVars=["State"]),
        )
        a = adapt_plan(qp)[0]
        assert a.formulaSpec.type == "SHARE"
        assert a.formulaSpec.numeratorColumn == "part"
        assert a.formulaSpec.denominatorColumn == "whole"
        assert a.normalizationPlan.type == "WIDE_TO_LONG"
        # share is a grouped quotient → bucketed as group_aggregate (formula_exec computes later)
        assert a.planRec.operation == "group_aggregate"

    def test_outputcontract_preserved_and_serializable(self):
        comps = [{"componentId": "c1", "kind": "chart"}]
        qp = _qplan(qid="q_oc", measures=["m"], dimensions=["d"], output_components=comps)
        a = adapt_plan(qp)[0]
        assert a.outputContract["components"] == comps
        d = a.to_dict()  # AdaptedPlan must round-trip to a JSON-safe dict
        assert d["outputContract"]["components"] == comps
        assert d["planRec"]["measure"]["columnExpr"] == "m"

    def test_growth_operation_buckets_to_trend(self):
        qp = _qplan(qid="q_g", measures=["Year_2024"], dimensions=["State"], operation="growth",
                    time_col="year",
                    formula=FormulaSpec(type="GROWTH", numeratorColumn="Year_2024", denominatorColumn="Year_2023"))
        a = adapt_plan(qp)[0]
        assert a.planRec.operation == "trend"
        assert a.formulaSpec.type == "GROWTH"
