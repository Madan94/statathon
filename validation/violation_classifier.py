"""Violation severity classification.

Every rule violation is mapped to one of four severity bands:

  CRITICAL  — logical impossibility (age = -5, pH = 25)
              Always-true rules that the value provably breaks. Requires
              user attention before the dataset can move to anomaly detection.

  HIGH      — strong domain conflict (employment_rate = 150)
              Domain-declared bound violations + cross-column rule failures
              with high KG/ontology confidence.

  MEDIUM    — suspicious inconsistency (household_income < individual_income)
              Multi-column dependency violations + statistical-range overshoots
              with moderate confidence.

  LOW       — weak semantic mismatch
              Statistical-only outliers with weak ontology grounding. Often
              just heavy-tail tails; user can usually accept.

Classification looks at:
  * Rule source           (ontology > kg > library > archetype > statistical)
  * Rule rule_type         (numeric_between bounds = CRITICAL when violated badly)
  * Violation magnitude    (how far past the boundary)
  * Calibrated confidence  (from rule_confidence.score_rule_confidence)
"""
from __future__ import annotations

from typing import Any


_BASE_SEVERITY_BY_TYPE = {
    "numeric_between": "HIGH",
    "numeric_min": "MEDIUM",
    "numeric_max": "MEDIUM",
    "regex_or_null": "MEDIUM",
    "categorical_in_set": "MEDIUM",
    "is_integer_like": "LOW",
    "aggregation_equals": "HIGH",
    "less_than_or_equal": "MEDIUM",
    "date_order": "HIGH",
    "correlation_consistency": "LOW",
    "dependency_implication": "MEDIUM",
    "non_null_dependency": "LOW",
}


def classify_violation(
    *,
    rule_source: str,
    rule_type: str,
    severity_hint: str | None,
    violation_magnitude: float | None,
    rule_confidence: float,
) -> str:
    """Return CRITICAL | HIGH | MEDIUM | LOW for one violation."""
    base = _BASE_SEVERITY_BY_TYPE.get(rule_type, "MEDIUM")
    hint = (severity_hint or "").upper()

    # 1) Logical impossibility detector
    #    A numeric bound from an ontology source with very large magnitude
    #    overshoot means the value cannot be real -> CRITICAL
    if rule_source in ("ontology", "library") and rule_type in ("numeric_between", "numeric_min", "numeric_max"):
        if violation_magnitude is not None and violation_magnitude >= 0.25:
            # Value is at least 25% past the bound — likely impossible
            return "CRITICAL"

    # 2) Promote based on hinted severity from the rule's metadata
    if hint == "HIGH":
        base = _max_severity(base, "HIGH")
    elif hint == "CRITICAL":
        return "CRITICAL"
    elif hint == "LOW":
        base = _min_severity(base, "LOW")

    # 3) Confidence floor — low-confidence violations get demoted
    if rule_confidence < 0.40:
        return _min_severity(base, "LOW")
    if rule_confidence < 0.55 and base in ("HIGH", "CRITICAL"):
        base = "MEDIUM"
    if rule_confidence >= 0.85 and base == "MEDIUM":
        base = _max_severity(base, "HIGH")

    return base


def relative_magnitude(value: float | None,
                        bound_low: float | None = None,
                        bound_high: float | None = None) -> float | None:
    """How far past the boundary is `value`, normalised by the bound range?

    Returns 0.0 if inside the bounds. >0 means past the bound (a fraction of
    the legitimate range). Used by `classify_violation` to flag impossibility.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    if bound_low is not None and bound_high is not None:
        span = max(1e-9, float(bound_high) - float(bound_low))
        if v < bound_low:
            return float(abs(bound_low - v) / span)
        if v > bound_high:
            return float(abs(v - bound_high) / span)
        return 0.0
    if bound_low is not None and v < bound_low:
        return float(abs(bound_low - v) / max(1.0, abs(bound_low)))
    if bound_high is not None and v > bound_high:
        return float(abs(v - bound_high) / max(1.0, abs(bound_high)))
    return 0.0


_SEV_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_RANK_SEV = {v: k for k, v in _SEV_RANK.items()}


def _max_severity(a: str, b: str) -> str:
    return _RANK_SEV[max(_SEV_RANK.get(a, 0), _SEV_RANK.get(b, 0))]


def _min_severity(a: str, b: str) -> str:
    return _RANK_SEV[min(_SEV_RANK.get(a, 0) or 1, _SEV_RANK.get(b, 0) or 1)]


def severity_summary(violations: list[dict[str, Any]]) -> dict[str, int]:
    """Bucket counts of CRITICAL / HIGH / MEDIUM / LOW from a violation list."""
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in violations or []:
        sev = str(v.get("severity") or "").upper()
        if sev in counts:
            counts[sev] += 1
    return counts
