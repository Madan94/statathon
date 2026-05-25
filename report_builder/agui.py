"""Phase 5 — Block-based AGUI schema.

A rendered job is a tree of Blocks. The frontend reactively renders each block
type. Today the frontend polls REST; the schema is WebSocket-ready (each block
carries a stable `block_id` and a `version` so deltas can be pushed later).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RenderedBlock:
    block_id: str
    kind: str          # 'narrative' | 'table' | 'chart' | 'metric' | 'heading' | 'list'
    title: str
    section: str
    payload: dict[str, Any]      # rendering data (rows, series, paragraph, metrics)
    verifier: dict[str, Any] | None = None  # per-block firewall verdict (Phase 4)
    route: dict[str, Any] | None = None     # Phase 3 routing decision (sql/python/static)
    version: int = 1
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kind": self.kind,
            "title": self.title,
            "section": self.section,
            "payload": self.payload,
            "verifier": self.verifier,
            "route": self.route,
            "version": self.version,
            "generated_at": self.generated_at,
        }


@dataclass
class BlockCanvas:
    job_id: int
    analysis_id: int
    template_name: str
    blocks: list[RenderedBlock] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # Group by section for the UI sidebar
        sections: dict[str, list[dict[str, Any]]] = {}
        for b in self.blocks:
            sections.setdefault(b.section, []).append(b.to_dict())
        return {
            "job_id": self.job_id,
            "analysis_id": self.analysis_id,
            "template_name": self.template_name,
            "summary": self.summary,
            "sections": [
                {"section": s, "blocks": items}
                for s, items in sections.items()
            ],
        }
