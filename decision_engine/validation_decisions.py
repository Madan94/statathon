"""Validation decision helpers — aggregate pending validation candidates (Phase 3D)."""

from __future__ import annotations


def summarize_validation_decisions(candidates: list[dict] | None) -> dict[str, object]:
    items = [c for c in (candidates or []) if isinstance(c, dict)]
    sev_counts: dict[str, int] = {}
    cols: set[str] = set()
    for row in items:
        if isinstance(row.get("severity"), str):
            k = str(row["severity"]).upper()
            sev_counts[k] = sev_counts.get(k, 0) + 1
        cn = row.get("column")
        if isinstance(cn, str) and cn:
            cols.add(cn)
    return {
        "pending_count": len(items),
        "severity_counts": sev_counts,
        "distinct_columns": len(cols),
    }
