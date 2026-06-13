"""S5e — Lineage / provenance enrichment for the assembled report.

The filler already stamps each chart/table with a small ``provenance`` block
(``questionId`` / ``analyticsRef`` / ``evidenceRef``) and carries ``rowIds`` on every
point/row; the executor records one ``Evidence`` per question. This module closes the
audit chain by:

  1. Building a **per-plan lineage index** from the adapted plans + evidenceAST — the
     full trace each measured value can claim: ``questionId``, ``planId``, ``componentRef``,
     ``measureColumn``, ``analyticsRef``, ``evidenceRef``, ``sourceColumns``, ``rowIds``,
     ``formulaType`` and ``filters``.
  2. **Enriching** each filled artifact's ``provenance`` block (additively — never
     overwriting what the filler/narrator set) with the richer plan-level fields so the
     dashboard ProvenanceDrawer and the PDF appendix can show a complete chain.
  3. Computing **provenance coverage** over every measured value (the single source of
     truth the verifier also consumes) and recording it under
     ``auditAST.provenance`` together with ``datasetSignature`` / ``contentHash``.
  4. Surfacing the bundle's **StatisticalContext** (source notes, units, geography,
     survey round, …) under ``auditAST.statisticalContext`` — only fields that exist;
     nothing is invented.

Everything is additive and backward-compatible: the gold 13-key report shape is
unchanged, and a legacy run (no adapted plans / no bundle) still produces a valid
``auditAST.provenance`` computed from the report alone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from report_builder.binding.execution_contracts import ExecutionBundle
    from report_builder.generation.bundle_adapter import AdaptedPlan

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Measured-value enumeration (single source of truth, shared with the verifier)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MeasuredValue:
    """One value-bearing slot in the report and the refs that make it traceable."""

    kind: str                         # block | chartPoint | tableRow | metric
    elementId: str
    refs: list[str] = field(default_factory=list)   # evidence/analytics refs (or rowIds for blocks)
    rowIds: list[str] = field(default_factory=list)

    @property
    def traced(self) -> bool:
        return bool(self.refs)


def iter_measured_values(report: dict[str, Any]) -> list[MeasuredValue]:
    """Every filled, value-bearing slot in the report.

    A value is *traced* when it carries an evidence/analytics ref (blocks) or row-id
    provenance (chart points, table rows, metrics). This is the canonical definition
    used by both the audit coverage and the verifier's PROVENANCE check.
    """
    out: list[MeasuredValue] = []

    for b in (report.get("contentAST") or {}).get("blocks", []):
        if (b.get("slot") or {}).get("status") != "filled":
            continue
        # Derived summary blocks (e.g. Key Findings synthesized from auditAST.insights)
        # are not measured values — they restate already-traced numbers, so excluding
        # them keeps provenance coverage about *source* values, not their summaries.
        if b.get("kind") == "key_findings" or (b.get("provenance") or {}).get("derivedFrom"):
            continue
        prov = b.get("provenance") or {}
        refs = [r for r in [prov.get("evidenceRef"), prov.get("analyticsRef")] if r]
        row_ids = list(prov.get("rowIds") or [])
        out.append(MeasuredValue("block", b.get("blockId", "?"), refs or row_ids, row_ids))

    for c in (report.get("chartAST") or {}).get("charts", []):
        if (c.get("slot") or {}).get("status") != "filled":
            continue
        for s in c.get("series", []):
            for p in s.get("points", []):
                rids = list(p.get("rowIds") or [])
                out.append(MeasuredValue("chartPoint", c.get("chartId", "?"), rids, rids))

    for t in (report.get("tableAST") or {}).get("tables", []):
        if (t.get("slot") or {}).get("status") != "filled":
            continue
        for row in t.get("rows", []):
            rids = list(row.get("rowIds") or [])
            out.append(MeasuredValue("tableRow", t.get("tableId", "?"), rids, rids))

    for m in (report.get("analyticsAST") or {}).get("metrics", []):
        rids = list(m.get("rowIds") or [])
        out.append(MeasuredValue("metric", m.get("metricId", "?"), rids, rids))

    return out


@dataclass
class ProvenanceCoverage:
    measured: int = 0
    traced: int = 0

    @property
    def coverage(self) -> float:
        return (self.traced / self.measured) if self.measured else 1.0


def compute_coverage(report: dict[str, Any]) -> ProvenanceCoverage:
    """Fraction of measured values that carry a provenance trace (1.0 when none)."""
    mvs = iter_measured_values(report)
    return ProvenanceCoverage(measured=len(mvs), traced=sum(1 for m in mvs if m.traced))


def provenance_coverage(report: dict[str, Any]) -> float:
    return compute_coverage(report).coverage


# ─────────────────────────────────────────────────────────────────────────────
# Per-plan lineage index
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class LineageEntry:
    """The full audit trace for one executed plan (one row of the provenance appendix)."""

    questionId: str = ""
    planId: str = ""
    componentRef: str | None = None
    measureColumn: str = ""
    analyticsRef: str = ""
    evidenceRef: str = ""
    sourceColumns: list[str] = field(default_factory=list)
    rowIds: list[str] = field(default_factory=list)
    formulaType: str = "DIRECT"
    filters: list[str] = field(default_factory=list)
    status: str = "EXECUTABLE"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "questionId": self.questionId,
            "planId": self.planId,
            "measureColumn": self.measureColumn,
            "analyticsRef": self.analyticsRef,
            "evidenceRef": self.evidenceRef,
            "sourceColumns": list(self.sourceColumns),
            "rowIds": list(self.rowIds),
            "formulaType": self.formulaType,
            "filters": list(self.filters),
            "status": self.status,
        }
        if self.componentRef:
            out["componentRef"] = self.componentRef
        return out


def _evidence_by_question(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_q: dict[str, dict[str, Any]] = {}
    for ev in (evidence or {}).get("evidence", []):
        by_q.setdefault(ev.get("questionId", ""), ev)   # first evidence per question wins
    return by_q


def build_lineage_index(
    adapted: "list[AdaptedPlan] | None",
    evidence: dict[str, Any] | None,
) -> list[LineageEntry]:
    """One :class:`LineageEntry` per adapted plan, joined to its evidence record.

    Multi-measure fan-out yields one entry per fanned plan (stable ``planId``), so a
    value can never trace to the wrong measure/slot.
    """
    ev_by_q = _evidence_by_question(evidence or {})
    entries: list[LineageEntry] = []
    for plan in adapted or []:
        qid = plan.questionId or plan.planRec.questionId
        ev = ev_by_q.get(qid, {})
        entries.append(LineageEntry(
            questionId=qid,
            planId=plan.planRec.planId,
            componentRef=plan.componentRef,
            measureColumn=plan.measureColumn or plan.planRec.measure.columnExpr,
            analyticsRef=str(ev.get("analyticsRef") or ""),
            evidenceRef=str(ev.get("evidenceId") or ""),
            sourceColumns=list(plan.lineage.sourceColumnIds or []),
            rowIds=list(ev.get("rowIds") or []),
            formulaType=(plan.formulaSpec.type or "DIRECT"),
            filters=list(plan.planRec.filters or []),
            status=plan.status,
        ))
    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Report enrichment
# ─────────────────────────────────────────────────────────────────────────────


def _enrich_artifact_provenance(report: dict[str, Any],
                                by_question: dict[str, LineageEntry]) -> None:
    """Additively enrich each filled artifact's provenance block with plan-level trace."""
    def enrich(prov: dict[str, Any]) -> None:
        qid = prov.get("questionId")
        entry = by_question.get(qid) if qid else None
        if not entry:
            return
        prov.setdefault("planId", entry.planId)
        if entry.componentRef:
            prov.setdefault("componentRef", entry.componentRef)
        if entry.sourceColumns:
            prov.setdefault("sourceColumns", list(entry.sourceColumns))
        prov.setdefault("formulaType", entry.formulaType)
        if entry.filters:
            prov.setdefault("filters", list(entry.filters))

    for c in (report.get("chartAST") or {}).get("charts", []):
        if isinstance(c.get("provenance"), dict):
            enrich(c["provenance"])
    for t in (report.get("tableAST") or {}).get("tables", []):
        if isinstance(t.get("provenance"), dict):
            enrich(t["provenance"])
    for b in (report.get("contentAST") or {}).get("blocks", []):
        if isinstance(b.get("provenance"), dict):
            enrich(b["provenance"])


def enrich_report_provenance(
    report: dict[str, Any],
    *,
    adapted: "list[AdaptedPlan] | None" = None,
    evidence: dict[str, Any] | None = None,
    bundle: "ExecutionBundle | None" = None,
    dataset_signature: str = "",
    content_hash: str = "",
) -> dict[str, Any]:
    """Populate ``auditAST.provenance`` + ``auditAST.statisticalContext`` (in place).

    Backward-compatible: the report's 13-key shape and existing provenance blocks are
    preserved; new fields are only *added*. A legacy run (no plans / no bundle) still
    gets a valid coverage summary computed from the report itself.
    Returns the provenance summary dict that was stored under ``auditAST.provenance``.
    """
    audit = report.setdefault("auditAST", {})
    entries = build_lineage_index(adapted, evidence)

    # First plan per question drives artifact enrichment (the appendix keeps every plan).
    by_question: dict[str, LineageEntry] = {}
    for e in entries:
        by_question.setdefault(e.questionId, e)
    _enrich_artifact_provenance(report, by_question)

    cov = compute_coverage(report)

    # Defaults from the bundle when not passed explicitly.
    stat_ctx: dict[str, Any] = {}
    if bundle is not None:
        try:
            stat_ctx = bundle.statisticalContext.to_dict()
        except AttributeError:
            stat_ctx = {}
        if not dataset_signature:
            dataset_signature = getattr(bundle.bindingAst, "datasetSignature", "") or ""
        if not content_hash:
            content_hash = str((bundle.dataframeRef or {}).get("contentHash") or "")

    summary = {
        "coverage": round(cov.coverage, 3),
        "measuredValues": cov.measured,
        "tracedValues": cov.traced,
        "datasetSignature": dataset_signature,
        "contentHash": content_hash,
        "entries": [e.to_dict() for e in entries],
    }
    audit["provenance"] = summary
    if stat_ctx:
        audit["statisticalContext"] = stat_ctx

    logger.info("[S5e] provenance coverage %.1f%% (%d/%d) entries=%d statctx=%s",
                100.0 * cov.coverage, cov.traced, cov.measured, len(entries), bool(stat_ctx))
    return summary
