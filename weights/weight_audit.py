"""Weight application audit helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from core.json_safe import make_json_safe


def build_audit_record(
    *,
    analysis_id: int,
    weight_column: str | None,
    quality_score: float | None,
    user_action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return make_json_safe(
        {
            "analysis_id": analysis_id,
            "phase": "weight_application",
            "weight_column": weight_column,
            "quality_score": quality_score,
            "user_action": user_action,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": payload or {},
        }
    )
