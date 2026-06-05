"""Build enterprise AST v2.0 from PDF extraction."""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Callable

from template_engine.ast import ids as idgen
from template_engine.ast.enterprise_schema import (
    AgentAST,
    AgentDef,
    AnalyticsAST,
    AnnotationAST,
    AssetAST,
    BBox,
    ChartAST,
    ChartEntry,
    CitationAST,
    CitationDef,
    ContentAST,
    ContentParagraph,
    EnterpriseDocumentAST,
    EntityDef,
    EntityGraph,
    FactGraph,
    FigureAST,
    FigureEntry,
    GeometryAST,
    GeometryNode,
    KnowledgeGraphAST,
    LayoutAST,
    LayoutBlockRef,
    LayoutPage,
    MetadataAST,
    RelationshipDef,
    RelationshipGraph,
    RetrievalAST,
    RetrievalChunk,
    SemanticAST,
    SemanticNode,
    StyleAST,
    StyleDef,
    TableAST,
    TableASTEntry,
    utc_now_iso,
)
from template_engine.ast.quality import run_quality_gates, stable_checksum
from template_engine.ast.section_classifier import classify_heading, infer_block_kind

logger = logging.getLogger(__name__)

PRODUCTION_STAGE_ORDER = (
    "stage1_immutable_ingestion_vaulting",
    "stage2_vision_spatial_layout_parsing",
    "stage3_semantic_blueprint_extraction",
    "stage4_required_answer_structure_modeling",
    "stage5_detailed_ast_hierarchy_assembly",
    "stage6_final_ast_json_layout",
)


def sha256_of_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "section"


def _pages_from_pdf(path: Path) -> tuple[list[Any], str]:
    from template_engine.ingestion.pdf_loader import load_pdf

    pages, method = load_pdf(path, strict_colpali=True)
    return pages, method


def _page_summaries(pages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in pages:
        tbl_previews = []
        for t in (p.tables or [])[:6]:
            tbl_rows = [[str(c or "") for c in row] for row in (t.rows or [])]
            tbl_previews.append(
                {
                    "row_count": int(t.row_count or len(tbl_rows)),
                    "col_count": int(t.col_count or max((len(r) for r in tbl_rows), default=0)),
                    "preview_rows": tbl_rows[:5],
                }
            )
        out.append(
            {
                "page_index": p.page_index,
                "width": p.width,
                "height": p.height,
                "word_count": p.word_count,
                "has_tables": bool(p.tables),
                "table_count": len(p.tables or []),
                "table_previews": tbl_previews,
                "headings": p.headings[:30],
                "raw_text": p.raw_text or "",
                "raw_text_sample": (p.raw_text or "")[:800],
            }
        )
    return out


def _build_semantic_and_content(
    page_summaries: list[dict[str, Any]],
) -> tuple[list[SemanticNode], list[ContentParagraph], list[TableASTEntry], list[LayoutPage]]:
    semantic_nodes: list[SemanticNode] = []
    paragraphs: list[ContentParagraph] = []
    tables: list[TableASTEntry] = []
    layout_pages: list[LayoutPage] = []
    p_idx = 0
    t_idx = 0
    sec_idx = 0

    for page in page_summaries:
        pi = int(page.get("page_index") or 0)
        pid = idgen.page_id(pi)
        layout_page = LayoutPage(
            pageId=pid,
            width=float(page.get("width") or 612),
            height=float(page.get("height") or 792),
            blocks=[],
        )
        headings = page.get("headings") or []
        if not headings and page.get("raw_text_sample"):
            headings = [page["raw_text_sample"][:80].strip()]

        for hi, heading in enumerate(headings[:15]):
            hs = str(heading).strip()
            if len(hs) < 3:
                continue
            sid = idgen.section_id(sec_idx)
            sec_idx += 1
            section_slug = _slug(hs)
            kind = infer_block_kind(hs, bool(page.get("has_tables")), False)
            classify_heading(hs)
            pid_content = idgen.paragraph_id(p_idx)
            p_idx += 1

            paragraphs.append(
                ContentParagraph(
                    id=pid_content,
                    type="paragraph",
                    content=hs,
                    pageRef=pid,
                )
            )
            semantic_nodes.append(
                SemanticNode(
                    id=sid,
                    type="section",
                    title=hs[:120],
                    kind=kind,
                    required=True,
                    hints={"page_index": pi, "section": section_slug},
                    children=[],
                    contentRef=pid_content,
                )
            )
            layout_page.blocks.append(
                LayoutBlockRef(
                    blockId=idgen.layout_block_id(pi, hi),
                    refType="content",
                    refId=pid_content,
                )
            )

        for tbl in page.get("table_previews") or []:
            tid = idgen.table_id(t_idx)
            t_idx += 1
            rows = tbl.get("preview_rows") or []
            cols = (
                [f"col_{i+1}" for i in range(int(tbl.get("col_count") or max((len(r) for r in rows), default=0)))]
                if rows
                else []
            )
            tables.append(
                TableASTEntry(
                    tableId=tid,
                    title=f"Table on page {pi + 1}",
                    columns=cols,
                    rows=rows,
                    metadata={"row_count": tbl.get("row_count"), "col_count": tbl.get("col_count")},
                    pageRef=pid,
                )
            )
            layout_page.blocks.append(
                LayoutBlockRef(blockId=idgen.layout_block_id(pi, 100 + t_idx), refType="table", refId=tid)
            )
            semantic_nodes.append(
                SemanticNode(
                    id=f"sec_table_{tid}",
                    type="section",
                    title=f"Table on page {pi + 1}",
                    kind="table",
                    required=False,
                    hints={"page_index": pi},
                    tableRef=tid,
                )
            )

        if page.get("raw_text") and not headings:
            pid_content = idgen.paragraph_id(p_idx)
            p_idx += 1
            excerpt = str(page.get("raw_text") or "")[:2000]
            paragraphs.append(
                ContentParagraph(id=pid_content, type="paragraph", content=excerpt, pageRef=pid)
            )
            layout_page.blocks.append(
                LayoutBlockRef(
                    blockId=idgen.layout_block_id(pi, 0),
                    refType="content",
                    refId=pid_content,
                )
            )

        layout_pages.append(layout_page)

    if not semantic_nodes:
        semantic_nodes.append(
            SemanticNode(
                id="section_001",
                type="section",
                title="Document body",
                kind="narrative",
                contentRef=idgen.paragraph_id(0) if paragraphs else None,
            )
        )
        if not paragraphs:
            paragraphs.append(
                ContentParagraph(id=idgen.paragraph_id(0), type="paragraph", content="Extracted document")
            )

    return semantic_nodes, paragraphs, tables, layout_pages


def _build_geometry_and_styles(pages: list[Any]) -> tuple[GeometryAST, StyleAST]:
    geo_nodes: list[GeometryNode] = []
    styles_map: dict[tuple[str, float, bool], str] = {}
    style_list: list[StyleDef] = []
    g_idx = 0
    s_idx = 0

    for p in pages:
        for tb in getattr(p, "text_blocks", []) or []:
            fs = float(getattr(tb, "font_size", 10.0))
            bold = bool(getattr(tb, "bold", False))
            fam = "serif" if fs >= 14 else "sans-serif"
            sk = (fam, fs, bold)
            if sk not in styles_map:
                sid = idgen.style_id(s_idx)
                s_idx += 1
                styles_map[sk] = sid
                style_list.append(
                    StyleDef(
                        styleId=sid,
                        fontFamily=fam,
                        fontSize=fs,
                        fontWeight="bold" if bold else "normal",
                        color="#1e293b",
                    )
                )
            nid = idgen.geometry_node_id("t", g_idx)
            g_idx += 1
            geo_nodes.append(
                GeometryNode(
                    nodeId=nid,
                    bbox=BBox(
                        x=float(getattr(tb, "x0", 0)),
                        y=float(getattr(tb, "y0", 0)),
                        width=max(0, float(getattr(tb, "x1", 0)) - float(getattr(tb, "x0", 0))),
                        height=max(0, float(getattr(tb, "y1", 0)) - float(getattr(tb, "y0", 0))),
                    ),
                    styleId=styles_map.get(sk),
                )
            )

    return GeometryAST(nodes=geo_nodes[:500]), StyleAST(styles=style_list)


def _build_graphs(semantic_nodes: list[SemanticNode], tables: list[TableASTEntry]) -> tuple[
    EntityGraph, RelationshipGraph, KnowledgeGraphAST, CitationAST, RetrievalAST, AgentAST
]:
    entities: list[EntityDef] = []
    relationships: list[RelationshipDef] = []
    chunks: list[RetrievalChunk] = []
    agents: list[AgentDef] = []

    for i, node in enumerate(semantic_nodes[:40]):
        eid = idgen.entity_id(i)
        entities.append(EntityDef(entityId=eid, type="section", name=node.title, properties={"kind": node.kind}))
        if i > 0:
            relationships.append(
                RelationshipDef(
                    relationshipId=idgen.relationship_id(i),
                    source=idgen.entity_id(i - 1),
                    predicate="follows",
                    target=eid,
                    properties={},
                )
            )
        chunks.append(
            RetrievalChunk(
                chunkId=idgen.chunk_id(i),
                text=node.title,
                keywords=[w for w in _slug(node.title).split("_") if w][:8],
                metadata={"nodeId": node.id},
            )
        )

    concepts = [
        {"conceptId": idgen.concept_id(0), "name": "ReportStructure", "children": []},
    ]
    from template_engine.ast.enterprise_schema import ConceptNode

    kg = KnowledgeGraphAST(
        concepts=[ConceptNode.model_validate(c) for c in concepts],
    )

    citations: list[CitationDef] = []
    for i, tbl in enumerate(tables[:20]):
        citations.append(
            CitationDef(
                citationId=idgen.citation_id(i),
                sourceNode=tbl.tableId,
                pageRef=tbl.pageRef or "",
                elementRef=tbl.tableId,
            )
        )

    top_ids = [n.id for n in semantic_nodes[:8]]
    agents.append(
        AgentDef(
            agentId=idgen.agent_id(0),
            scope=["report_generation"],
            visibleNodes=top_ids,
            accessibleFacts=[],
            accessibleEntities=[e.entityId for e in entities[:20]],
        )
    )

    return (
        EntityGraph(entities=entities),
        RelationshipGraph(relationships=relationships),
        kg,
        CitationAST(citations=citations),
        RetrievalAST(chunks=chunks[:200]),
        AgentAST(agents=agents),
    )


def _semantic_to_legacy_blocks(nodes: list[SemanticNode]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    def walk(ns: list[SemanticNode]) -> None:
        for n in ns:
            blocks.append(
                {
                    "block_id": n.id,
                    "kind": n.kind,
                    "title": n.title,
                    "section": n.hints.get("section", "general"),
                    "required": n.required,
                    "hints": n.hints,
                }
            )
            walk(n.children)

    walk(nodes)
    return blocks


def build_enterprise_ast(
    pdf_path: str | Path,
    template_name: str,
    *,
    progress: Callable[[str, int, dict[str, Any]], None] | None = None,
    user_id: int | None = None,
    extraction_job_id: int | None = None,
    source_filename: str | None = None,
) -> tuple[EnterpriseDocumentAST, dict[str, Any]]:
    """Full enterprise extraction from PDF."""
    path = Path(pdf_path)
    diagnostics: dict[str, Any] = {"stages": {}, "doc_id": "MOSPI_TPL_01"}

    def _tick(stage: str, pct: int, payload: dict[str, Any] | None = None) -> None:
        diagnostics["stages"][stage] = payload or {}
        if progress:
            progress(stage, pct, payload or {})

    _tick(PRODUCTION_STAGE_ORDER[0], 10, {"status": "started"})
    file_hash = sha256_of_file(path)
    diagnostics["source_hash"] = file_hash
    _tick(PRODUCTION_STAGE_ORDER[0], 20, {"sha256": file_hash, "status": "completed"})

    _tick(PRODUCTION_STAGE_ORDER[1], 35, {"status": "started"})
    pages, extraction_method = _pages_from_pdf(path) if path.exists() else ([], "unknown")
    if not pages:
        raise RuntimeError("No PDF pages extracted.")

    from template_engine.ingestion.ingestion_vault import persist_post_ingestion_vault

    vault_result = persist_post_ingestion_vault(
        path,
        pages,
        extraction_method,
        user_id=user_id,
        extraction_job_id=extraction_job_id,
        source_filename=source_filename,
    )
    file_hash = vault_result.source_hash
    diagnostics["source_hash"] = file_hash
    diagnostics["vault"] = {
        "vault_pdf_key": vault_result.vault_pdf_key,
        "vault_manifest_key": vault_result.vault_manifest_key,
        "audit_id": vault_result.audit_id,
    }

    page_summaries = _page_summaries(pages)
    _tick(
        PRODUCTION_STAGE_ORDER[1],
        45,
        {
            "page_count": len(pages),
            "extraction_method": extraction_method,
            "vault_pdf_key": vault_result.vault_pdf_key,
            "vault_manifest_key": vault_result.vault_manifest_key,
            "status": "completed",
        },
    )

    _tick(PRODUCTION_STAGE_ORDER[2], 55, {"status": "started"})
    semantic_nodes, paragraphs, tables, layout_pages = _build_semantic_and_content(page_summaries)
    geometry, styles = _build_geometry_and_styles(pages)
    _tick(PRODUCTION_STAGE_ORDER[2], 65, {"semantic_count": len(semantic_nodes), "status": "completed"})

    _tick(PRODUCTION_STAGE_ORDER[3], 75, {"status": "started"})
    entities, relationships, kg, citations, retrieval, agent_ast = _build_graphs(semantic_nodes, tables)
    _tick(PRODUCTION_STAGE_ORDER[3], 82, {"status": "completed"})

    _tick(PRODUCTION_STAGE_ORDER[4], 90, {"status": "started"})
    now = utc_now_iso()
    doc_id = idgen.document_id_from_hash(file_hash)

    meta = MetadataAST(
        documentId=doc_id,
        version="2.0",
        language="en",
        createdAt=now,
        updatedAt=now,
        checksum="",
        name=template_name or "Extracted Template",
        source_hash=file_hash,
        page_count=len(pages),
        extraction_method=extraction_method,
    )

    doc = EnterpriseDocumentAST(
        metadata=meta,
        layoutAST=LayoutAST(pages=layout_pages),
        styleAST=styles,
        geometryAST=geometry,
        assetAST=AssetAST(assets=[]),
        annotationAST=AnnotationAST(),
        semanticAST=SemanticAST(nodes=semantic_nodes),
        contentAST=ContentAST(paragraphs=paragraphs),
        tableAST=TableAST(tables=tables),
        figureAST=FigureAST(figures=[]),
        chartAST=ChartAST(charts=[]),
        entityGraph=entities,
        relationshipGraph=relationships,
        knowledgeGraph=kg,
        factGraph=FactGraph(facts=[]),
        analyticsAST=AnalyticsAST(),
        citationAST=citations,
        retrievalAST=retrieval,
        agentAST=agent_ast,
        blocks=_semantic_to_legacy_blocks(semantic_nodes),
        production_stages=diagnostics.get("stages", {}),
    )

    payload = doc.to_dict()
    payload["metadata"]["checksum"] = stable_checksum(payload)
    doc.metadata.checksum = payload["metadata"]["checksum"]

    quality = run_quality_gates(doc)
    diagnostics["quality_report"] = quality
    if not quality.get("passed"):
        logger.warning("Enterprise AST quality gates: %s", quality.get("errors"))

    _tick(PRODUCTION_STAGE_ORDER[5], 100, {"quality": quality, "status": "completed"})
    diagnostics["blueprint_payload"] = payload
    return doc, diagnostics
