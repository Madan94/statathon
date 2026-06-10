"""Execution-phase contract schemas — Phase 1 of Binding Contract Compiler.

These dataclasses define the **handoff contract** between the binding team (S0→S3.5)
and the execution team (S4→S6). The binding phase produces an ``ExecutionBundle``;
the execution phase consumes it without interpretation or guessing.

Key principle: every executable plan must know not only WHICH column to use,
but WHAT the number statistically MEANS — unit, period, geography, estimate status,
aggregation rule, formula, source table, and evidence lineage.

Contract version: binding.executionBundle.v1
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from report_builder.binding.schema import (
    BindingAST,
    CoverageReport,
    DatasetAST,
    QuestionBinding,
    ResolvedRoles,
)

# ─────────────────────────────────────────────────────────────────────────────
# Controlled vocabularies
# ─────────────────────────────────────────────────────────────────────────────

CONTRACT_VERSION = "binding.executionBundle.v1"

BUNDLE_STATUSES = ("READY", "NOT_READY", "DEGRADED")

NORMALIZATION_TYPES = (
    "NONE",           # No reshape needed
    "WIDE_TO_LONG",   # Melt year/gender/category columns into rows
    "PIVOT",          # Long→wide for comparison tables
    "JOIN",           # Join two tables on a shared key
    "UNION",          # Stack tables with same schema
    "FILTER_ROWS",    # Remove embedded header/total/footnote rows
    "DERIVE_COLUMN",  # Compute a new column (rate, share, growth)
)

FORMULA_TYPES = (
    "DIRECT",     # Use value as-is (no derivation)
    "SHARE",      # numerator / denominator × 100
    "RATE",       # count / population × multiplier (per 1000, per lakh)
    "GROWTH",     # (current - prior) / prior × 100
    "CAGR",       # (end/start)^(1/n) - 1
    "INDEX",      # value / base_value × 100
    "RATIO",      # numerator / denominator
    "DIFFERENCE", # current - prior (absolute change)
)

READINESS_LEVELS = ("technical", "statistical", "evidence")


# ─────────────────────────────────────────────────────────────────────────────
# NormalizationPlan
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class NormalizationPlan:
    """Describes how raw data must be reshaped before analytics execution.

    For MoSPI tables: wide year columns → melt; state + national → union;
    separate numerator/denominator tables → join.
    """

    type: str = "NONE"                   # one of NORMALIZATION_TYPES
    # WIDE_TO_LONG params
    idVars: list[str] = field(default_factory=list)
    valueVar: str = "value"
    memberVar: str = "member"
    memberLabels: list[str] = field(default_factory=list)
    # JOIN/UNION params
    joinKey: list[str] = field(default_factory=list)
    secondaryDataRef: str = ""           # reference to second table/dataframe
    # DERIVE_COLUMN params
    expression: str = ""                 # e.g., "col_a / col_b * 100"
    outputColumn: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.type == "WIDE_TO_LONG":
            out["idVars"] = list(self.idVars)
            out["valueVar"] = self.valueVar
            out["memberVar"] = self.memberVar
            out["memberLabels"] = list(self.memberLabels)
        elif self.type in ("JOIN", "UNION"):
            out["joinKey"] = list(self.joinKey)
            out["secondaryDataRef"] = self.secondaryDataRef
        elif self.type == "DERIVE_COLUMN":
            out["expression"] = self.expression
            out["outputColumn"] = self.outputColumn
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NormalizationPlan":
        return cls(
            type=str(d.get("type") or "NONE"),
            idVars=list(d.get("idVars") or []),
            valueVar=str(d.get("valueVar") or "value"),
            memberVar=str(d.get("memberVar") or "member"),
            memberLabels=list(d.get("memberLabels") or []),
            joinKey=list(d.get("joinKey") or []),
            secondaryDataRef=str(d.get("secondaryDataRef") or ""),
            expression=str(d.get("expression") or ""),
            outputColumn=str(d.get("outputColumn") or ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# FormulaSpec
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FormulaSpec:
    """Specifies how a derived metric is computed.

    MoSPI reports frequently require SHARE (% distribution), RATE (per 1000),
    GROWTH (YoY change), CAGR, INDEX, and RATIO — none of which are simple sums.
    S4 must not infer formula semantics; S3 must express them explicitly here.
    """

    type: str = "DIRECT"                 # one of FORMULA_TYPES
    numeratorColumn: str = ""            # column for numerator (SHARE, RATE, RATIO)
    denominatorColumn: str = ""          # column for denominator
    timeWindow: dict[str, Any] = field(default_factory=dict)  # {current, prior, periods}
    weightColumn: str | None = None      # for weighted aggregation (population weights)
    multiplier: float = 1.0              # e.g., 100 for percent, 1000 for per-1000
    unitConversion: str | None = None    # target unit after formula application
    baseValue: float | None = None       # for INDEX type (base year value)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.numeratorColumn:
            out["numeratorColumn"] = self.numeratorColumn
        if self.denominatorColumn:
            out["denominatorColumn"] = self.denominatorColumn
        if self.timeWindow:
            out["timeWindow"] = dict(self.timeWindow)
        if self.weightColumn:
            out["weightColumn"] = self.weightColumn
        if self.multiplier != 1.0:
            out["multiplier"] = self.multiplier
        if self.unitConversion:
            out["unitConversion"] = self.unitConversion
        if self.baseValue is not None:
            out["baseValue"] = self.baseValue
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FormulaSpec":
        return cls(
            type=str(d.get("type") or "DIRECT"),
            numeratorColumn=str(d.get("numeratorColumn") or ""),
            denominatorColumn=str(d.get("denominatorColumn") or ""),
            timeWindow=dict(d.get("timeWindow") or {}),
            weightColumn=d.get("weightColumn"),
            multiplier=float(d.get("multiplier") or 1.0),
            unitConversion=d.get("unitConversion"),
            baseValue=d.get("baseValue"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# StatisticalContext
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StatisticalContext:
    """MoSPI-specific metadata that travels with the execution bundle.

    In MoSPI reports, meaning often lives outside the cell: in table titles,
    spanning headers, unit notes, footnotes, source notes, and chapter context.
    This captures that context for S4-S6 to use during execution and evidence.
    """

    geographyLevel: str = ""            # state_ut | district | all_india | rural_urban
    timeCoverage: list[str] = field(default_factory=list)  # ["2023-24", "2024-25"]
    unitRegistry: dict[str, str] = field(default_factory=dict)  # columnId → unit
    sourceNotes: list[str] = field(default_factory=list)    # ["NSS 80th Round", "PLFS 2024-25"]
    footnotes: list[str] = field(default_factory=list)      # ["Excludes Assam", "Provisional"]
    estimateStatus: str = ""            # quick | provisional | revised | final
    surveyRound: str = ""               # "NSS 80th Round", "PLFS Annual 2024-25"
    referenceDate: str = ""             # "As on 31.03.2025", "January-December 2025"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.geographyLevel:
            out["geographyLevel"] = self.geographyLevel
        if self.timeCoverage:
            out["timeCoverage"] = list(self.timeCoverage)
        if self.unitRegistry:
            out["unitRegistry"] = dict(self.unitRegistry)
        if self.sourceNotes:
            out["sourceNotes"] = list(self.sourceNotes)
        if self.footnotes:
            out["footnotes"] = list(self.footnotes)
        if self.estimateStatus:
            out["estimateStatus"] = self.estimateStatus
        if self.surveyRound:
            out["surveyRound"] = self.surveyRound
        if self.referenceDate:
            out["referenceDate"] = self.referenceDate
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StatisticalContext":
        return cls(
            geographyLevel=str(d.get("geographyLevel") or ""),
            timeCoverage=list(d.get("timeCoverage") or []),
            unitRegistry=dict(d.get("unitRegistry") or {}),
            sourceNotes=list(d.get("sourceNotes") or []),
            footnotes=list(d.get("footnotes") or []),
            estimateStatus=str(d.get("estimateStatus") or ""),
            surveyRound=str(d.get("surveyRound") or ""),
            referenceDate=str(d.get("referenceDate") or ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# LineageRef
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class LineageRef:
    """Provenance for one execution plan — traces from question back to source.

    Enables S6 to assemble evidenceAST without re-inferring provenance.
    """

    sourceQuestionId: str = ""
    sourceEntityIds: list[str] = field(default_factory=list)
    sourceColumnIds: list[str] = field(default_factory=list)
    sourceTableId: str = ""             # which extracted table this comes from
    headerPaths: list[list[str]] = field(default_factory=list)  # hierarchical header context
    transformations: list[str] = field(default_factory=list)    # ["melt", "filter:Rural"]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "sourceQuestionId": self.sourceQuestionId,
            "sourceEntityIds": list(self.sourceEntityIds),
            "sourceColumnIds": list(self.sourceColumnIds),
        }
        if self.sourceTableId:
            out["sourceTableId"] = self.sourceTableId
        if self.headerPaths:
            out["headerPaths"] = [list(p) for p in self.headerPaths]
        if self.transformations:
            out["transformations"] = list(self.transformations)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LineageRef":
        return cls(
            sourceQuestionId=str(d.get("sourceQuestionId") or ""),
            sourceEntityIds=list(d.get("sourceEntityIds") or []),
            sourceColumnIds=list(d.get("sourceColumnIds") or []),
            sourceTableId=str(d.get("sourceTableId") or ""),
            headerPaths=[list(p) for p in (d.get("headerPaths") or [])],
            transformations=list(d.get("transformations") or []),
        )


# ─────────────────────────────────────────────────────────────────────────────
# QuestionExecutionPlan
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class QuestionExecutionPlan:
    """A fully-specified execution instruction for one question.

    This is what S4 receives. It contains EVERYTHING needed to execute
    the analytics without interpretation: columns, aggregation, formula,
    normalization, output shape, and evidence requirements.
    """

    planId: str = ""
    questionId: str = ""
    questionText: str = ""
    status: str = "EXECUTABLE"          # EXECUTABLE | DEGRADED | BLOCKED

    # What to compute
    analyticsSpec: dict[str, Any] = field(default_factory=dict)
    resolvedRoles: ResolvedRoles = field(default_factory=ResolvedRoles)
    normalizationPlan: NormalizationPlan = field(default_factory=NormalizationPlan)
    formulaSpec: FormulaSpec = field(default_factory=FormulaSpec)

    # What shape to produce
    outputContract: dict[str, Any] = field(default_factory=dict)

    # What evidence to return
    evidenceRequirements: dict[str, Any] = field(default_factory=lambda: {
        "returnRowIds": True,
        "returnComputedValues": True,
        "traceToSource": True,
    })

    # Provenance
    lineage: LineageRef = field(default_factory=LineageRef)

    # Diagnostics (populated by S3.5 readiness gate)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "planId": self.planId,
            "questionId": self.questionId,
            "questionText": self.questionText,
            "status": self.status,
            "analyticsSpec": dict(self.analyticsSpec),
            "resolvedRoles": self.resolvedRoles.to_dict(),
            "normalizationPlan": self.normalizationPlan.to_dict(),
            "formulaSpec": self.formulaSpec.to_dict(),
            "outputContract": dict(self.outputContract),
            "evidenceRequirements": dict(self.evidenceRequirements),
            "lineage": self.lineage.to_dict(),
            "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QuestionExecutionPlan":
        return cls(
            planId=str(d.get("planId") or ""),
            questionId=str(d.get("questionId") or ""),
            questionText=str(d.get("questionText") or ""),
            status=str(d.get("status") or "EXECUTABLE"),
            analyticsSpec=dict(d.get("analyticsSpec") or {}),
            resolvedRoles=ResolvedRoles.from_dict(d.get("resolvedRoles") or {}),
            normalizationPlan=NormalizationPlan.from_dict(d.get("normalizationPlan") or {}),
            formulaSpec=FormulaSpec.from_dict(d.get("formulaSpec") or {}),
            outputContract=dict(d.get("outputContract") or {}),
            evidenceRequirements=dict(d.get("evidenceRequirements") or {"returnRowIds": True, "returnComputedValues": True, "traceToSource": True}),
            lineage=LineageRef.from_dict(d.get("lineage") or {}),
            diagnostics=list(d.get("diagnostics") or []),
        )


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionReadinessReport
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ReadinessCheck:
    """One readiness check result."""

    level: str = "technical"            # one of READINESS_LEVELS
    severity: str = "error"             # error | warn | info
    passed: bool = True
    code: str = ""
    message: str = ""
    planId: str = ""
    recommendedAction: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "level": self.level,
            "severity": self.severity,
            "passed": self.passed,
            "code": self.code,
            "message": self.message,
            "planId": self.planId,
        }
        if self.recommendedAction:
            out["recommendedAction"] = self.recommendedAction
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReadinessCheck":
        return cls(
            level=str(d.get("level") or "technical"),
            severity=str(d.get("severity") or "error"),
            passed=bool(d.get("passed", True)),
            code=str(d.get("code") or ""),
            message=str(d.get("message") or ""),
            planId=str(d.get("planId") or ""),
            recommendedAction=str(d.get("recommendedAction") or ""),
        )


@dataclass
class ExecutionReadinessReport:
    """3-level readiness gate output: technical + statistical + evidence.

    S4 should ONLY receive plans that pass all three levels.
    """

    executableCount: int = 0
    degradedCount: int = 0
    blockedCount: int = 0
    checks: list[ReadinessCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        """True if at least one plan is executable and no critical errors."""
        return self.executableCount > 0 and len(self.errors) == 0

    @property
    def status(self) -> str:
        if self.errors:
            return "NOT_READY"
        if self.degradedCount > 0:
            return "DEGRADED"
        return "READY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "executableCount": self.executableCount,
            "degradedCount": self.degradedCount,
            "blockedCount": self.blockedCount,
            "checks": [c.to_dict() for c in self.checks],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExecutionReadinessReport":
        return cls(
            executableCount=int(d.get("executableCount") or 0),
            degradedCount=int(d.get("degradedCount") or 0),
            blockedCount=int(d.get("blockedCount") or 0),
            checks=[ReadinessCheck.from_dict(c) for c in (d.get("checks") or [])],
            warnings=list(d.get("warnings") or []),
            errors=list(d.get("errors") or []),
        )


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionBundle — THE final handoff artifact
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ExecutionBundle:
    """The versioned, immutable, validated handoff artifact from binding to execution.

    This is the ONLY thing the S4 team consumes. It contains everything needed
    to execute all questions without guessing, interpretation, or re-resolution.

    Contract: binding.executionBundle.v1
    """

    contractVersion: str = CONTRACT_VERSION
    templateId: str = ""
    datasetId: str = ""
    bindingAstId: str = ""
    status: str = "NOT_READY"           # one of BUNDLE_STATUSES

    # Core artifacts
    datasetAst: DatasetAST = field(default_factory=DatasetAST)
    bindingAst: BindingAST = field(default_factory=BindingAST)

    # MoSPI statistical context (travels with the bundle)
    statisticalContext: StatisticalContext = field(default_factory=StatisticalContext)

    # Execution plans (one per executable/degraded question)
    plans: list[QuestionExecutionPlan] = field(default_factory=list)
    blockedQuestions: list[dict[str, Any]] = field(default_factory=list)

    # Readiness assessment
    readinessReport: ExecutionReadinessReport = field(default_factory=ExecutionReadinessReport)

    # Data reference (path/URL to the actual dataframe for S4 to load)
    dataframeRef: dict[str, Any] = field(default_factory=dict)

    # Lineage index (question → entities → columns → source tables)
    lineageIndex: dict[str, Any] = field(default_factory=dict)

    # Frozen timestamp
    frozenAt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contractVersion,
            "templateId": self.templateId,
            "datasetId": self.datasetId,
            "bindingAstId": self.bindingAstId,
            "status": self.status,
            "datasetAst": self.datasetAst.to_dict(),
            "bindingAst": self.bindingAst.to_dict(),
            "statisticalContext": self.statisticalContext.to_dict(),
            "plans": [p.to_dict() for p in self.plans],
            "blockedQuestions": list(self.blockedQuestions),
            "readinessReport": self.readinessReport.to_dict(),
            "dataframeRef": dict(self.dataframeRef),
            "lineageIndex": dict(self.lineageIndex),
            "frozenAt": self.frozenAt,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExecutionBundle":
        return cls(
            contractVersion=str(d.get("contractVersion") or CONTRACT_VERSION),
            templateId=str(d.get("templateId") or ""),
            datasetId=str(d.get("datasetId") or ""),
            bindingAstId=str(d.get("bindingAstId") or ""),
            status=str(d.get("status") or "NOT_READY"),
            datasetAst=DatasetAST.from_dict(d.get("datasetAst") or {}),
            bindingAst=BindingAST.from_dict(d.get("bindingAst") or {}),
            statisticalContext=StatisticalContext.from_dict(d.get("statisticalContext") or {}),
            plans=[QuestionExecutionPlan.from_dict(p) for p in (d.get("plans") or [])],
            blockedQuestions=list(d.get("blockedQuestions") or []),
            readinessReport=ExecutionReadinessReport.from_dict(d.get("readinessReport") or {}),
            dataframeRef=dict(d.get("dataframeRef") or {}),
            lineageIndex=dict(d.get("lineageIndex") or {}),
            frozenAt=str(d.get("frozenAt") or ""),
        )

    # -- convenience methods -------------------------------------------------

    @property
    def executable_plans(self) -> list[QuestionExecutionPlan]:
        return [p for p in self.plans if p.status == "EXECUTABLE"]

    @property
    def degraded_plans(self) -> list[QuestionExecutionPlan]:
        return [p for p in self.plans if p.status == "DEGRADED"]
