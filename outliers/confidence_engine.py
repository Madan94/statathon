"""Confidence scores for flagged anomalies (explainability heuristics)."""

from __future__ import annotations


def severity_multiplier(severity: str | None) -> float:
    return {"LOW": 0.55, "MEDIUM": 0.72, "EXTREME": 0.9}.get(severity or "", 0.48)


def anomaly_row_confidence(method_confidence: float, severity: str | None) -> float:
    mc = max(0.0, min(1.0, method_confidence))
    sm = severity_multiplier(severity)
    return round(max(0.0, min(1.0, 0.62 * mc + 0.38 * sm)), 4)
