"""Generation phase (S4–S6) — dataset + bindingAST → ③ report.output.ast.json.

The third leg of the pipeline. Consumes the value-free template (①②) and the
confirmed binding (datasetAST + bindingAST) and produces the only artifact that
carries real values and prose, with full row-level provenance.

Sub-stages:

    S4  analytics   planner_adapter → executor → analyticsAST + evidenceAST
    S5  fill         filler (tables/charts/metrics) + narrator (prose)
    S6  assemble     assembler → report.output.ast.json  (+ render)

Offline-first: analytics is fully deterministic; only the narrative's optional
top tier calls an LLM, and every number it emits is re-validated against
evidenceAST before it is accepted.
"""
from __future__ import annotations

from .schema import (
    Aggregation,
    AggregationRow,
    AnalyticsAST,
    AnalyticsPlanRec,
    Evidence,
    EvidenceAST,
    ExecutionRec,
    GenerationTrace,
    Metric,
    PlanMeasure,
    Ranking,
    RankingItem,
    StageTrace,
    Trend,
    TrendPoint,
)
from .planner_adapter import build_plan, build_plans
from .executor import run_analytics
from .coordinator import (
    CoordinatorResult,
    PlanOutcome,
    run_execution,
    run_execution_detailed,
)
from .run_modes import (
    DataDriftError,
    GENERATION_MODES,
    attach_data_hash,
    bundle_data_hash,
    compute_data_content_hash,
    resolve_mode,
    verify_data_hash,
)
from .filler import fill_visuals
from .narrator import narrate, validate_numbers
from .assembler import assemble_report, validate_report
from .verifier import (
    VerificationCheck,
    VerificationReport,
    VerifierPolicy,
    verify_report,
)
from .lineage import (
    LineageEntry,
    MeasuredValue,
    build_lineage_index,
    enrich_report_provenance,
    iter_measured_values,
    provenance_coverage,
)
from .insights import (
    Insight,
    attach_insights,
    derive_insights,
    key_findings,
)
from .renderer import render_html, render_pdf
from .render.pdf import pdf_available
from .profile import (
    TemplateProfile,
    ReportOverrides,
    deep_merge,
    effective_profile,
    apply_profile,
    render_flags,
)
from .edit import (
    apply_edit,
    bump_version,
    current_version,
    EditRejected,
)

__all__ = [
    "build_plan",
    "build_plans",
    "run_analytics",
    "run_execution",
    "run_execution_detailed",
    "CoordinatorResult",
    "PlanOutcome",
    "DataDriftError",
    "GENERATION_MODES",
    "attach_data_hash",
    "bundle_data_hash",
    "compute_data_content_hash",
    "resolve_mode",
    "verify_data_hash",
    "fill_visuals",
    "narrate",
    "validate_numbers",
    "assemble_report",
    "validate_report",
    "verify_report",
    "VerificationCheck",
    "VerificationReport",
    "VerifierPolicy",
    "enrich_report_provenance",
    "build_lineage_index",
    "iter_measured_values",
    "provenance_coverage",
    "LineageEntry",
    "MeasuredValue",
    "derive_insights",
    "attach_insights",
    "key_findings",
    "Insight",
    "render_html",
    "render_pdf",
    "pdf_available",
    "TemplateProfile",
    "ReportOverrides",
    "deep_merge",
    "effective_profile",
    "apply_profile",
    "render_flags",
    "apply_edit",
    "bump_version",
    "current_version",
    "EditRejected",
    "Aggregation",
    "AggregationRow",
    "AnalyticsAST",
    "AnalyticsPlanRec",
    "Evidence",
    "EvidenceAST",
    "ExecutionRec",
    "GenerationTrace",
    "Metric",
    "PlanMeasure",
    "Ranking",
    "RankingItem",
    "StageTrace",
    "Trend",
    "TrendPoint",
]
