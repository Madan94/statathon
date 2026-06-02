"""5-factor rule confidence scoring.

For every discovered rule we compute a confidence in [0, 1] from five
independent signals:

  * ontology_support   — does the rule align with the domain ontology?
  * graph_support      — does the KG support the relationship the rule encodes?
  * semantic_support   — how confident is the semantic mapping of the column?
  * historical_support — is this a well-known MoSPI / NSSO / NAS rule?
  * statistical_support — does the column's distribution corroborate the rule?

The signals come from `DiscoveredRule.confidence_signals` (each source
populates the signals it has evidence for; missing signals are treated as
"not applicable" and dropped from the weighted aggregation).

We route the aggregation through the shared `analytics.default_calibrator`
so weights are tunable and the same way as the rest of the platform.
"""
from __future__ import annotations

from typing import Any

from analytics import default_calibrator


# Reuse the validation subsystem weights from the calibrator default config.
# (The default 5 signals already line up with the 5 factors we want here.)


def score_rule_confidence(
    rule_signals: dict[str, float],
    *,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate the per-rule signals into a calibrated confidence score.

    Returns a dict with `value`, `band` ('high' | 'medium' | 'low'), and
    a per-signal contribution breakdown.
    """
    # Map our 5 factor names to the calibrator's signal names. The shared
    # calibrator already has "validation" weights tuned to these inputs:
    #   semantic_confidence + dtype_alignment + violation_stability +
    #   rule_specificity + kg_support
    signals: dict[str, float] = {}
    if "semantic_support" in rule_signals:
        signals["semantic_confidence"] = float(rule_signals["semantic_support"])
    if "ontology_support" in rule_signals:
        signals["rule_specificity"] = float(rule_signals["ontology_support"])
    if "graph_support" in rule_signals:
        signals["kg_support"] = float(rule_signals["graph_support"])
    if "statistical_support" in rule_signals:
        signals["dtype_alignment"] = float(rule_signals["statistical_support"])
    if "historical_support" in rule_signals:
        signals["violation_stability"] = float(rule_signals["historical_support"])

    if not signals:
        return {"value": 0.5, "band": "low", "signals": rule_signals, "notes": ["no signals"]}

    score = default_calibrator.combine("validation", signals, notes=notes)
    out = score.to_dict()
    # Expose both the original 5-factor view AND the calibrator's signal view
    out["rule_signals"] = rule_signals
    return out
