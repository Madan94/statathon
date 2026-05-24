"""Rule-level confidence scores (explainability-first; not calibrated for surveys)."""


def semantic_dtype_alignment(rule_type: str, is_numeric: bool, is_cat_like: bool) -> float:
    if rule_type in ("numeric_between", "numeric_min"):
        return 0.95 if is_numeric else 0.35
    if rule_type in ("regex_or_null",):
        return 0.92 if True else 0.0
    if rule_type == "categorical_in_set":
        return 0.9 if is_cat_like else 0.45 if not is_numeric else 0.3
    return 0.7


def rule_confidence(*, semantic_confidence: float, dtype_alignment: float, violation_frac: float) -> float:
    """
    Semantic confidence from mapping × dtype fit × certainty that anomalies are violations.
    Few violations ⇒ still high confidence the rule fires correctly on bad rows (not downgrade hard).
    """
    stability = max(0.2, min(1.0, 1.0 - violation_frac * 0.5))
    raw = semantic_confidence * dtype_alignment * stability
    return round(max(0.0, min(1.0, raw)), 4)
