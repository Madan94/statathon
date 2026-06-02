"""Validate template AST payloads from the builder form."""
from __future__ import annotations

from typing import Any

ALLOWED_KINDS = frozenset(
    {"narrative", "table", "chart", "metric", "heading", "list"}
)
ALLOWED_SOURCES = frozenset(
    {
        "semantic_mapping",
        "clusters",
        "health_summary",
        "phase3.anomaly_candidates",
        "phase3.imputation_candidates",
        "missing_per_column",
        "column_types",
        "schema_graph",
    }
)


def validate_ast_payload(ast: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ast, dict):
        raise ValueError("ast must be an object")
    blocks = ast.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("ast.blocks must be a non-empty list")
    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for i, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            raise ValueError(f"blocks[{i}] must be an object")
        block_id = str(raw.get("block_id") or "").strip()
        if not block_id:
            raise ValueError(f"blocks[{i}].block_id is required")
        if block_id in seen_ids:
            raise ValueError(f"duplicate block_id: {block_id}")
        seen_ids.add(block_id)
        kind = str(raw.get("kind") or "narrative").strip().lower()
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"blocks[{i}].kind invalid: {kind}")
        title = str(raw.get("title") or block_id).strip()
        section = str(raw.get("section") or "general").strip()
        hints = raw.get("hints") if isinstance(raw.get("hints"), dict) else {}
        src = hints.get("source")
        if src is not None and str(src) not in ALLOWED_SOURCES:
            pass  # allow custom sources for forward compat
        normalized.append(
            {
                "block_id": block_id,
                "kind": kind,
                "title": title,
                "section": section,
                "required": bool(raw.get("required", True)),
                "hints": hints,
            }
        )
    out = dict(ast)
    out["blocks"] = normalized
    if "name" in ast:
        out["name"] = str(ast["name"])
    return out
