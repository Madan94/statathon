"""Generation-phase AST schemas — ``analyticsAST`` · ``evidenceAST`` · trace.

These dataclasses are the value-bearing artifacts produced by the **generation
phase** (``report_builder/generation/``), the third leg of the pipeline:

    R1 extraction  →  ① template.ast.json + ② template.blueprint.json   (value-free)
    R2 binding     →  datasetAST + bindingAST + coverage                 (the map)
    S4–S6 generate →  analyticsAST + evidenceAST  →  ③ report.output.ast.json

They follow the same conventions as ``binding/schema.py`` and ``ast_core/schema.py``
— generous defaults, ``to_dict`` / ``from_dict`` round-trip, camelCase JSON keys —
and live in the generation package so the phase stays self-contained and
independently testable.

Unlike the binding/template schemas, these **do** carry measured values: every
number is paired with a ``rowIds`` provenance token list so it traces back to the
exact dataset rows that produced it (the audit contract).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Controlled vocabularies
# ─────────────────────────────────────────────────────────────────────────────

# The four analytic operations the blueprint's ``analyticsSpec.operation`` uses,
# each mapping to one rollup bucket in analyticsAST.
OPERATIONS = ("group_aggregate", "rank", "trend", "metric")

# Aggregation functions a measure may request (blueprint ``measure.agg``).
AGG_FUNCS = ("weighted_ratio", "mean", "sum", "median", "count", "ratio", "min", "max")

# Execution status (per question).
EXEC_STATUSES = ("ok", "empty", "error", "skipped")

# Evidence kinds — which analytics bucket the evidence cites.
EVIDENCE_KINDS = ("metric", "aggregation", "ranking", "trend")


# ─────────────────────────────────────────────────────────────────────────────
# analyticsAST — plans + executions + rollups
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PlanMeasure:
    """The measure expression inside a plan (``measure`` block, gold shape)."""

    columnExpr: str = ""
    agg: str = "mean"
    weightColumn: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"columnExpr": self.columnExpr, "agg": self.agg}
        if self.weightColumn:
            out["weightColumn"] = self.weightColumn
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanMeasure":
        return cls(
            columnExpr=str(d.get("columnExpr") or ""),
            agg=str(d.get("agg") or "mean"),
            weightColumn=d.get("weightColumn"),
        )


@dataclass
class AnalyticsPlanRec:
    """One question's compute plan (gold ``analyticsAST.plans[]`` shape).

    This is the *declarative* plan that pairs 1:1 with a question and an
    execution. It is built deterministically from the blueprint's
    ``analyticsSpec`` + the binding's ``resolvedRoles`` (the columns are already
    known, so no NL intent parsing is needed).
    """

    planId: str = ""
    questionId: str = ""
    operation: str = "metric"        # one of OPERATIONS
    measure: PlanMeasure = field(default_factory=PlanMeasure)
    groupBy: list[str] = field(default_factory=list)     # column names
    filters: list[str] = field(default_factory=list)     # expr strings, e.g. "age>=15"
    sort: dict[str, Any] = field(default_factory=dict)   # {by, order}
    topN: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "planId": self.planId,
            "questionId": self.questionId,
            "operation": self.operation,
            "measure": self.measure.to_dict(),
            "groupBy": list(self.groupBy),
            "filters": list(self.filters),
            "sort": dict(self.sort),
        }
        if self.topN is not None:
            out["topN"] = self.topN
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AnalyticsPlanRec":
        return cls(
            planId=str(d.get("planId") or ""),
            questionId=str(d.get("questionId") or ""),
            operation=str(d.get("operation") or "metric"),
            measure=PlanMeasure.from_dict(d.get("measure") or {}),
            groupBy=list(d.get("groupBy") or []),
            filters=list(d.get("filters") or []),
            sort=dict(d.get("sort") or {}),
            topN=d.get("topN"),
        )


@dataclass
class ExecutionRec:
    """The execution receipt for a plan (gold ``analyticsAST.executions[]``)."""

    executionId: str = ""
    planRef: str = ""
    engine: str = "pandas"           # gold labels "duckdb"; swappable backend
    rowsScanned: int = 0
    ms: int = 0
    status: str = "ok"               # one of EXEC_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "executionId": self.executionId,
            "planRef": self.planRef,
            "engine": self.engine,
            "rowsScanned": self.rowsScanned,
            "ms": self.ms,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExecutionRec":
        return cls(
            executionId=str(d.get("executionId") or ""),
            planRef=str(d.get("planRef") or ""),
            engine=str(d.get("engine") or "pandas"),
            rowsScanned=int(d.get("rowsScanned") or 0),
            ms=int(d.get("ms") or 0),
            status=str(d.get("status") or "ok"),
        )


@dataclass
class AggregationRow:
    """One group's aggregated value with row provenance."""

    key: dict[str, Any] = field(default_factory=dict)   # {dimColumn: memberValue}
    value: Any = None
    n: int = 0
    rowIds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"key": dict(self.key), "value": self.value, "n": self.n, "rowIds": list(self.rowIds)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AggregationRow":
        return cls(
            key=dict(d.get("key") or {}),
            value=d.get("value"),
            n=int(d.get("n") or 0),
            rowIds=list(d.get("rowIds") or []),
        )


@dataclass
class Aggregation:
    """A grouped aggregation result (gold ``analyticsAST.aggregations[]``)."""

    aggId: str = ""
    questionId: str = ""
    groupBy: str = ""                # single grouping column name (gold shape)
    measure: str = ""                # measure column name
    rows: list[AggregationRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggId": self.aggId,
            "questionId": self.questionId,
            "groupBy": self.groupBy,
            "measure": self.measure,
            "rows": [r.to_dict() for r in self.rows],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Aggregation":
        return cls(
            aggId=str(d.get("aggId") or ""),
            questionId=str(d.get("questionId") or ""),
            groupBy=str(d.get("groupBy") or ""),
            measure=str(d.get("measure") or ""),
            rows=[AggregationRow.from_dict(r) for r in (d.get("rows") or [])],
        )


@dataclass
class RankingItem:
    """One ranked entry."""

    rank: int = 0
    key: dict[str, Any] = field(default_factory=dict)
    value: Any = None
    rowIds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "key": dict(self.key), "value": self.value, "rowIds": list(self.rowIds)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RankingItem":
        return cls(
            rank=int(d.get("rank") or 0),
            key=dict(d.get("key") or {}),
            value=d.get("value"),
            rowIds=list(d.get("rowIds") or []),
        )


@dataclass
class Ranking:
    """A ranked result (gold ``analyticsAST.rankings[]``)."""

    rankId: str = ""
    questionId: str = ""
    measure: str = ""
    order: str = "desc"
    items: list[RankingItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rankId": self.rankId,
            "questionId": self.questionId,
            "measure": self.measure,
            "order": self.order,
            "items": [it.to_dict() for it in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Ranking":
        return cls(
            rankId=str(d.get("rankId") or ""),
            questionId=str(d.get("questionId") or ""),
            measure=str(d.get("measure") or ""),
            order=str(d.get("order") or "desc"),
            items=[RankingItem.from_dict(it) for it in (d.get("items") or [])],
        )


@dataclass
class TrendPoint:
    """One period's value on a trend line."""

    period: str = ""
    value: Any = None
    rowIds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"period": self.period, "value": self.value, "rowIds": list(self.rowIds)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrendPoint":
        return cls(
            period=str(d.get("period") or ""),
            value=d.get("value"),
            rowIds=list(d.get("rowIds") or []),
        )


@dataclass
class Trend:
    """A time-series trend result (gold ``analyticsAST.trends[]``; empty in WPR)."""

    trendId: str = ""
    questionId: str = ""
    measure: str = ""
    dimension: str = ""              # the time/period column
    points: list[TrendPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trendId": self.trendId,
            "questionId": self.questionId,
            "measure": self.measure,
            "dimension": self.dimension,
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Trend":
        return cls(
            trendId=str(d.get("trendId") or ""),
            questionId=str(d.get("questionId") or ""),
            measure=str(d.get("measure") or ""),
            dimension=str(d.get("dimension") or ""),
            points=[TrendPoint.from_dict(p) for p in (d.get("points") or [])],
        )


@dataclass
class Metric:
    """A single scalar metric (gold ``analyticsAST.metrics[]``)."""

    metricId: str = ""
    questionId: str = ""
    label: str = ""
    value: Any = None
    unit: str | None = None
    rowIds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metricId": self.metricId,
            "questionId": self.questionId,
            "label": self.label,
            "value": self.value,
        }
        if self.unit is not None:
            out["unit"] = self.unit
        out["rowIds"] = list(self.rowIds)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Metric":
        return cls(
            metricId=str(d.get("metricId") or ""),
            questionId=str(d.get("questionId") or ""),
            label=str(d.get("label") or ""),
            value=d.get("value"),
            unit=d.get("unit"),
            rowIds=list(d.get("rowIds") or []),
        )


@dataclass
class AnalyticsAST:
    """The full analytics subtree (gold ``analyticsAST``)."""

    plans: list[AnalyticsPlanRec] = field(default_factory=list)
    executions: list[ExecutionRec] = field(default_factory=list)
    aggregations: list[Aggregation] = field(default_factory=list)
    rankings: list[Ranking] = field(default_factory=list)
    trends: list[Trend] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plans": [p.to_dict() for p in self.plans],
            "executions": [e.to_dict() for e in self.executions],
            "aggregations": [a.to_dict() for a in self.aggregations],
            "rankings": [r.to_dict() for r in self.rankings],
            "trends": [t.to_dict() for t in self.trends],
            "metrics": [m.to_dict() for m in self.metrics],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AnalyticsAST":
        return cls(
            plans=[AnalyticsPlanRec.from_dict(p) for p in (d.get("plans") or [])],
            executions=[ExecutionRec.from_dict(e) for e in (d.get("executions") or [])],
            aggregations=[Aggregation.from_dict(a) for a in (d.get("aggregations") or [])],
            rankings=[Ranking.from_dict(r) for r in (d.get("rankings") or [])],
            trends=[Trend.from_dict(t) for t in (d.get("trends") or [])],
            metrics=[Metric.from_dict(m) for m in (d.get("metrics") or [])],
        )


# ─────────────────────────────────────────────────────────────────────────────
# evidenceAST — row-level provenance for every value
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Evidence:
    """One provenance record linking a component's value to its source rows.

    Gold ``evidenceAST.evidence[]`` shape. Every filled slot in ③ points at one
    of these via ``provenance.evidenceRef`` so a reader can trace a number all
    the way to the dataset rows and the computation that produced it.
    """

    evidenceId: str = ""
    questionId: str = ""
    componentId: str = ""
    kind: str = "metric"             # one of EVIDENCE_KINDS
    analyticsRef: str = ""           # id of the agg/rank/metric/trend it cites
    columns: list[str] = field(default_factory=list)
    rowIds: list[str] = field(default_factory=list)
    computation: str = ""
    value: Any = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidenceId,
            "questionId": self.questionId,
            "componentId": self.componentId,
            "kind": self.kind,
            "analyticsRef": self.analyticsRef,
            "columns": list(self.columns),
            "rowIds": list(self.rowIds),
            "computation": self.computation,
            "value": self.value,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Evidence":
        return cls(
            evidenceId=str(d.get("evidenceId") or ""),
            questionId=str(d.get("questionId") or ""),
            componentId=str(d.get("componentId") or ""),
            kind=str(d.get("kind") or "metric"),
            analyticsRef=str(d.get("analyticsRef") or ""),
            columns=list(d.get("columns") or []),
            rowIds=list(d.get("rowIds") or []),
            computation=str(d.get("computation") or ""),
            value=d.get("value"),
            confidence=float(d.get("confidence") or 0.0),
        )


@dataclass
class EvidenceAST:
    """The full evidence subtree (gold ``evidenceAST``)."""

    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"evidence": [e.to_dict() for e in self.evidence]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvidenceAST":
        return cls(evidence=[Evidence.from_dict(e) for e in (d.get("evidence") or [])])

    # -- convenience ---------------------------------------------------------

    def by_component(self, component_id: str) -> "Evidence | None":
        for e in self.evidence:
            if e.componentId == component_id:
                return e
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Observability — generation trace (mirrors extraction's pipeline_trace)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StageTrace:
    """One stage's observability record for a single question."""

    questionId: str = ""
    stage: str = ""                  # plan | query | analyze | visualize | critique | narrate
    status: str = "ok"               # ok | warn | skipped | error
    ms: int = 0
    confidence: float | None = None
    rowsScanned: int = 0
    narrativeTier: int | None = None     # 0/1/2 for the narrative stage
    ltmHits: int = 0
    fallback: str | None = None          # set when a stage degraded to a floor
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "questionId": self.questionId,
            "stage": self.stage,
            "status": self.status,
            "ms": self.ms,
            "rowsScanned": self.rowsScanned,
            "ltmHits": self.ltmHits,
            "notes": list(self.notes),
        }
        if self.confidence is not None:
            out["confidence"] = self.confidence
        if self.narrativeTier is not None:
            out["narrativeTier"] = self.narrativeTier
        if self.fallback is not None:
            out["fallback"] = self.fallback
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StageTrace":
        return cls(
            questionId=str(d.get("questionId") or ""),
            stage=str(d.get("stage") or ""),
            status=str(d.get("status") or "ok"),
            ms=int(d.get("ms") or 0),
            confidence=d.get("confidence"),
            rowsScanned=int(d.get("rowsScanned") or 0),
            narrativeTier=d.get("narrativeTier"),
            ltmHits=int(d.get("ltmHits") or 0),
            fallback=d.get("fallback"),
            notes=list(d.get("notes") or []),
        )


@dataclass
class GenerationTrace:
    """End-to-end observability for one generation run.

    Surfaced as the metro-path UI (same UX language as the extraction stepper).
    Carries per-stage timings/confidence/fallbacks plus rollup counters.
    """

    reportId: str = ""
    templateId: str = ""
    datasetId: str = ""
    stages: list[StageTrace] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    startedAt: str = ""
    finishedAt: str = ""
    totalsMs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "reportId": self.reportId,
            "templateId": self.templateId,
            "datasetId": self.datasetId,
            "stages": [s.to_dict() for s in self.stages],
            "warnings": list(self.warnings),
            "startedAt": self.startedAt,
            "finishedAt": self.finishedAt,
            "totalsMs": self.totalsMs,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GenerationTrace":
        return cls(
            reportId=str(d.get("reportId") or ""),
            templateId=str(d.get("templateId") or ""),
            datasetId=str(d.get("datasetId") or ""),
            stages=[StageTrace.from_dict(s) for s in (d.get("stages") or [])],
            warnings=list(d.get("warnings") or []),
            startedAt=str(d.get("startedAt") or ""),
            finishedAt=str(d.get("finishedAt") or ""),
            totalsMs=int(d.get("totalsMs") or 0),
        )
