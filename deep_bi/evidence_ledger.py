"""Evidence Ledger.

Every claim a Deep BI response makes is recorded here with:
  - the prose claim
  - the numeric/string value asserted
  - the source kind (dataset / aggregate / kg / rulebook / history)
  - the row_ids that contributed
  - the computation dict (so it can be re-run independently)
  - a verified flag set by the Verifier (after independent recomputation)
  - a confidence score from the calibrator

The ledger also exposes `attach_to_narrative()` which links sentence-level
claims back to evidence ids so a renderer can show `[E1, E2]` markers next
to every sentence.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ast_core.schema import EvidenceEntry

logger = logging.getLogger(__name__)


@dataclass
class EvidenceRecord:
    evidence_id: str
    claim: str
    value: Any
    source: str
    row_ids: list[int] = field(default_factory=list)
    computation: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    verified: bool = False
    op: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_ast_entry(self) -> EvidenceEntry:
        return EvidenceEntry(
            evidenceId=self.evidence_id, claim=self.claim, value=self.value,
            source=self.source, row_ids=list(self.row_ids),
            computation=dict(self.computation),
            confidence=float(self.confidence), verified=bool(self.verified),
            diagnostics=dict(self.diagnostics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"evidence_id": self.evidence_id, "claim": self.claim,
                "value": self.value, "source": self.source,
                "row_ids": self.row_ids[:50], "row_count": len(self.row_ids),
                "computation": self.computation, "confidence": self.confidence,
                "verified": self.verified, "op": self.op,
                "diagnostics": self.diagnostics}


class EvidenceLedger:
    """Append-only collection of EvidenceRecords."""

    def __init__(self):
        self.records: list[EvidenceRecord] = []
        self._next = 1

    def _nid(self) -> str:
        nid = f"E{self._next}"
        self._next += 1
        return nid

    # ---------------- Recording ----------------

    def record(self, *, claim: str, value: Any, source: str = "aggregate",
                row_ids: list[int] | None = None,
                computation: dict[str, Any] | None = None,
                confidence: float = 0.0, verified: bool = False,
                op: str = "",
                diagnostics: dict[str, Any] | None = None) -> EvidenceRecord:
        rec = EvidenceRecord(
            evidence_id=self._nid(),
            claim=claim, value=value, source=source,
            row_ids=list(row_ids or []),
            computation=dict(computation or {}),
            confidence=float(confidence), verified=bool(verified), op=op,
            diagnostics=dict(diagnostics or {}),
        )
        self.records.append(rec)
        return rec

    # ---------------- Bulk import from AnalyticsExecution ----------------

    def import_execution(self, execution) -> list[EvidenceRecord]:
        """Walk an AnalyticsExecution and record one EvidenceRecord per result."""
        out: list[EvidenceRecord] = []
        for r in execution.results:
            claim = self._claim_for(r)
            conf = 0.92 if r.value is not None and not r.notes else 0.30
            out.append(self.record(
                claim=claim, value=r.value,
                source="aggregate" if r.op != "filter" else "dataset",
                row_ids=r.row_ids, computation=r.computation,
                confidence=conf, op=r.op,
                diagnostics={"notes": r.notes, "explanation": r.explanation},
            ))
        return out

    @staticmethod
    def _claim_for(result) -> str:
        op = result.op
        c = result.computation or {}
        if op == "aggregate":
            return (f"{c.get('fn','sum')} of {c.get('metric')}"
                    + (f" by {c.get('by')}" if c.get('by') else ""))
        if op == "rank":
            return f"top {c.get('top_k')} by {c.get('metric')} ({c.get('order')})"
        if op == "trend":
            return f"trend of {c.get('metric')} over {c.get('time_column') or 'index'}"
        if op == "corr":
            return f"correlation matrix on {c.get('metrics')}"
        if op == "compare":
            return f"{c.get('left')} vs {c.get('right')}"
        if op == "outlier":
            return f"{c.get('outlier_count', 0)} IQR outliers in {c.get('metric')}"
        if op == "describe":
            return f"descriptive stats" + (f" for {c.get('metric')}" if c.get('metric') else "")
        if op == "filter":
            return f"filtered rows where {c.get('filter_column')} == {c.get('filter_value')}"
        return result.explanation or op

    # ---------------- Sentence ↔ Evidence linking ----------------

    _NUM = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\b")

    def attach_to_narrative(self, narrative: str) -> list[dict[str, Any]]:
        """Split narrative into sentences and map each to candidate evidence ids."""
        sentences = re.split(r"(?<=[\.\!\?])\s+", (narrative or "").strip())
        out: list[dict[str, Any]] = []
        for i, s in enumerate(sentences):
            if not s:
                continue
            ev_ids = []
            for m in self._NUM.finditer(s):
                raw = m.group(1).replace(",", "")
                try:
                    val = float(raw)
                except ValueError:
                    continue
                # Match against any evidence whose value contains this number
                for rec in self.records:
                    if self._value_contains(rec.value, val):
                        ev_ids.append(rec.evidence_id)
            out.append({
                "sentence_index": i,
                "sentence": s,
                "evidence_ids": sorted(set(ev_ids)),
                "verified": all(self.by_id(eid) and self.by_id(eid).verified
                                  for eid in set(ev_ids)) if ev_ids else False,
            })
        return out

    @staticmethod
    def _value_contains(value: Any, target: float, tol: float = 0.05) -> bool:
        if isinstance(value, (int, float)):
            return abs(float(value) - target) <= max(abs(target) * tol, 1e-9)
        if isinstance(value, dict):
            for v in value.values():
                if EvidenceLedger._value_contains(v, target, tol):
                    return True
            return False
        if isinstance(value, list):
            for item in value:
                if EvidenceLedger._value_contains(item, target, tol):
                    return True
            return False
        return False

    # ---------------- Lookup ----------------

    def by_id(self, eid: str) -> EvidenceRecord | None:
        for r in self.records:
            if r.evidence_id == eid:
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"records": [r.to_dict() for r in self.records],
                "count": len(self.records)}

    def to_ast_entries(self) -> list[EvidenceEntry]:
        return [r.to_ast_entry() for r in self.records]
