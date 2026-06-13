"""Binding-phase AST schemas — ``datasetAST`` · ``bindingAST`` · coverage report.

These dataclasses are the artifacts produced by the binding phase
(``report_builder/binding/``). They follow the same conventions as
``ast_core/schema.py`` — generous defaults, ``to_dict`` / ``from_dict`` round-trip,
camelCase JSON keys — but live in the binding package so the new phase stays
self-contained and independently testable.

Three artifacts:

* :class:`DatasetAST`   — the profiled, self-describing dataset (S0 output).
* :class:`BindingAST`   — entity⇄column bindings + per-question resolution (S1–S3).
* :class:`CoverageReport` — structured gate report with severities (S3/B6).

Nothing here stores measured values or prose; ``DatasetAST`` carries small
``sampleValues`` only (for the confirm UI), never the full dataset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Controlled vocabularies (kept as plain tuples so callers can validate cheaply)
# ─────────────────────────────────────────────────────────────────────────────

COLUMN_ROLES = ("dimension", "measure", "time", "id", "metadata")
CARDINALITIES = ("oneToOne", "memberSet", "composite", "timeSeries")
COMBINE_OPS = ("none", "sum", "mean", "min", "max", "pick")
BINDING_METHODS = ("exact", "alias", "glossary", "synonym", "embedding", "manual")
BINDING_STATUSES = ("proposed", "confirmed", "overridden", "rejected", "unresolved")
QUESTION_STATUSES = ("executable", "blocked", "degraded")
GROUP_KINDS = ("measureGroup", "periodGroup")
SEVERITIES = ("error", "warn", "info")


# ─────────────────────────────────────────────────────────────────────────────
# datasetAST
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ColumnProfile:
    """One profiled dataset column."""

    name: str
    dtype: str = "string"            # string | int | float | bool | date
    role: str = "dimension"          # one of COLUMN_ROLES
    cardinality: int = 0             # number of distinct non-null values
    sampleValues: list[Any] = field(default_factory=list)
    unit: str | None = None          # parsed from name/values (%, MW, ₹, …)
    minValue: float | None = None    # measures only
    maxValue: float | None = None    # measures only
    nullPct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "dtype": self.dtype,
            "role": self.role,
            "cardinality": self.cardinality,
            "sampleValues": list(self.sampleValues),
            "nullPct": self.nullPct,
        }
        if self.unit is not None:
            out["unit"] = self.unit
        if self.minValue is not None:
            out["minValue"] = self.minValue
        if self.maxValue is not None:
            out["maxValue"] = self.maxValue
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnProfile":
        return cls(
            name=str(d.get("name") or ""),
            dtype=str(d.get("dtype") or "string"),
            role=str(d.get("role") or "dimension"),
            cardinality=int(d.get("cardinality") or 0),
            sampleValues=list(d.get("sampleValues") or []),
            unit=d.get("unit"),
            minValue=d.get("minValue"),
            maxValue=d.get("maxValue"),
            nullPct=float(d.get("nullPct") or 0.0),
        )


@dataclass
class ColumnGroup:
    """A set of wide columns that share a stem (members-as-columns)."""

    stem: str
    kind: str = "measureGroup"       # one of GROUP_KINDS
    members: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"stem": self.stem, "kind": self.kind, "members": list(self.members)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnGroup":
        return cls(
            stem=str(d.get("stem") or ""),
            kind=str(d.get("kind") or "measureGroup"),
            members=list(d.get("members") or []),
        )


@dataclass
class ReshapeRecipe:
    """A lazy wide→long melt recipe (applied per-question on a scoped copy)."""

    groupStem: str
    kind: str = "melt"
    idVars: list[str] = field(default_factory=list)
    valueVar: str = "value"
    memberVar: str = "member"

    def to_dict(self) -> dict[str, Any]:
        return {
            "groupStem": self.groupStem,
            "kind": self.kind,
            "idVars": list(self.idVars),
            "valueVar": self.valueVar,
            "memberVar": self.memberVar,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReshapeRecipe":
        return cls(
            groupStem=str(d.get("groupStem") or ""),
            kind=str(d.get("kind") or "melt"),
            idVars=list(d.get("idVars") or []),
            valueVar=str(d.get("valueVar") or "value"),
            memberVar=str(d.get("memberVar") or "member"),
        )


@dataclass
class DatasetAST:
    """The profiled, self-describing dataset (S0 output)."""

    datasetId: str = ""
    sourceFile: str = ""
    rowCount: int = 0
    archetype: str = "generic"       # PLFS | energy | generic | …
    columns: list[ColumnProfile] = field(default_factory=list)
    columnGroups: list[ColumnGroup] = field(default_factory=list)
    reshape: list[ReshapeRecipe] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.datasetId,
            "sourceFile": self.sourceFile,
            "rowCount": self.rowCount,
            "archetype": self.archetype,
            "columns": [c.to_dict() for c in self.columns],
            "columnGroups": [g.to_dict() for g in self.columnGroups],
            "reshape": [r.to_dict() for r in self.reshape],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetAST":
        return cls(
            datasetId=str(d.get("datasetId") or ""),
            sourceFile=str(d.get("sourceFile") or ""),
            rowCount=int(d.get("rowCount") or 0),
            archetype=str(d.get("archetype") or "generic"),
            columns=[ColumnProfile.from_dict(c) for c in (d.get("columns") or [])],
            columnGroups=[ColumnGroup.from_dict(g) for g in (d.get("columnGroups") or [])],
            reshape=[ReshapeRecipe.from_dict(r) for r in (d.get("reshape") or [])],
        )

    # -- convenience lookups -------------------------------------------------

    def column(self, name: str) -> ColumnProfile | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None

    def columns_by_role(self, role: str) -> list[ColumnProfile]:
        return [c for c in self.columns if c.role == role]


# ─────────────────────────────────────────────────────────────────────────────
# bindingAST
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BoundColumn:
    """One column inside an entity binding (with optional member/period label)."""

    column: str
    memberLabel: str | None = None   # memberSet: human-readable member name
    period: str | None = None        # timeSeries: the period this column encodes

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"column": self.column}
        if self.memberLabel is not None:
            out["memberLabel"] = self.memberLabel
        if self.period is not None:
            out["period"] = self.period
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BoundColumn":
        return cls(
            column=str(d.get("column") or ""),
            memberLabel=d.get("memberLabel"),
            period=d.get("period"),
        )


@dataclass
class BindingCandidate:
    """A ranked alternative column for a binding (shown in the confirm UI)."""

    column: str
    confidence: float = 0.0
    method: str = "synonym"          # one of BINDING_METHODS

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "confidence": self.confidence, "method": self.method}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BindingCandidate":
        return cls(
            column=str(d.get("column") or ""),
            confidence=float(d.get("confidence") or 0.0),
            method=str(d.get("method") or "synonym"),
        )


@dataclass
class EntityBinding:
    """An entity → column(s) binding, proposed by S1 and confirmed in S2."""

    entityId: str
    entityName: str = ""
    entityType: str = "dimension"    # dimension | measure | time | filter | metadata
    cardinality: str = "oneToOne"    # one of CARDINALITIES
    columns: list[BoundColumn] = field(default_factory=list)
    combine: str = "none"            # one of COMBINE_OPS (composite only)
    confidence: float = 0.0
    method: str = "synonym"          # one of BINDING_METHODS
    status: str = "proposed"         # one of BINDING_STATUSES
    alternatives: list[BindingCandidate] = field(default_factory=list)
    typeMismatch: bool = False       # soft-penalty flag for the confirm UI
    notes: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "entityId": self.entityId,
            "entityName": self.entityName,
            "entityType": self.entityType,
            "cardinality": self.cardinality,
            "columns": [c.to_dict() for c in self.columns],
            "combine": self.combine,
            "confidence": self.confidence,
            "method": self.method,
            "status": self.status,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "evidence": [dict(e) for e in self.evidence],
            "risks": [dict(r) for r in self.risks],
        }
        if self.typeMismatch:
            out["typeMismatch"] = True
        if self.notes:
            out["notes"] = list(self.notes)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EntityBinding":
        return cls(
            entityId=str(d.get("entityId") or ""),
            entityName=str(d.get("entityName") or ""),
            entityType=str(d.get("entityType") or "dimension"),
            cardinality=str(d.get("cardinality") or "oneToOne"),
            columns=[BoundColumn.from_dict(c) for c in (d.get("columns") or [])],
            combine=str(d.get("combine") or "none"),
            confidence=float(d.get("confidence") or 0.0),
            method=str(d.get("method") or "synonym"),
            status=str(d.get("status") or "proposed"),
            alternatives=[BindingCandidate.from_dict(a) for a in (d.get("alternatives") or [])],
            typeMismatch=bool(d.get("typeMismatch") or False),
            notes=list(d.get("notes") or []),
            evidence=[dict(e) for e in (d.get("evidence") or []) if isinstance(e, dict)],
            risks=[dict(r) for r in (d.get("risks") or []) if isinstance(r, dict)],
        )

    @property
    def column_names(self) -> list[str]:
        return [c.column for c in self.columns]


@dataclass
class ResolvedFilter:
    """A resolved filter on a question (column + operator + value)."""

    column: str
    op: str = "eq"
    value: Any = None
    filterApplied: bool = True       # False = widened (default member absent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "op": self.op,
            "value": self.value,
            "filterApplied": self.filterApplied,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResolvedFilter":
        return cls(
            column=str(d.get("column") or ""),
            op=str(d.get("op") or "eq"),
            value=d.get("value"),
            filterApplied=bool(d.get("filterApplied", True)),
        )


@dataclass
class ResolvedTime:
    """Resolved time/period roles for a question."""

    column: str | None = None
    periods: dict[str, Any] = field(default_factory=dict)  # {current, prior, delta}
    timeResolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "periods": dict(self.periods),
            "timeResolved": self.timeResolved,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResolvedTime":
        return cls(
            column=d.get("column"),
            periods=dict(d.get("periods") or {}),
            timeResolved=bool(d.get("timeResolved") or False),
        )


@dataclass
class ResolvedRoles:
    """The confirmed columns for a question, grouped by analytic role."""

    measures: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    denominators: list[str] = field(default_factory=list)
    filters: list[ResolvedFilter] = field(default_factory=list)
    time: ResolvedTime = field(default_factory=ResolvedTime)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "measures": list(self.measures),
            "dimensions": list(self.dimensions),
            "filters": [f.to_dict() for f in self.filters],
            "time": self.time.to_dict(),
        }
        # Only surface denominators when present so existing snapshots are unaffected.
        if self.denominators:
            out["denominators"] = list(self.denominators)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResolvedRoles":
        return cls(
            measures=list(d.get("measures") or []),
            dimensions=list(d.get("dimensions") or []),
            denominators=list(d.get("denominators") or []),
            filters=[ResolvedFilter.from_dict(f) for f in (d.get("filters") or [])],
            time=ResolvedTime.from_dict(d.get("time") or {}),
        )


@dataclass
class QuestionBinding:
    """Per-question resolution result (S3)."""

    questionId: str
    status: str = "executable"       # one of QUESTION_STATUSES
    resolvedRoles: ResolvedRoles = field(default_factory=ResolvedRoles)
    unresolvedEntities: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "questionId": self.questionId,
            "status": self.status,
            "resolvedRoles": self.resolvedRoles.to_dict(),
            "unresolvedEntities": list(self.unresolvedEntities),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QuestionBinding":
        return cls(
            questionId=str(d.get("questionId") or ""),
            status=str(d.get("status") or "executable"),
            resolvedRoles=ResolvedRoles.from_dict(d.get("resolvedRoles") or {}),
            unresolvedEntities=list(d.get("unresolvedEntities") or []),
            notes=list(d.get("notes") or []),
        )


@dataclass
class BindingAST:
    """The core binding artifact — entity bindings + per-question resolution."""

    templateId: str = ""
    datasetId: str = ""
    datasetSignature: str = ""
    entityBindings: list[EntityBinding] = field(default_factory=list)
    questionBindings: list[QuestionBinding] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "templateId": self.templateId,
            "datasetId": self.datasetId,
            "datasetSignature": self.datasetSignature,
            "entityBindings": [b.to_dict() for b in self.entityBindings],
            "questionBindings": [q.to_dict() for q in self.questionBindings],
            "coverage": dict(self.coverage),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BindingAST":
        return cls(
            templateId=str(d.get("templateId") or ""),
            datasetId=str(d.get("datasetId") or ""),
            datasetSignature=str(d.get("datasetSignature") or ""),
            entityBindings=[EntityBinding.from_dict(b) for b in (d.get("entityBindings") or [])],
            questionBindings=[QuestionBinding.from_dict(q) for q in (d.get("questionBindings") or [])],
            coverage=dict(d.get("coverage") or {}),
        )

    # -- convenience lookups -------------------------------------------------

    def binding_for(self, entity_id: str) -> EntityBinding | None:
        for b in self.entityBindings:
            if b.entityId == entity_id:
                return b
        return None


# ─────────────────────────────────────────────────────────────────────────────
# coverage report
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CoverageIssue:
    """One coverage issue with a severity (error blocks; warn/info surface)."""

    severity: str = "info"           # one of SEVERITIES
    code: str = ""
    message: str = ""
    entityId: str | None = None
    questionId: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.entityId:
            out["entityId"] = self.entityId
        if self.questionId:
            out["questionId"] = self.questionId
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CoverageIssue":
        return cls(
            severity=str(d.get("severity") or "info"),
            code=str(d.get("code") or ""),
            message=str(d.get("message") or ""),
            entityId=d.get("entityId"),
            questionId=d.get("questionId"),
        )


@dataclass
class CoverageReport:
    """Structured gate report (B6). Machine-checkable + human-readable digest."""

    entities: dict[str, int] = field(default_factory=lambda: {"bound": 0, "pending": 0, "unresolved": 0})
    questions: dict[str, int] = field(default_factory=lambda: {"executable": 0, "blocked": 0, "degraded": 0})
    issues: list[CoverageIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": dict(self.entities),
            "questions": dict(self.questions),
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CoverageReport":
        rep = cls(
            entities=dict(d.get("entities") or {}),
            questions=dict(d.get("questions") or {}),
            issues=[CoverageIssue.from_dict(i) for i in (d.get("issues") or [])],
        )
        return rep

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def add(self, severity: str, code: str, message: str,
            *, entity_id: str | None = None, question_id: str | None = None) -> None:
        self.issues.append(CoverageIssue(
            severity=severity, code=code, message=message,
            entityId=entity_id, questionId=question_id,
        ))
