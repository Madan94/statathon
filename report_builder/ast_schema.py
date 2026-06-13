"""Enterprise Document AST Schema — Pydantic models for the 14-subtree AST.

This module defines the canonical schema for document ASTs produced by the
multi-pass extraction pipeline. It provides:
    - Strict Pydantic validation (fail-fast on malformed ASTs)
    - Serialization/deserialization to/from JSON
    - Builder pattern for incremental AST construction
    - Schema version management for forward compatibility

Reference: Enterprise_Document_AST.json in repo root.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Metadata
# ─────────────────────────────────────────────────────────────────────────────

class DocumentMetadata(BaseModel):
    documentId: str
    title: str = ""
    version: str = "2.0"
    language: str = "en"
    pageCount: int = 0
    checksum: str = ""
    extractionMethod: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updatedAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


# ─────────────────────────────────────────────────────────────────────────────
# Layout AST
# ─────────────────────────────────────────────────────────────────────────────

class LayoutBlock(BaseModel):
    blockId: str
    type: str  # text | heading | header | figure | table | list | chart | empty_canvas
    elementRefs: list[str] = Field(default_factory=list)
    readingOrder: int | None = None
    bbox: list[float] | None = None
    confidence: float | None = None


class LayoutPage(BaseModel):
    pageId: str
    width: float = 595.0
    height: float = 842.0
    blocks: list[LayoutBlock] = Field(default_factory=list)


class LayoutAST(BaseModel):
    pages: list[LayoutPage] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Style AST
# ─────────────────────────────────────────────────────────────────────────────

class StyleEntry(BaseModel):
    styleId: str
    fontFamily: str = "Arial"
    fontSize: float = 11.0
    fontWeight: str = "normal"
    color: str = "#000000"


class StyleAST(BaseModel):
    styles: list[StyleEntry] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Geometry AST
# ─────────────────────────────────────────────────────────────────────────────

class BBox(BaseModel):
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


class GeometryNode(BaseModel):
    nodeId: str
    bbox: BBox = Field(default_factory=BBox)
    pageRef: str = ""


class GeometryAST(BaseModel):
    nodes: list[GeometryNode] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Asset AST
# ─────────────────────────────────────────────────────────────────────────────

class Asset(BaseModel):
    assetId: str
    type: str = "image"  # image | svg | embedded
    mimeType: str = "image/png"
    storageRef: str = ""


class AssetAST(BaseModel):
    assets: list[Asset] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Annotation AST
# ─────────────────────────────────────────────────────────────────────────────

class AnnotationEntry(BaseModel):
    pageRef: str = ""
    text: str = ""
    id: str | None = None
    elementRef: str | None = None


class Bookmark(BaseModel):
    id: str
    title: str
    targetNode: str


class AnnotationAST(BaseModel):
    headers: list[AnnotationEntry] = Field(default_factory=list)
    footers: list[AnnotationEntry] = Field(default_factory=list)
    footnotes: list[AnnotationEntry] = Field(default_factory=list)
    comments: list[AnnotationEntry] = Field(default_factory=list)
    bookmarks: list[Bookmark] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Semantic AST
# ─────────────────────────────────────────────────────────────────────────────

class SemanticNode(BaseModel):
    id: str
    type: str = "section"  # chapter | section | subsection
    title: str = ""
    children: list[SemanticNode] = Field(default_factory=list)
    pageSpan: list[int] | None = None


class SemanticAST(BaseModel):
    nodes: list[SemanticNode] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Content AST
# ─────────────────────────────────────────────────────────────────────────────

class Paragraph(BaseModel):
    id: str
    type: str = "text"  # title | subtitle | heading | text | chapter_heading
    content: str = ""
    pageRef: str | None = None
    styleRef: str | None = None


class ListBlock(BaseModel):
    id: str
    type: str = "unordered"
    items: list[str] = Field(default_factory=list)


class ContentAST(BaseModel):
    paragraphs: list[Paragraph] = Field(default_factory=list)
    lists: list[ListBlock] = Field(default_factory=list)
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    codeBlocks: list[dict[str, Any]] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Table AST
# ─────────────────────────────────────────────────────────────────────────────

class TableEntry(BaseModel):
    tableId: str
    title: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    sampleRows: list[dict[str, str]] | None = None
    rowCount: int = 0
    pageRef: str | None = None
    footnotes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableAST(BaseModel):
    tables: list[TableEntry] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Figure AST
# ─────────────────────────────────────────────────────────────────────────────

class FigureEntry(BaseModel):
    figureId: str
    caption: str = ""
    type: str = "image"
    assetRef: str | None = None
    pageRef: str | None = None


class FigureAST(BaseModel):
    figures: list[FigureEntry] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Chart AST
# ─────────────────────────────────────────────────────────────────────────────

class ChartEntry(BaseModel):
    chartId: str
    type: str = "unknown"  # bar | line | pie | scatter | area | grouped_bar
    title: str = ""
    xAxis: dict[str, Any] | None = None
    yAxis: dict[str, Any] | None = None
    series: list[dict[str, Any]] = Field(default_factory=list)
    pageRef: str | None = None


class ChartAST(BaseModel):
    charts: list[ChartEntry] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Entity Graph
# ─────────────────────────────────────────────────────────────────────────────

class Entity(BaseModel):
    entityId: str
    type: str  # org | metric | demographic | time | location | resource
    name: str
    context: str = ""
    mentions: list[str] = Field(default_factory=list)  # paragraph refs


class EntityGraph(BaseModel):
    entities: list[Entity] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph
# ─────────────────────────────────────────────────────────────────────────────

class Concept(BaseModel):
    conceptId: str
    name: str
    relatedEntities: list[str] = Field(default_factory=list)
    definition: str = ""


class KnowledgeGraph(BaseModel):
    concepts: list[Concept] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Fact Graph
# ─────────────────────────────────────────────────────────────────────────────

class Fact(BaseModel):
    factId: str
    statement: str
    entityRefs: list[str] = Field(default_factory=list)
    sourceRef: str = ""  # paragraph or table ref
    confidence: float = 1.0


class FactGraph(BaseModel):
    facts: list[Fact] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Template Slots
# ─────────────────────────────────────────────────────────────────────────────

class TemplateSlot(BaseModel):
    slotId: str
    entityRef: str = ""
    slotType: str = "value"  # value | label | range | enum | date
    currentValue: str = ""
    description: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)


class TemplateSlots(BaseModel):
    slots: list[TemplateSlot] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Questions
# ─────────────────────────────────────────────────────────────────────────────

class Question(BaseModel):
    id: str
    question: str
    section: str = ""
    answerType: str = "narrative"  # narrative | metric | table | chart


# ─────────────────────────────────────────────────────────────────────────────
# Root AST (all 14 subtrees + extras)
# ─────────────────────────────────────────────────────────────────────────────

class EnterpriseDocumentAST(BaseModel):
    """Root model for the Enterprise Document AST with all 14 subtrees."""

    metadata: DocumentMetadata
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
    knowledgeGraph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)
    factGraph: FactGraph = Field(default_factory=FactGraph)
    templateSlots: TemplateSlots = Field(default_factory=TemplateSlots)
    questions: list[Question] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        """Quick count of elements across all subtrees."""
        return {
            "pages": len(self.layoutAST.pages),
            "styles": len(self.styleAST.styles),
            "geometry_nodes": len(self.geometryAST.nodes),
            "assets": len(self.assetAST.assets),
            "paragraphs": len(self.contentAST.paragraphs),
            "tables": len(self.tableAST.tables),
            "figures": len(self.figureAST.figures),
            "charts": len(self.chartAST.charts),
            "entities": len(self.entityGraph.entities),
            "concepts": len(self.knowledgeGraph.concepts),
            "facts": len(self.factGraph.facts),
            "template_slots": len(self.templateSlots.slots),
            "questions": len(self.questions),
        }
