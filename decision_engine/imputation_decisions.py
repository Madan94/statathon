"""Imputation decision ledger stub (Phase 3D)."""

from __future__ import annotations


def summarize_imputation_decisions(candidates: list[dict] | None) -> dict[str, object]:
    items = [c for c in (candidates or []) if isinstance(c, dict)]
    bands: dict[str, int] = {}
    for row in items:
        b = row.get("confidence_band")
        if isinstance(b, str):
            bands[b] = bands.get(b, 0) + 1
    return {"pending_columns": len(items), "confidence_bands": bands}
