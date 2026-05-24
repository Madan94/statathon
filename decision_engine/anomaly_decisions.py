"""Anomaly decision ledger — persist user column actions from the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def summarize_anomaly_decisions(candidates: list[dict] | None) -> dict[str, object]:
    items = [c for c in (candidates or []) if isinstance(c, dict)]
    sev: dict[str, int] = {}
    for row in items:
        if isinstance(row.get("severity"), str):
            k = str(row["severity"]).upper()
            sev[k] = sev.get(k, 0) + 1
    return {"pending_count": len(items), "severity_counts": sev}


def build_decision_payload(
    *,
    decisions: dict[str, str],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge new column decisions into a ledger payload."""
    base = dict(existing or {})
    column_actions = dict(base.get("column_actions") or {})
    for column, action in decisions.items():
        if action not in ("keep", "delete", "normalize"):
            continue
        column_actions[column] = {
            "action": action,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    base["column_actions"] = column_actions
    base["summary"] = summarize_anomaly_decisions(
        [{"severity": v.get("action"), "column": k} for k, v in column_actions.items()]
    )
    return base
