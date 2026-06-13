"""S3.5 — Execution Readiness Gate.

3-level validation ensuring S4 never discovers basic binding errors:

1. Technical: columns exist, dtypes support operation, filters resolve
2. Statistical: unit compatibility, aggregation valid, rates not blindly summed
3. Evidence: source table known, lineage available

Severity controls bundle status:
    severity=error → plan BLOCKED, bundle NOT_READY
    severity=warn  → plan DEGRADED, bundle DEGRADED
    severity=info  → plan unchanged, bundle READY with notes

Returns ExecutionReadinessReport with per-plan diagnostics.
"""
from __future__ import annotations

import logging
from typing import Any

from report_builder.binding.execution_contracts import (
    ExecutionReadinessReport,
    QuestionExecutionPlan,
    ReadinessCheck,
)
from report_builder.binding.schema import DatasetAST

logger = logging.getLogger(__name__)


def validate_execution_ready(
    plans: list[QuestionExecutionPlan],
    dataset: DatasetAST,
) -> ExecutionReadinessReport:
    """Validate all plans against dataset. Returns readiness report.

    Severity determines plan fate:
        severity=error → BLOCKED (cannot execute)
        severity=warn  → DEGRADED (can execute with caveats)
        severity=info  → informational, no status change
    """
    report = ExecutionReadinessReport()
    all_column_names = {c.name for c in dataset.columns}
    measure_columns = {c.name for c in dataset.columns if c.role == "measure"}
    dimension_columns = {c.name for c in dataset.columns if c.role == "dimension"}
    units_map = {c.name: c.unit for c in dataset.columns if c.unit}

    for plan in plans:
        plan_checks: list[ReadinessCheck] = []

        # ═══════════════════════════════════════════════════════════════════════
        # Level 1: TECHNICAL READINESS (severity=error → BLOCKED)
        # ═══════════════════════════════════════════════════════════════════════

        # Check measure columns exist
        for col in plan.resolvedRoles.measures:
            if col not in all_column_names:
                plan_checks.append(ReadinessCheck(
                    level="technical", severity="error", passed=False,
                    code="MEASURE_COLUMN_MISSING",
                    message=f"Measure column '{col}' not found in dataset",
                    planId=plan.planId,
                    recommendedAction="Re-resolve entity binding or fix column reference",
                ))
                plan.status = "BLOCKED"
                plan.diagnostics.append(f"BLOCKED: measure '{col}' missing")

        # Check dimension columns exist
        for col in plan.resolvedRoles.dimensions:
            if col not in all_column_names:
                plan_checks.append(ReadinessCheck(
                    level="technical", severity="error", passed=False,
                    code="DIMENSION_COLUMN_MISSING",
                    message=f"Dimension column '{col}' not found in dataset",
                    planId=plan.planId,
                    recommendedAction="Re-resolve entity binding or fix column reference",
                ))
                plan.status = "BLOCKED"
                plan.diagnostics.append(f"BLOCKED: dimension '{col}' missing")

        # Check filter columns exist
        for f in plan.resolvedRoles.filters:
            if f.column not in all_column_names:
                plan_checks.append(ReadinessCheck(
                    level="technical", severity="error", passed=False,
                    code="FILTER_COLUMN_MISSING",
                    message=f"Filter column '{f.column}' not found in dataset",
                    planId=plan.planId,
                    recommendedAction="Re-resolve filter entity or remove filter",
                ))
                plan.status = "BLOCKED"

        # Check formula columns for GROWTH/SHARE/RATIO
        if plan.formulaSpec.type in ("GROWTH", "RATIO", "SHARE", "DIFFERENCE"):
            if plan.formulaSpec.numeratorColumn and plan.formulaSpec.numeratorColumn not in all_column_names:
                plan_checks.append(ReadinessCheck(
                    level="technical", severity="error", passed=False,
                    code="FORMULA_NUMERATOR_MISSING",
                    message=f"Formula numerator '{plan.formulaSpec.numeratorColumn}' not in dataset",
                    planId=plan.planId,
                    recommendedAction="Re-resolve numerator entity",
                ))
                plan.status = "BLOCKED"
            if plan.formulaSpec.denominatorColumn and plan.formulaSpec.denominatorColumn not in all_column_names:
                plan_checks.append(ReadinessCheck(
                    level="technical", severity="error", passed=False,
                    code="FORMULA_DENOMINATOR_MISSING",
                    message=f"Formula denominator '{plan.formulaSpec.denominatorColumn}' not in dataset",
                    planId=plan.planId,
                    recommendedAction="Re-resolve denominator entity",
                ))
                plan.status = "BLOCKED"

        # ═══════════════════════════════════════════════════════════════════════
        # Level 2: STATISTICAL READINESS
        # ═══════════════════════════════════════════════════════════════════════

        # Check: rates/percentages/indices should NOT be summed
        for col in plan.resolvedRoles.measures:
            unit = units_map.get(col, "")
            agg = (plan.analyticsSpec.get("measure") or {}).get("agg", "sum")
            if unit in ("percent", "per_1000", "index", "ratio") and agg == "sum":
                plan_checks.append(ReadinessCheck(
                    level="statistical", severity="warn", passed=False,
                    code="RATE_SUMMED",
                    message=f"Column '{col}' (unit={unit}) should not be summed — use weighted_mean or reported_value",
                    planId=plan.planId,
                    recommendedAction="Use reported_value or weighted_mean aggregation",
                ))
                plan.diagnostics.append(f"WARN: '{col}' is a rate but aggregation is sum")
                if plan.status == "EXECUTABLE":
                    plan.status = "DEGRADED"

        # Check: GROWTH formula requires both current and prior columns
        if plan.formulaSpec.type == "GROWTH":
            if not plan.formulaSpec.numeratorColumn or not plan.formulaSpec.denominatorColumn:
                plan_checks.append(ReadinessCheck(
                    level="statistical", severity="warn", passed=False,
                    code="GROWTH_MISSING_PERIODS",
                    message="GROWTH formula requires both numerator (current) and denominator (prior) columns",
                    planId=plan.planId,
                    recommendedAction="Resolve time periods or add explicit current/prior column binding",
                ))
                if plan.status == "EXECUTABLE":
                    plan.status = "DEGRADED"

        # Check: SHARE/RATE/RATIO requires denominator column — THIS IS A BLOCKING ERROR
        # Cannot compute share/rate/ratio without knowing what the denominator is.
        # Sending to S4 without denominator would produce wrong numbers.
        if plan.formulaSpec.type in ("SHARE", "RATE", "RATIO"):
            if not plan.formulaSpec.denominatorColumn:
                plan_checks.append(ReadinessCheck(
                    level="statistical", severity="error", passed=False,
                    code="FORMULA_MISSING_DENOMINATOR",
                    message=f"{plan.formulaSpec.type} formula requires a denominator column — cannot execute without it",
                    planId=plan.planId,
                    recommendedAction="Add denominator entity binding or change formula to DIRECT",
                ))
                plan.status = "BLOCKED"
                plan.diagnostics.append(f"BLOCKED: {plan.formulaSpec.type} missing denominator")

        # Check: CAGR requires time periods + start/end
        if plan.formulaSpec.type == "CAGR":
            if not plan.formulaSpec.timeWindow:
                plan_checks.append(ReadinessCheck(
                    level="statistical", severity="error", passed=False,
                    code="CAGR_MISSING_TIME_WINDOW",
                    message="CAGR formula requires timeWindow with start/end periods",
                    planId=plan.planId,
                    recommendedAction="Resolve time column and provide start/end periods",
                ))
                plan.status = "BLOCKED"

        # Check: INDEX requires baseValue
        if plan.formulaSpec.type == "INDEX":
            if plan.formulaSpec.baseValue is None:
                plan_checks.append(ReadinessCheck(
                    level="statistical", severity="error", passed=False,
                    code="INDEX_MISSING_BASE",
                    message="INDEX formula requires baseValue",
                    planId=plan.planId,
                    recommendedAction="Provide base year value for index calculation",
                ))
                plan.status = "BLOCKED"

        # Check: dimension column has enough cardinality for groupBy
        for col in plan.resolvedRoles.dimensions:
            col_profile = dataset.column(col)
            if col_profile and col_profile.cardinality < 2:
                plan_checks.append(ReadinessCheck(
                    level="statistical", severity="info", passed=False,
                    code="LOW_CARDINALITY_GROUPBY",
                    message=f"Dimension '{col}' has cardinality {col_profile.cardinality} — groupBy won't produce useful results",
                    planId=plan.planId,
                    recommendedAction="Consider removing groupBy or using a higher-cardinality column",
                ))

        # Check: output contract requires chart but no dimension exists
        output_components = (plan.outputContract.get("components") or [])
        has_chart_component = any(c.get("kind") == "chart" for c in output_components)
        if has_chart_component and not plan.resolvedRoles.dimensions:
            plan_checks.append(ReadinessCheck(
                level="statistical", severity="warn", passed=False,
                code="CHART_MISSING_DIMENSION",
                message="Output contract requires chart but no dimension column is resolved for groupBy/xAxis",
                planId=plan.planId,
                recommendedAction="Add a dimension entity binding for chart axis",
            ))
            if plan.status == "EXECUTABLE":
                plan.status = "DEGRADED"

        # Check: normalization plan is executable
        norm_type = plan.normalizationPlan.type
        if norm_type == "WIDE_TO_LONG" and not plan.normalizationPlan.idVars:
            plan_checks.append(ReadinessCheck(
                level="technical", severity="warn", passed=False,
                code="NORMALIZATION_INCOMPLETE",
                message="WIDE_TO_LONG normalization requires idVars to be specified",
                planId=plan.planId,
                recommendedAction="Specify dimension columns as idVars for melt operation",
            ))
            if plan.status == "EXECUTABLE":
                plan.status = "DEGRADED"
        if norm_type == "DERIVE_COLUMN" and not plan.normalizationPlan.expression:
            plan_checks.append(ReadinessCheck(
                level="technical", severity="error", passed=False,
                code="DERIVE_MISSING_EXPRESSION",
                message="DERIVE_COLUMN normalization requires an expression",
                planId=plan.planId,
                recommendedAction="Provide derivation expression (e.g., 'col_a / col_b * 100')",
            ))
            plan.status = "BLOCKED"
        if norm_type in ("JOIN", "UNION") and not plan.normalizationPlan.joinKey:
            plan_checks.append(ReadinessCheck(
                level="technical", severity="error", passed=False,
                code="JOIN_MISSING_KEY",
                message=f"{norm_type} normalization requires joinKey columns",
                planId=plan.planId,
                recommendedAction="Specify join key columns shared between primary and secondary data",
            ))
            plan.status = "BLOCKED"

        # ═══════════════════════════════════════════════════════════════════════
        # Level 3: EVIDENCE READINESS (severity=info for missing evidence)
        # ═══════════════════════════════════════════════════════════════════════

        # Check lineage completeness
        if not plan.lineage.sourceColumnIds:
            plan_checks.append(ReadinessCheck(
                level="evidence", severity="info", passed=False,
                code="LINEAGE_MISSING_COLUMNS",
                message="No source columns in lineage — evidence traceability incomplete",
                planId=plan.planId,
                recommendedAction="Ensure entity bindings populate lineage source columns",
            ))

        if not plan.lineage.sourceQuestionId:
            plan_checks.append(ReadinessCheck(
                level="evidence", severity="info", passed=False,
                code="LINEAGE_MISSING_QUESTION",
                message="No source question in lineage",
                planId=plan.planId,
                recommendedAction="Link plan back to blueprint question ID",
            ))

        # Record all checks
        report.checks.extend(plan_checks)

    # ═══════════════════════════════════════════════════════════════════════════
    # AGGREGATE: severity controls bundle classification
    # ═══════════════════════════════════════════════════════════════════════════

    report.executableCount = sum(1 for p in plans if p.status == "EXECUTABLE")
    report.degradedCount = sum(1 for p in plans if p.status == "DEGRADED")
    report.blockedCount = sum(1 for p in plans if p.status == "BLOCKED")

    # Severity-based classification (canonical — no fallback)
    report.errors = [c.message for c in report.checks if not c.passed and c.severity == "error"]
    report.warnings = [c.message for c in report.checks if not c.passed and c.severity == "warn"]
    # Info-level are informational — not surfaced as warnings but available in checks[]

    logger.info(
        "[readiness_gate] %d plans validated: %d executable, %d degraded, %d blocked | %d errors, %d warnings",
        len(plans), report.executableCount, report.degradedCount, report.blockedCount,
        len(report.errors), len(report.warnings),
    )
    return report
