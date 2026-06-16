"""Assemble weight profile records for persistence."""
from __future__ import annotations

from typing import Any

from core.json_safe import make_json_safe


def build_weight_profile(
    detection: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    return make_json_safe(
        {
            "column": detection.get("column"),
            "confidence": detection.get("confidence"),
            "signals": detection.get("signals") or {},
            "quality_score": validation.get("quality_score"),
            "coverage": validation.get("coverage"),
            "missing_pct": validation.get("missing_pct"),
            "variance": validation.get("variance"),
            "valid": validation.get("valid"),
            "checks": validation.get("checks") or {},
        }
    )
