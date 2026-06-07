"""Confidence rollup for a DeepBI answer.

Combines:
  * Intent confidence (parser)
  * Reasoning path total weight (KG support)
  * Evidence count + per-evidence calibrated confidence
  * Verifier verdict per claim (pass / warn / fail / unverified)

Returns a single 0..1 with a per-source breakdown so the AGUI can show why.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analytics import default_calibrator


@dataclass
class ConfidenceReport:
    value: float
    band: str
    breakdown: dict[str, float]
    evidence_count: int
    verified_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"value": round(self.value, 4), "band": self.band,
                "breakdown": self.breakdown,
                "evidence_count": self.evidence_count,
                "verified_count": self.verified_count}


class ConfidenceScorer:

    def score(self, *, intent_confidence: float,
              reasoning_total_weight: float,
              evidence_records: list,
              verifier_verdict: dict[str, Any] | None = None
              ) -> ConfidenceReport:
        # Evidence aggregate
        n = len(evidence_records or [])
        verified = sum(1 for r in (evidence_records or []) if r.verified)
        if n:
            mean_ev = sum(r.confidence for r in evidence_records) / n
            verified_frac = verified / n
        else:
            mean_ev = 0.0
            verified_frac = 0.0

        # Verifier verdict (pass/warn/fail/unverified)
        verdict_score = 0.5
        if verifier_verdict:
            status = str(verifier_verdict.get("overall_status") or "").lower()
            verdict_score = {"pass": 1.0, "warn": 0.6,
                              "fail": 0.2, "unverified": 0.4}.get(status, 0.5)

        # Reasoning weight (multi-hop quality)
        reasoning_norm = min(1.0, float(reasoning_total_weight) / 3.0)

        signals = {
            "semantic_confidence":  float(intent_confidence),
            "kg_support":           reasoning_norm,
            "rule_specificity":     mean_ev,
            "violation_stability":  verdict_score,
            "dtype_alignment":      verified_frac,
        }
        cal = default_calibrator.combine("validation", signals)
        return ConfidenceReport(
            value=cal.value, band=cal.band,
            breakdown=signals,
            evidence_count=n, verified_count=verified,
        )
