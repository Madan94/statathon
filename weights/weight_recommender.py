"""Recommend the best weight column from validated candidates."""
from __future__ import annotations

from typing import Any


def recommend_weight(
    candidates: list[dict[str, Any]],
    validations: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not candidates:
        return None

    scored: list[tuple[str, float, str]] = []
    for cand in candidates:
        col = str(cand.get("column") or "")
        if not col:
            continue
        val = validations.get(col) or {}
        detection_conf = float(cand.get("confidence") or 0.0)
        quality = float(val.get("quality_score") or 0.0)
        coverage = float(val.get("coverage") or 0.0)
        valid = bool(val.get("valid"))
        composite = (
            0.35 * detection_conf
            + 0.35 * quality
            + 0.20 * coverage
            + (0.10 if valid else 0.0)
        )
        reason_parts = []
        if coverage >= 0.95:
            reason_parts.append("high completeness")
        if quality >= 0.85:
            reason_parts.append("strong quality score")
        if detection_conf >= 0.9:
            reason_parts.append("strong survey naming signal")
        if valid:
            reason_parts.append("passes validation rules")
        reason = ", ".join(reason_parts) or "best overall weight quality"
        scored.append((col, round(composite, 4), reason))

    if not scored:
        return None

    scored.sort(key=lambda item: item[1], reverse=True)
    best_col, confidence, reason = scored[0]
    return {
        "recommended": best_col,
        "confidence": confidence,
        "reason": f"Highest survey representation quality ({reason})",
    }
