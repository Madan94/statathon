"""Typed AST schemas.

Mirrors the Enterprise_Document_AST.json structure exactly. Every field that
exists in the JSON is represented here so a round-trip load -> save produces
the same content.

Dataclasses are intentionally generous with default values so partially-built
ASTs (e.g. a freshly synthesised report from a dataset) can be progressively
populated before render.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Common primitives
# ---------------------------------------------------------------------------


@dataclass
class BBox:
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BBox:
        return cls(
            x=float(d.get("x") or 0),
            y=float(d.get("y") or 0),
            width=float(d.get("width") or 0),
            height=float(d.get("height") or 0),
        )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@dataclass
class MetadataAST:
    documentId: str = "doc_001"
    version: str = "1.0"
    language: str = "en"
    createdAt: str = ""
    updatedAt: str = ""
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetadataAST:
        return cls(**{k: d.get(k, "") for k in
                      ("documentId", "version", "language",
                       "createdAt", "updatedAt", "checksum")})


# ---------------------------------------------------------------------------
# LayoutAST
# ---------------------------------------------------------------------------


@dataclass
class LayoutBlock:
    blockId: str
    type: str
    elementRefs: list[str] = field(default_factory=list)
    # Inline bbox — present in coordinate-based ASTs (fina-ast style).
    # The coord_loader promotes these into GeometryAST nodes so the renderer
    # still uses the single geometry lookup path.
    inline_bbox: "BBox | None" = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"blockId": self.blockId, "type": self.type,
                                "elementRefs": list(self.elementRefs)}
        if self.inline_bbox is not None:
            out["bbox"] = self.inline_bbox.to_dict()
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LayoutBlock":
        # Accept both elementRef (singular, new coord-AST) and elementRefs (array)
        refs: list[str] = list(d.get("elementRefs") or [])
        singular = d.get("elementRef")
        if singular and singular not in refs:
            refs = [singular]
        bbox_raw = d.get("bbox")
        inline = BBox.from_dict(bbox_raw) if bbox_raw else None
        return cls(blockId=str(d.get("blockId") or ""),
                   type=str(d.get("type") or "text"),
                   elementRefs=refs,
                   inline_bbox=inline)


@dataclass
class LayoutPage:
    pageId: str
    width: float
    height: float
    blocks: list[LayoutBlock] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"pageId": self.pageId, "width": self.width,
                "height": self.height,
                "blocks": [b.to_dict() for b in self.blocks]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LayoutPage:
        return cls(pageId=str(d.get("pageId") or ""),
                   width=float(d.get("width") or 595),
                   height=float(d.get("height") or 842),
                   blocks=[LayoutBlock.from_dict(b) for b in (d.get("blocks") or [])])


@dataclass
class LayoutAST:
    pages: list[LayoutPage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"pages": [p.to_dict() for p in self.pages]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LayoutAST:
        return cls(pages=[LayoutPage.from_dict(p) for p in (d.get("pages") or [])])


# ---------------------------------------------------------------------------
# StyleAST
# ---------------------------------------------------------------------------


@dataclass
class Style:
    styleId: str
    fontFamily: str = "Helvetica"
    fontSize: float = 10
    fontWeight: str = "normal"
    color: str = "#000000"
    italic: bool = False
    alignment: str = "left"
    leading: float | None = None
    spaceBefore: float = 0
    spaceAfter: float = 0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Style:
        return cls(
            styleId=str(d.get("styleId") or ""),
            fontFamily=str(d.get("fontFamily") or "Helvetica"),
            fontSize=float(d.get("fontSize") or 10),
            fontWeight=str(d.get("fontWeight") or "normal"),
            color=str(d.get("color") or "#000000"),
            italic=bool(d.get("italic") or
                        str(d.get("fontWeight", "")).lower() == "italic"),
            alignment=str(d.get("alignment") or "left"),
            leading=d.get("leading"),
            spaceBefore=float(d.get("spaceBefore") or 0),
            spaceAfter=float(d.get("spaceAfter") or 0),
        )


@dataclass
class StyleAST:
    styles: list[Style] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"styles": [s.to_dict() for s in self.styles]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StyleAST:
        return cls(styles=[Style.from_dict(s) for s in (d.get("styles") or [])])

    def by_id(self, sid: str) -> Style | None:
        for s in self.styles:
            if s.styleId == sid:
                return s
        return None


# ---------------------------------------------------------------------------
# GeometryAST
# ---------------------------------------------------------------------------


@dataclass
class GeometryNode:
    nodeId: str
    bbox: BBox = field(default_factory=BBox)
    styleId: str | None = None
    pageId: str | None = None
    elementRef: str | None = None
    # Optional chart components (e.g. pre-computed pie slices from a coord-AST).
    # Shape: [{"type": "pie_slice", "label": str, "percentage": float, "color": str}, ...]
    components: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"nodeId": self.nodeId, "bbox": self.bbox.to_dict()}
        if self.styleId:    out["styleId"] = self.styleId
        if self.pageId:     out["pageId"]  = self.pageId
        if self.elementRef: out["elementRef"] = self.elementRef
        if self.components: out["components"] = self.components
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GeometryNode":
        return cls(nodeId=str(d.get("nodeId") or d.get("id") or ""),
                   bbox=BBox.from_dict(d.get("bbox") or {}),
                   styleId=d.get("styleId") or d.get("style"),
                   pageId=d.get("pageId"),
                   elementRef=d.get("elementRef"),
                   components=list(d.get("components") or []))


@dataclass
class GeometryAST:
    nodes: list[GeometryNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self.nodes]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GeometryAST:
        return cls(nodes=[GeometryNode.from_dict(n) for n in (d.get("nodes") or [])])

    def by_id(self, nid: str) -> GeometryNode | None:
        for n in self.nodes:
            if n.nodeId == nid:
                return n
        return None

    def by_element_ref(self, element_id: str) -> GeometryNode | None:
        """Find the geometry node anchored to a content element (paragraph, table)."""
        # Common conventions: nodeId may be "node_<element>" or elementRef may be set.
        for n in self.nodes:
            if n.elementRef == element_id:
                return n
            if n.nodeId == element_id or n.nodeId.endswith(element_id):
                return n
        return None


# ---------------------------------------------------------------------------
# SemanticAST
# ---------------------------------------------------------------------------


@dataclass
class SemanticNode:
    id: str
    type: str = "section"
    title: str = ""
    children: list[SemanticNode] = field(default_factory=list)
    contentRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "title": self.title,
                "children": [c.to_dict() for c in self.children],
                "contentRefs": self.contentRefs}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SemanticNode:
        return cls(id=str(d.get("id") or ""),
                   type=str(d.get("type") or "section"),
                   title=str(d.get("title") or ""),
                   children=[SemanticNode.from_dict(c)
                             for c in (d.get("children") or [])],
                   contentRefs=list(d.get("contentRefs") or []))


@dataclass
class SemanticAST:
    nodes: list[SemanticNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self.nodes]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SemanticAST:
        return cls(nodes=[SemanticNode.from_dict(n)
                          for n in (d.get("nodes") or [])])


# ---------------------------------------------------------------------------
# ContentAST
# ---------------------------------------------------------------------------


@dataclass
class Paragraph:
    id: str
    type: str = "text"  # title | subtitle | heading | chapter_heading | text | caption
    content: str = ""
    styleId: str | None = None
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = {"id": self.id, "type": self.type, "content": self.content}
        if self.styleId: out["styleId"] = self.styleId
        if self.evidenceRefs: out["evidenceRefs"] = self.evidenceRefs
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Paragraph:
        return cls(id=str(d.get("id") or ""),
                   type=str(d.get("type") or "text"),
                   content=str(d.get("content") or ""),
                   styleId=d.get("styleId"),
                   evidenceRefs=list(d.get("evidenceRefs") or []))


@dataclass
class ListItem:
    id: str
    items: list[str] = field(default_factory=list)
    ordered: bool = False
    styleId: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "items": self.items, "ordered": self.ordered,
                "styleId": self.styleId} if self.styleId else \
               {"id": self.id, "items": self.items, "ordered": self.ordered}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ListItem:
        return cls(id=str(d.get("id") or ""),
                   items=list(d.get("items") or []),
                   ordered=bool(d.get("ordered") or False),
                   styleId=d.get("styleId"))


@dataclass
class Quote:
    id: str
    content: str = ""
    attribution: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "content": self.content, "attribution": self.attribution}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Quote:
        return cls(id=str(d.get("id") or ""),
                   content=str(d.get("content") or ""),
                   attribution=str(d.get("attribution") or ""))


@dataclass
class CodeBlock:
    id: str
    code: str = ""
    language: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "code": self.code, "language": self.language}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CodeBlock:
        return cls(id=str(d.get("id") or ""),
                   code=str(d.get("code") or ""),
                   language=str(d.get("language") or ""))


@dataclass
class ContentAST:
    paragraphs: list[Paragraph] = field(default_factory=list)
    lists: list[ListItem] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)
    codeBlocks: list[CodeBlock] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"paragraphs": [p.to_dict() for p in self.paragraphs],
                "lists": [l.to_dict() for l in self.lists],
                "quotes": [q.to_dict() for q in self.quotes],
                "codeBlocks": [c.to_dict() for c in self.codeBlocks]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ContentAST:
        return cls(paragraphs=[Paragraph.from_dict(p)
                                for p in (d.get("paragraphs") or [])],
                   lists=[ListItem.from_dict(l) for l in (d.get("lists") or [])],
                   quotes=[Quote.from_dict(q) for q in (d.get("quotes") or [])],
                   codeBlocks=[CodeBlock.from_dict(c)
                                for c in (d.get("codeBlocks") or [])])

    def paragraph_by_id(self, pid: str) -> Paragraph | None:
        for p in self.paragraphs:
            if p.id == pid:
                return p
        return None


# ---------------------------------------------------------------------------
# TableAST / FigureAST / ChartAST
# ---------------------------------------------------------------------------


@dataclass
class Table:
    tableId: str
    title: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    evidenceRefs: list[str] = field(default_factory=list)
    styleId: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "tableId": self.tableId, "title": self.title,
            "columns": self.columns, "rows": self.rows,
            "footnotes": self.footnotes, "metadata": self.metadata,
        }
        if self.evidenceRefs: out["evidenceRefs"] = self.evidenceRefs
        if self.styleId: out["styleId"] = self.styleId
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Table:
        return cls(tableId=str(d.get("tableId") or ""),
                   title=str(d.get("title") or ""),
                   columns=list(d.get("columns") or []),
                   rows=[list(r) if isinstance(r, list) else [r]
                         for r in (d.get("rows") or [])],
                   footnotes=list(d.get("footnotes") or []),
                   metadata=dict(d.get("metadata") or {}),
                   evidenceRefs=list(d.get("evidenceRefs") or []),
                   styleId=d.get("styleId"))


@dataclass
class TableAST:
    tables: list[Table] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tables": [t.to_dict() for t in self.tables]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TableAST:
        return cls(tables=[Table.from_dict(t) for t in (d.get("tables") or [])])

    def by_id(self, tid: str) -> Table | None:
        for t in self.tables:
            if t.tableId == tid:
                return t
        return None


@dataclass
class Figure:
    figureId: str
    caption: str = ""
    assetRef: str = ""
    description: str = ""
    # When the figure is data-driven, the binder populates `computed_chart`
    # with a shape:
    #   {"type": "pie"|"bar"|"line",
    #    "title": str,
    #    "data": [{"label": str, "value": float}, ...]}
    # The renderer reads this and draws a real chart at the figure's bbox.
    computed_chart: dict[str, Any] | None = None
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"figureId": self.figureId, "caption": self.caption,
                                "assetRef": self.assetRef,
                                "description": self.description}
        if self.computed_chart is not None:
            out["computed_chart"] = self.computed_chart
        if self.evidenceRefs:
            out["evidenceRefs"] = self.evidenceRefs
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Figure:
        return cls(figureId=str(d.get("figureId") or ""),
                   caption=str(d.get("caption") or ""),
                   assetRef=str(d.get("assetRef") or ""),
                   description=str(d.get("description") or ""),
                   computed_chart=d.get("computed_chart"),
                   evidenceRefs=list(d.get("evidenceRefs") or []))


@dataclass
class FigureAST:
    figures: list[Figure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"figures": [f.to_dict() for f in self.figures]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FigureAST:
        return cls(figures=[Figure.from_dict(f) for f in (d.get("figures") or [])])

    def by_id(self, fid: str) -> Figure | None:
        for f in self.figures:
            if f.figureId == fid:
                return f
        return None


@dataclass
class Chart:
    chartId: str
    type: str = "bar"
    title: str = ""
    series: list[dict[str, Any]] = field(default_factory=list)
    xAxis: str = ""
    yAxis: str = ""
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = {"chartId": self.chartId, "type": self.type, "title": self.title,
               "series": self.series}
        if self.xAxis: out["xAxis"] = self.xAxis
        if self.yAxis: out["yAxis"] = self.yAxis
        if self.evidenceRefs: out["evidenceRefs"] = self.evidenceRefs
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Chart:
        return cls(chartId=str(d.get("chartId") or ""),
                   type=str(d.get("type") or "bar"),
                   title=str(d.get("title") or ""),
                   series=list(d.get("series") or []),
                   xAxis=str(d.get("xAxis") or ""),
                   yAxis=str(d.get("yAxis") or ""),
                   evidenceRefs=list(d.get("evidenceRefs") or []))


@dataclass
class ChartAST:
    charts: list[Chart] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"charts": [c.to_dict() for c in self.charts]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChartAST:
        return cls(charts=[Chart.from_dict(c) for c in (d.get("charts") or [])])

    def by_id(self, cid: str) -> Chart | None:
        for c in self.charts:
            if c.chartId == cid:
                return c
        return None


# ---------------------------------------------------------------------------
# Knowledge / Entity / Relationship / Fact / Analytics / Citation / Retrieval / Agent
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    entityId: str
    type: str = ""
    name: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntityGraph:
    entities: list[Entity] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"entities": [
            {"entityId": e.entityId, "type": e.type, "name": e.name,
             "properties": e.properties} for e in self.entities]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EntityGraph:
        return cls(entities=[Entity(entityId=str(e.get("entityId") or ""),
                                     type=str(e.get("type") or ""),
                                     name=str(e.get("name") or ""),
                                     properties=dict(e.get("properties") or {}))
                              for e in (d.get("entities") or [])])


@dataclass
class Relationship:
    relationshipId: str
    source: str = ""
    predicate: str = ""
    target: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipGraph:
    relationships: list[Relationship] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"relationships": [
            {"relationshipId": r.relationshipId, "source": r.source,
             "predicate": r.predicate, "target": r.target,
             "properties": r.properties} for r in self.relationships]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RelationshipGraph:
        return cls(relationships=[
            Relationship(relationshipId=str(r.get("relationshipId") or ""),
                         source=str(r.get("source") or ""),
                         predicate=str(r.get("predicate") or ""),
                         target=str(r.get("target") or ""),
                         properties=dict(r.get("properties") or {}))
            for r in (d.get("relationships") or [])])


@dataclass
class KGConcept:
    conceptId: str
    name: str = ""
    children: list[KGConcept] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)


@dataclass
class KnowledgeGraph:
    concepts: list[KGConcept] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def dump(c: KGConcept) -> dict[str, Any]:
            return {"conceptId": c.conceptId, "name": c.name,
                    "children": [dump(ch) for ch in c.children],
                    "synonyms": c.synonyms}
        return {"concepts": [dump(c) for c in self.concepts]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KnowledgeGraph:
        def make(c: Any) -> KGConcept:
            # Children can be either a dict (full concept) or a string (concept name)
            if isinstance(c, str):
                return KGConcept(conceptId="", name=c, children=[], synonyms=[])
            if not isinstance(c, dict):
                return KGConcept(conceptId="", name=str(c), children=[], synonyms=[])
            return KGConcept(conceptId=str(c.get("conceptId") or ""),
                             name=str(c.get("name") or ""),
                             children=[make(ch) for ch in (c.get("children") or [])],
                             synonyms=list(c.get("synonyms") or []))
        return cls(concepts=[make(c) for c in (d.get("concepts") or [])])


@dataclass
class Fact:
    factId: str
    statement: str = ""
    confidence: float = 0.0
    sourceRefs: list[str] = field(default_factory=list)
    evidenceRefs: list[str] = field(default_factory=list)


@dataclass
class FactAST:
    facts: list[Fact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"facts": [
            {"factId": f.factId, "statement": f.statement,
             "confidence": f.confidence, "sourceRefs": f.sourceRefs,
             "evidenceRefs": f.evidenceRefs} for f in self.facts]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FactAST:
        return cls(facts=[
            Fact(factId=str(f.get("factId") or ""),
                 statement=str(f.get("statement") or ""),
                 confidence=float(f.get("confidence") or 0),
                 sourceRefs=list(f.get("sourceRefs") or []),
                 evidenceRefs=list(f.get("evidenceRefs") or []))
            for f in (d.get("facts") or [])])

    def by_id(self, fid: str) -> Fact | None:
        for f in self.facts:
            if f.factId == fid:
                return f
        return None


@dataclass
class AnalyticsAST:
    metrics: list[dict[str, Any]] = field(default_factory=list)
    aggregations: list[dict[str, Any]] = field(default_factory=list)
    rankings: list[dict[str, Any]] = field(default_factory=list)
    trends: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"metrics": self.metrics, "aggregations": self.aggregations,
                "rankings": self.rankings, "trends": self.trends}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AnalyticsAST:
        return cls(metrics=list(d.get("metrics") or []),
                   aggregations=list(d.get("aggregations") or []),
                   rankings=list(d.get("rankings") or []),
                   trends=list(d.get("trends") or []))


@dataclass
class Citation:
    citationId: str
    sourceNode: str = ""
    pageRef: str = ""
    elementRef: str = ""


@dataclass
class CitationAST:
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"citations": [
            {"citationId": c.citationId, "sourceNode": c.sourceNode,
             "pageRef": c.pageRef, "elementRef": c.elementRef}
            for c in self.citations]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CitationAST:
        return cls(citations=[
            Citation(citationId=str(c.get("citationId") or ""),
                     sourceNode=str(c.get("sourceNode") or ""),
                     pageRef=str(c.get("pageRef") or ""),
                     elementRef=str(c.get("elementRef") or ""))
            for c in (d.get("citations") or [])])


@dataclass
class RetrievalChunk:
    chunkId: str
    text: str = ""
    embeddingId: str = ""
    keywords: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalAST:
    chunks: list[RetrievalChunk] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"chunks": [
            {"chunkId": c.chunkId, "text": c.text, "embeddingId": c.embeddingId,
             "keywords": c.keywords, "metadata": c.metadata}
            for c in self.chunks]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RetrievalAST:
        return cls(chunks=[
            RetrievalChunk(chunkId=str(c.get("chunkId") or ""),
                           text=str(c.get("text") or ""),
                           embeddingId=str(c.get("embeddingId") or ""),
                           keywords=list(c.get("keywords") or []),
                           metadata=dict(c.get("metadata") or {}))
            for c in (d.get("chunks") or [])])


# ---------------------------------------------------------------------------
# EvidenceAST (NEW — the zero-hallucination ledger)
# ---------------------------------------------------------------------------


@dataclass
class EvidenceEntry:
    """One claim mapped to its supporting data.

    `claim` is the prose statement; `value` is the numeric or string assertion;
    `source` describes how the value was computed; `row_ids` are the dataset
    rows that participated; `computation` records the operation deterministically
    so it can be re-run; `confidence` is the calibrated 0..1 score from the
    Verifier.
    """
    evidenceId: str
    claim: str
    value: Any = None
    source: str = "dataset"   # 'dataset' | 'aggregate' | 'kg' | 'rulebook' | 'history'
    row_ids: list[int] = field(default_factory=list)
    computation: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    verified: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"evidenceId": self.evidenceId, "claim": self.claim,
                "value": self.value, "source": self.source,
                "row_ids": self.row_ids, "computation": self.computation,
                "confidence": self.confidence, "verified": self.verified,
                "diagnostics": self.diagnostics}


@dataclass
class EvidenceAST:
    entries: list[EvidenceEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvidenceAST:
        out = cls()
        for e in (d.get("entries") or []):
            out.entries.append(EvidenceEntry(
                evidenceId=str(e.get("evidenceId") or ""),
                claim=str(e.get("claim") or ""),
                value=e.get("value"),
                source=str(e.get("source") or "dataset"),
                row_ids=list(e.get("row_ids") or []),
                computation=dict(e.get("computation") or {}),
                confidence=float(e.get("confidence") or 0),
                verified=bool(e.get("verified") or False),
                diagnostics=dict(e.get("diagnostics") or {}),
            ))
        return out

    def by_id(self, eid: str) -> EvidenceEntry | None:
        for e in self.entries:
            if e.evidenceId == eid:
                return e
        return None


# ---------------------------------------------------------------------------
# AgentAST
# ---------------------------------------------------------------------------


@dataclass
class AgentScope:
    agentId: str
    scope: list[str] = field(default_factory=list)
    visibleNodes: list[str] = field(default_factory=list)
    accessibleFacts: list[str] = field(default_factory=list)
    accessibleEntities: list[str] = field(default_factory=list)


@dataclass
class AgentAST:
    agents: list[AgentScope] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"agents": [
            {"agentId": a.agentId, "scope": a.scope,
             "visibleNodes": a.visibleNodes, "accessibleFacts": a.accessibleFacts,
             "accessibleEntities": a.accessibleEntities}
            for a in self.agents]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentAST:
        return cls(agents=[
            AgentScope(agentId=str(a.get("agentId") or ""),
                       scope=list(a.get("scope") or []),
                       visibleNodes=list(a.get("visibleNodes") or []),
                       accessibleFacts=list(a.get("accessibleFacts") or []),
                       accessibleEntities=list(a.get("accessibleEntities") or []))
            for a in (d.get("agents") or [])])


# ---------------------------------------------------------------------------
# Top-level MultiAST
# ---------------------------------------------------------------------------


@dataclass
class AnnotationAST:
    headers: list[Any] = field(default_factory=list)
    footers: list[Any] = field(default_factory=list)
    footnotes: list[Any] = field(default_factory=list)
    comments: list[Any] = field(default_factory=list)
    bookmarks: list[Any] = field(default_factory=list)


@dataclass
class AssetAST:
    assets: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MultiAST:
    metadata: MetadataAST = field(default_factory=MetadataAST)
    layoutAST: LayoutAST = field(default_factory=LayoutAST)
    styleAST: StyleAST = field(default_factory=StyleAST)
    geometryAST: GeometryAST = field(default_factory=GeometryAST)
    assetAST: AssetAST = field(default_factory=AssetAST)
    annotationAST: AnnotationAST = field(default_factory=AnnotationAST)
    semanticAST: SemanticAST = field(default_factory=SemanticAST)
    contentAST: ContentAST = field(default_factory=ContentAST)
    tableAST: TableAST = field(default_factory=TableAST)
    figureAST: FigureAST = field(default_factory=FigureAST)
    chartAST: ChartAST = field(default_factory=ChartAST)
    entityGraph: EntityGraph = field(default_factory=EntityGraph)
    relationshipGraph: RelationshipGraph = field(default_factory=RelationshipGraph)
    knowledgeGraph: KnowledgeGraph = field(default_factory=KnowledgeGraph)
    factAST: FactAST = field(default_factory=FactAST)
    analyticsAST: AnalyticsAST = field(default_factory=AnalyticsAST)
    citationAST: CitationAST = field(default_factory=CitationAST)
    retrievalAST: RetrievalAST = field(default_factory=RetrievalAST)
    evidenceAST: EvidenceAST = field(default_factory=EvidenceAST)
    agentAST: AgentAST = field(default_factory=AgentAST)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata":           self.metadata.to_dict(),
            "layoutAST":          self.layoutAST.to_dict(),
            "styleAST":           self.styleAST.to_dict(),
            "geometryAST":        self.geometryAST.to_dict(),
            "assetAST":           {"assets": self.assetAST.assets},
            "annotationAST":      {"headers": self.annotationAST.headers,
                                   "footers": self.annotationAST.footers,
                                   "footnotes": self.annotationAST.footnotes,
                                   "comments": self.annotationAST.comments,
                                   "bookmarks": self.annotationAST.bookmarks},
            "semanticAST":        self.semanticAST.to_dict(),
            "contentAST":         self.contentAST.to_dict(),
            "tableAST":           self.tableAST.to_dict(),
            "figureAST":          self.figureAST.to_dict(),
            "chartAST":           self.chartAST.to_dict(),
            "entityGraph":        self.entityGraph.to_dict(),
            "relationshipGraph":  self.relationshipGraph.to_dict(),
            "knowledgeGraph":     self.knowledgeGraph.to_dict(),
            "factAST":            self.factAST.to_dict(),
            "analyticsAST":       self.analyticsAST.to_dict(),
            "citationAST":        self.citationAST.to_dict(),
            "retrievalAST":       self.retrievalAST.to_dict(),
            "evidenceAST":        self.evidenceAST.to_dict(),
            "agentAST":           self.agentAST.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MultiAST:
        ann = d.get("annotationAST") or {}
        ast = d.get("assetAST") or {}
        return cls(
            metadata=MetadataAST.from_dict(d.get("metadata") or {}),
            layoutAST=LayoutAST.from_dict(d.get("layoutAST") or {}),
            styleAST=StyleAST.from_dict(d.get("styleAST") or {}),
            geometryAST=GeometryAST.from_dict(d.get("geometryAST") or {}),
            assetAST=AssetAST(assets=list(ast.get("assets") or [])),
            annotationAST=AnnotationAST(
                headers=list(ann.get("headers") or []),
                footers=list(ann.get("footers") or []),
                footnotes=list(ann.get("footnotes") or []),
                comments=list(ann.get("comments") or []),
                bookmarks=list(ann.get("bookmarks") or []),
            ),
            semanticAST=SemanticAST.from_dict(d.get("semanticAST") or {}),
            contentAST=ContentAST.from_dict(d.get("contentAST") or {}),
            tableAST=TableAST.from_dict(d.get("tableAST") or {}),
            figureAST=FigureAST.from_dict(d.get("figureAST") or {}),
            chartAST=ChartAST.from_dict(d.get("chartAST") or {}),
            entityGraph=EntityGraph.from_dict(d.get("entityGraph") or {}),
            relationshipGraph=RelationshipGraph.from_dict(d.get("relationshipGraph") or {}),
            knowledgeGraph=KnowledgeGraph.from_dict(d.get("knowledgeGraph") or {}),
            factAST=FactAST.from_dict(d.get("factAST") or {}),
            analyticsAST=AnalyticsAST.from_dict(d.get("analyticsAST") or {}),
            citationAST=CitationAST.from_dict(d.get("citationAST") or {}),
            retrievalAST=RetrievalAST.from_dict(d.get("retrievalAST") or {}),
            evidenceAST=EvidenceAST.from_dict(d.get("evidenceAST") or {}),
            agentAST=AgentAST.from_dict(d.get("agentAST") or {}),
        )
