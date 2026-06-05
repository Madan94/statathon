"""Migrate legacy flat blocks[] templates to enterprise AST v2.0."""
from __future__ import annotations

from typing import Any

from template_engine.ast import ids as idgen
from template_engine.ast.enterprise_schema import (
    ContentAST,
    ContentParagraph,
    EnterpriseDocumentAST,
    LayoutAST,
    LayoutBlockRef,
    LayoutPage,
    MetadataAST,
    SemanticAST,
    SemanticNode,
    utc_now_iso,
)
from template_engine.ast.quality import stable_checksum


def is_enterprise_ast(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("metadata"), dict)
        and payload.get("metadata", {}).get("version") == "2.0"
        and "layoutAST" in payload
        and "semanticAST" in payload
    )


def migrate_v1_blocks_to_enterprise(
    payload: dict[str, Any],
    *,
    template_name: str = "Migrated Template",
    source_hash: str | None = None,
) -> dict[str, Any]:
    """Convert v1 ast_json (blocks[]) to enterprise document."""
    if is_enterprise_ast(payload):
        return payload

    blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    now = utc_now_iso()
    doc_id = idgen.document_id_from_hash(source_hash or str(payload.get("source_hash") or ""))

    semantic_nodes: list[SemanticNode] = []
    page = LayoutPage(pageId=idgen.page_id(0), width=612.0, height=792.0, blocks=[])
    paragraphs: list[ContentParagraph] = []

    for i, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("block_id") or idgen.section_id(i))
        kind = str(raw.get("kind") or "narrative")
        title = str(raw.get("title") or bid)
        section = str(raw.get("section") or "general")
        hints = raw.get("hints") if isinstance(raw.get("hints"), dict) else {}
        pid = idgen.paragraph_id(i)

        semantic_nodes.append(
            SemanticNode(
                id=bid,
                type="section",
                title=title,
                kind=kind,
                required=bool(raw.get("required", True)),
                hints={**hints, "section": section},
                children=[],
                contentRef=pid if kind in ("narrative", "heading", "list") else None,
                tableRef=idgen.table_id(i) if kind == "table" else None,
            )
        )
        page.blocks.append(
            LayoutBlockRef(
                blockId=idgen.layout_block_id(0, i),
                refType="table" if kind == "table" else ("chart" if kind == "chart" else "content"),
                refId=idgen.table_id(i) if kind == "table" else pid,
            )
        )
        if kind in ("narrative", "heading", "list"):
            paragraphs.append(
                ContentParagraph(id=pid, type="paragraph", content=title, pageRef=idgen.page_id(0))
            )

    if not semantic_nodes:
        semantic_nodes.append(
            SemanticNode(id="section_001", type="section", title=template_name, kind="narrative")
        )

    meta = MetadataAST(
        documentId=doc_id,
        version="2.0",
        language="en",
        createdAt=now,
        updatedAt=now,
        checksum="",
        name=str(payload.get("name") or template_name),
        source_hash=source_hash or payload.get("source_hash"),
        page_count=int(payload.get("page_count") or 0),
        extraction_method=str(payload.get("extraction_method") or "migrated_v1"),
    )

    doc = EnterpriseDocumentAST(
        metadata=meta,
        layoutAST=LayoutAST(pages=[page] if page.blocks else [LayoutPage(pageId=idgen.page_id(0))]),
        semanticAST=SemanticAST(nodes=semantic_nodes),
        contentAST=ContentAST(paragraphs=paragraphs),
        blocks=blocks,
        production_stages=payload.get("production_stages")
        if isinstance(payload.get("production_stages"), dict)
        else {},
    )

    out = doc.to_dict()
    out["metadata"]["checksum"] = stable_checksum(out)
    return out
