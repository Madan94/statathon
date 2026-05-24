"""Anomaly decision ledger stub (user approvals applied later, not in auto-pipeline)."""

from __future__ import annotations


def summarize_anomaly_decisions(candidates: list[dict] | None) -> dict[str, object]:
    items = [c for c in (candidates or []) if isinstance(c, dict)]
    sev: dict[str, int] = {}
    for row in items:
        if isinstance(row.get("severity"), str):
            k = str(row["severity"]).upper()
            sev[k] = sev.get(k, 0) + 1
    return {"pending_count": len(items), "severity_counts": sev}
