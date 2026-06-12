"""Human-readable fields for validation review UI."""
from __future__ import annotations

from typing import Any


def format_expected(hit: dict[str, Any]) -> str | None:
    params = hit.get("rule_params") or {}
    rt = str(hit.get("rule_type") or "")
    if rt == "numeric_between":
        lo, hi = params.get("min"), params.get("max")
        if lo is not None and hi is not None:
            return f"{lo} - {hi}"
    if rt == "numeric_max" and params.get("max") is not None:
        return f"≤ {params['max']}"
    if rt == "numeric_min" and params.get("min") is not None:
        return f"≥ {params['min']}"
    if rt == "categorical_in_set":
        vals = params.get("values_ci") or params.get("values") or []
        if vals:
            preview = ", ".join(str(v) for v in list(vals)[:5])
            return preview + ("…" if len(vals) > 5 else "")
    expl = hit.get("explanation")
    return str(expl) if expl else None


def format_reason(hit: dict[str, Any], violation: dict[str, Any]) -> str:
    val = violation.get("value")
    expected = format_expected(hit)
    expl = hit.get("explanation")
    rt = str(hit.get("rule_type") or "")

    if val is not None and expected:
        if rt == "numeric_max":
            return f"Value {val} exceeds maximum threshold ({expected})"
        if rt == "numeric_min":
            return f"Value {val} is below minimum threshold ({expected})"
        if rt == "numeric_between":
            return f"Value {val} is outside allowed range ({expected})"
        return f"Value {val} violates expected {expected}"

    if expl:
        return str(expl)
    rule_id = hit.get("rule_id") or "rule"
    return f"Rule {rule_id} flagged row {violation.get('row')}"


def enrich_validation_candidate(cand: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy + new candidates for the review API."""
    out = dict(cand)
    rule = out.get("rule") if isinstance(out.get("rule"), dict) else {}

    if out.get("value") is None and out.get("original_value") is not None:
        out["value"] = out["original_value"]

    if not out.get("rule_id"):
        rid = rule.get("rule_id") if isinstance(rule, dict) else None
        if rid:
            out["rule_id"] = rid

    if not out.get("rule"):
        out["rule"] = out.get("rule_id") or rule.get("rule_id") or rule.get("rule_expression")

    if not out.get("expected"):
        if out.get("rule_params"):
            out["expected"] = format_expected(out)
        elif isinstance(rule, dict) and rule.get("rule_expression"):
            out["expected"] = rule.get("rule_expression")

    if not out.get("reason"):
        if out.get("explanation"):
            out["reason"] = out["explanation"]
        elif out.get("value") is not None and out.get("expected"):
            out["reason"] = f"Value {out['value']} violates expected {out['expected']}"
        else:
            out["reason"] = f"Rule {out.get('rule_id') or out.get('rule') or 'unknown'} violated"

    return out
