"""Template serializer — JSON ↔ TemplateAST conversion + default loader."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from template_engine.ast.ast_builder import BlockSpec, DEFAULT_MOSPI_TEMPLATE, TemplateAST


def serialize_template(ast: TemplateAST) -> dict[str, Any]:
    return ast.to_dict()


def deserialize_template(data: dict[str, Any]) -> TemplateAST:
    blocks = [
        BlockSpec(
            block_id=str(b.get("block_id") or f"blk_{i}"),
            kind=str(b.get("kind") or "narrative"),
            title=str(b.get("title") or "Section"),
            section=str(b.get("section") or "body"),
            required=bool(b.get("required", True)),
            hints=b.get("hints") or {},
        )
        for i, b in enumerate(data.get("blocks") or [])
    ]
    return TemplateAST(
        name=str(data.get("name") or "Template"),
        source_hash=data.get("source_hash"),
        page_count=int(data.get("page_count") or 0),
        extraction_method=str(data.get("extraction_method") or "unknown"),
        blocks=blocks,
        manifest=data.get("manifest") or {},
    )


def load_default_mospi() -> TemplateAST:
    return DEFAULT_MOSPI_TEMPLATE


def save_to_json(ast: TemplateAST, path: str | Path) -> None:
    Path(path).write_text(json.dumps(serialize_template(ast), indent=2), encoding="utf-8")


def load_from_json(path: str | Path) -> TemplateAST:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return deserialize_template(data)
