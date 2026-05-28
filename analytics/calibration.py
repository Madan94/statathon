"""Calibrated confidence aggregation.

Every subsystem (semantic mapping, clustering, validation, anomaly, imputation)
emits multiple signals per candidate. Today each subsystem hard-codes a blend
formula like `0.4*x + 0.3*y + ...` with arbitrary weights. This module
centralises that aggregation so:

  * Weights live in one config (env-overridable per subsystem)
  * Calibration (Platt / isotonic) can be applied uniformly later
  * Every confidence score carries an audit trail of contributing signals

Usage:

    from analytics import default_calibrator
    score = default_calibrator.combine(
        subsystem="semantic_mapping",
        signals={
            "cosine": 0.86,
            "jaccard": 0.62,
            "dtype_alignment": 0.95,
            "distribution_fit": 0.71,
            "keyword_overlap": 0.40,
        },
    )
    score.value      # final calibrated confidence in [0, 1]
    score.band       # 'high' | 'medium' | 'low'
    score.explain()  # {signal: contribution_pct}
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default weights (overridable via env or JSON config)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "semantic_mapping": {
        "alias_exact": 0.30,        # strong: column name == domain name / alias
        "cosine": 0.22,
        "keyword_overlap": 0.10,
        "structural": 0.08,
        "jaccard": 0.07,
        "dtype_alignment": 0.08,
        "distribution_fit": 0.08,
        "cluster_support": 0.05,
        "graph_consistency": 0.02,
    },
    "clustering": {
        "silhouette": 0.35,
        "davies_bouldin_inv": 0.20,
        "stability_ari": 0.25,
        "cohesion": 0.20,
    },
    "validation": {
        "semantic_confidence": 0.30,
        "dtype_alignment": 0.20,
        "violation_stability": 0.25,
        "rule_specificity": 0.15,
        "kg_support": 0.10,
    },
    "anomaly_method": {
        "normality": 0.35,         # supports z-score
        "robustness_need": 0.35,   # supports IQR
        "variance_stability": 0.15,
        "sample_size_adequacy": 0.15,
    },
    "imputation_method": {
        "distribution_fit": 0.35,
        "correlation_support": 0.25,
        "missing_mechanism": 0.20,
        "domain_prior": 0.10,
        "stability": 0.10,
    },
}


HIGH_BAND = 0.75
MEDIUM_BAND = 0.50


# ---------------------------------------------------------------------------
# Calibrated score wrapper
# ---------------------------------------------------------------------------


@dataclass
class CalibratedScore:
    """Result of `ConfidenceCalibrator.combine()`."""

    value: float
    band: str                                 # 'high' | 'medium' | 'low'
    signals: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    subsystem: str = ""
    notes: list[str] = field(default_factory=list)

    def explain(self) -> dict[str, dict[str, float]]:
        """Per-signal contribution breakdown (weight * value / total)."""
        out: dict[str, dict[str, float]] = {}
        total = sum(self.signals.get(k, 0.0) * w for k, w in self.weights.items())
        for sig, w in self.weights.items():
            v = self.signals.get(sig, 0.0)
            out[sig] = {
                "value": float(v),
                "weight": float(w),
                "contribution_pct": float(((v * w) / total * 100.0) if total else 0.0),
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "band": self.band,
            "subsystem": self.subsystem,
            "signals": self.signals,
            "weights": self.weights,
            "explain": self.explain(),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Calibrator
# ---------------------------------------------------------------------------


class ConfidenceCalibrator:
    """Weighted-average aggregator with provisions for future calibration.

    The current implementation uses normalised weighted average. Future
    extensions can wire in Platt scaling or isotonic regression by overriding
    `_calibrate()` without touching call sites.
    """

    def __init__(self, weights: dict[str, dict[str, float]] | None = None):
        self.weights = weights or DEFAULT_WEIGHTS
        self._load_overrides()

    def _load_overrides(self) -> None:
        """Allow JSON file or env vars to override default weights at startup."""
        path = os.getenv("STATATHON_CALIBRATION_CONFIG")
        if path and Path(path).is_file():
            try:
                data = json.loads(Path(path).read_text())
                if isinstance(data, dict):
                    for sub, w in data.items():
                        if isinstance(w, dict):
                            self.weights[sub] = {**self.weights.get(sub, {}), **w}
            except Exception as exc:
                logger.warning("Failed to load calibration overrides: %s", exc)

    def get_weights(self, subsystem: str) -> dict[str, float]:
        """Return the active weight map for a subsystem (renormalised to 1.0)."""
        w = self.weights.get(subsystem, {})
        if not w:
            return {}
        total = sum(v for v in w.values() if v > 0)
        if total <= 0:
            return {}
        return {k: float(v) / total for k, v in w.items() if v > 0}

    def combine(
        self,
        subsystem: str,
        signals: dict[str, float],
        notes: list[str] | None = None,
        applicability: dict[str, bool] | None = None,
        enable_consensus_bonus: bool = True,
    ) -> CalibratedScore:
        """Weighted aggregation with applicability filtering + consensus bonus.

        Key differences from a plain weighted average:

          * `applicability` lets the caller mark a signal as N/A (e.g. structural
            similarity when no tokens overlap). N/A signals are *dropped*, not
            zeroed — so a missing-but-N/A signal does not penalise the score.
          * Consensus bonus: when 4 or more *applicable* signals exceed 0.7,
            +0.05 is added (capped at 1.0). When 6 or more exceed 0.7, +0.10.
            This rewards multi-signal agreement that a plain average would
            wash out.
          * Signals without a configured weight are still kept in the audit
            payload but do not influence the score.
        """
        weights = self.get_weights(subsystem)
        applicability = applicability or {}

        # Build the set of signals that participate in the score:
        # must have a weight AND must be applicable.
        participating: dict[str, float] = {}
        for k, w in weights.items():
            if k not in signals:
                continue
            if applicability.get(k, True) is False:
                continue
            participating[k] = w

        if not participating:
            return CalibratedScore(
                value=0.0, band="low",
                signals={k: float(v) for k, v in signals.items() if isinstance(v, (int, float))},
                weights=weights,
                subsystem=subsystem,
                notes=(notes or []) + ["no applicable signals"],
            )

        # Renormalise the surviving weights to sum to 1.0
        wsum = sum(participating.values())
        norm_weights = {k: v / wsum for k, v in participating.items()}
        raw = sum(_clip01(signals[k]) * norm_weights[k] for k in norm_weights)

        # Consensus bonus
        bonus = 0.0
        if enable_consensus_bonus:
            strong_signals = sum(
                1 for k in norm_weights if _clip01(signals.get(k, 0.0)) >= 0.70
            )
            if strong_signals >= 6:
                bonus = 0.10
            elif strong_signals >= 4:
                bonus = 0.05
            elif strong_signals >= 3:
                bonus = 0.025

        # Tie-breaker dominance bonus: if a single signal is >= 0.9 and weights >= 0.20,
        # bias the score toward it (anchoring effect).
        dominant_bonus = 0.0
        for k, w in norm_weights.items():
            if w >= 0.20 and _clip01(signals.get(k, 0.0)) >= 0.90:
                dominant_bonus = max(dominant_bonus, 0.03)

        # Authority floor: when a signal carries near-certain semantic evidence,
        # ensure the final score reflects that even if other signals are weak.
        # Applies to `alias_exact == 1.0` (verbatim alias match) only.
        authority_floor = 0.0
        if subsystem == "semantic_mapping" and _clip01(signals.get("alias_exact", 0.0)) >= 0.99:
            authority_floor = 0.88

        calibrated = self._calibrate(subsystem, raw + bonus + dominant_bonus)
        if authority_floor > 0:
            calibrated = max(calibrated, authority_floor)
        active_notes = list(notes or [])
        if bonus > 0:
            active_notes.append(f"consensus_bonus={bonus:.3f}")
        if dominant_bonus > 0:
            active_notes.append(f"dominant_signal_bonus={dominant_bonus:.3f}")
        if any(applicability.get(k) is False for k in signals.keys()):
            dropped = [k for k in signals if applicability.get(k) is False]
            active_notes.append(f"dropped_inapplicable={dropped}")

        return CalibratedScore(
            value=calibrated,
            band=_band(calibrated),
            signals={k: float(v) for k, v in signals.items()
                     if isinstance(v, (int, float))},
            weights=norm_weights,
            subsystem=subsystem,
            notes=active_notes,
        )

    def _calibrate(self, subsystem: str, raw: float) -> float:
        """Hook for future Platt/isotonic calibration. Currently identity."""
        return _clip01(raw)


def _clip01(x: float) -> float:
    if x is None:
        return 0.0
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x != x:    # NaN
        return 0.0
    return max(0.0, min(1.0, x))


def _band(score: float) -> str:
    if score >= HIGH_BAND:
        return "high"
    if score >= MEDIUM_BAND:
        return "medium"
    return "low"


# Process-wide singleton
default_calibrator = ConfidenceCalibrator()
