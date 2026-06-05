"""Enterprise document AST schema (v2.0) — canonical template representation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MetadataAST(BaseModel):
    documentId: str = "doc_001"
    version: str = "2.0"
    language: str = "en"
    createdAt: str = ""
    updatedAt: str = ""
    checksum: str = ""
    name: str = ""
    source_hash: str | None = None
    page_count: int = 0
    extraction_method: str = ""


class BBox(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


class LayoutBlockRef(BaseModel):
    blockId: str = ""
    refType: str = "content"  # content | table | figure | chart | heading
    refId: str = ""


class LayoutPage(BaseModel):
    pageId: str = ""
    width: float = 0.0
    height: float = 0.0
    blocks: list[LayoutBlockRef] = Field(default_factory=list)


class LayoutAST(BaseModel):
    pages: list[LayoutPage] = Field(default_factory=list)


class StyleDef(BaseModel):
    styleId: str = ""
    fontFamily: str = ""
    fontSize: float = 0.0
    fontWeight: str = ""
    color: str = ""


class StyleAST(BaseModel):
    styles: list[StyleDef] = Field(default_factory=list)


class GeometryNode(BaseModel):
    nodeId: str = ""
    bbox: BBox = Field(default_factory=BBox)
    styleId: str | None = None


class GeometryAST(BaseModel):
    nodes: list[GeometryNode] = Field(default_factory=list)


class AssetDef(BaseModel):
    assetId: str = ""
    type: str = ""
    mimeType: str = ""
    storageRef: str = ""


class AssetAST(BaseModel):
    assets: list[AssetDef] = Field(default_factory=list)


class AnnotationAST(BaseModel):
    headers: list[dict[str, Any]] = Field(default_factory=list)
    footers: list[dict[str, Any]] = Field(default_factory=list)
    footnotes: list[dict[str, Any]] = Field(default_factory=list)
    comments: list[dict[str, Any]] = Field(default_factory=list)
    bookmarks: list[dict[str, Any]] = Field(default_factory=list)


class SemanticNode(BaseModel):
    id: str = ""
    type: str = "section"
    title: str = ""
    kind: str = "narrative"  # narrative | table | chart | metric | heading | list
    required: bool = True
    hints: dict[str, Any] = Field(default_factory=dict)
    children: list["SemanticNode"] = Field(default_factory=list)
    contentRef: str | None = None
    tableRef: str | None = None
    figureRef: str | None = None
    chartRef: str | None = None


SemanticNode.model_rebuild()


class SemanticAST(BaseModel):
    nodes: list[SemanticNode] = Field(default_factory=list)


class ContentParagraph(BaseModel):
    id: str = ""
    type: str = "paragraph"
    content: str = ""
    pageRef: str | None = None


class ContentAST(BaseModel):
    paragraphs: list[ContentParagraph] = Field(default_factory=list)
    lists: list[dict[str, Any]] = Field(default_factory=list)
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    codeBlocks: list[dict[str, Any]] = Field(default_factory=list)


class TableASTEntry(BaseModel):
    tableId: str = ""
    title: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    pageRef: str | None = None


class TableAST(BaseModel):
    tables: list[TableASTEntry] = Field(default_factory=list)


class FigureEntry(BaseModel):
    figureId: str = ""
    caption: str = ""
    assetRef: str = ""
    description: str = ""
    pageRef: str | None = None


class FigureAST(BaseModel):
    figures: list[FigureEntry] = Field(default_factory=list)


class ChartSeries(BaseModel):
    name: str = ""
    values: list[Any] = Field(default_factory=list)


class ChartEntry(BaseModel):
    chartId: str = ""
    type: str = "bar"
    title: str = ""
    series: list[ChartSeries] = Field(default_factory=list)


class ChartAST(BaseModel):
    charts: list[ChartEntry] = Field(default_factory=list)


class EntityDef(BaseModel):
    entityId: str = ""
    type: str = ""
    name: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityGraph(BaseModel):
    entities: list[EntityDef] = Field(default_factory=list)


class RelationshipDef(BaseModel):
    relationshipId: str = ""
    source: str = ""
    predicate: str = ""
    target: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationshipGraph(BaseModel):
    relationships: list[RelationshipDef] = Field(default_factory=list)


class ConceptNode(BaseModel):
    conceptId: str = ""
    name: str = ""
    children: list["ConceptNode"] = Field(default_factory=list)


ConceptNode.model_rebuild()


class KnowledgeGraphAST(BaseModel):
    concepts: list[ConceptNode] = Field(default_factory=list)


class FactDef(BaseModel):
    factId: str = ""
    statement: str = ""
    confidence: float = 0.0
    sourceRefs: list[str] = Field(default_factory=list)


class FactGraph(BaseModel):
    facts: list[FactDef] = Field(default_factory=list)


class AnalyticsAST(BaseModel):
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    aggregations: list[dict[str, Any]] = Field(default_factory=list)
    rankings: list[dict[str, Any]] = Field(default_factory=list)
    trends: list[dict[str, Any]] = Field(default_factory=list)


class CitationDef(BaseModel):
    citationId: str = ""
    sourceNode: str = ""
    pageRef: str = ""
    elementRef: str = ""


class CitationAST(BaseModel):
    citations: list[CitationDef] = Field(default_factory=list)


class RetrievalChunk(BaseModel):
    chunkId: str = ""
    text: str = ""
    embeddingId: str = ""
    keywords: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalAST(BaseModel):
    chunks: list[RetrievalChunk] = Field(default_factory=list)


class AgentDef(BaseModel):
    agentId: str = ""
    scope: list[str] = Field(default_factory=list)
    visibleNodes: list[str] = Field(default_factory=list)
    accessibleFacts: list[str] = Field(default_factory=list)
    accessibleEntities: list[str] = Field(default_factory=list)


class AgentAST(BaseModel):
    agents: list[AgentDef] = Field(default_factory=list)


class EnterpriseDocumentAST(BaseModel):
    """Full enterprise template document (schema v2.0)."""

    metadata: MetadataAST = Field(default_factory=MetadataAST)
    layoutAST: LayoutAST = Field(default_factory=LayoutAST)
    styleAST: StyleAST = Field(default_factory=StyleAST)
    geometryAST: GeometryAST = Field(default_factory=GeometryAST)
    assetAST: AssetAST = Field(default_factory=AssetAST)
    annotationAST: AnnotationAST = Field(default_factory=AnnotationAST)
    semanticAST: SemanticAST = Field(default_factory=SemanticAST)
    contentAST: ContentAST = Field(default_factory=ContentAST)
    tableAST: TableAST = Field(default_factory=TableAST)
    figureAST: FigureAST = Field(default_factory=FigureAST)
    chartAST: ChartAST = Field(default_factory=ChartAST)
    entityGraph: EntityGraph = Field(default_factory=EntityGraph)
    relationshipGraph: RelationshipGraph = Field(default_factory=RelationshipGraph)
    knowledgeGraph: KnowledgeGraphAST = Field(default_factory=KnowledgeGraphAST)
    factGraph: FactGraph = Field(default_factory=FactGraph)
    analyticsAST: AnalyticsAST = Field(default_factory=AnalyticsAST)
    citationAST: CitationAST = Field(default_factory=CitationAST)
    retrievalAST: RetrievalAST = Field(default_factory=RetrievalAST)
    agentAST: AgentAST = Field(default_factory=AgentAST)

    # Legacy projection for transitional APIs (optional)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    production_stages: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnterpriseDocumentAST":
        return cls.model_validate(data)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
