"""Fluent multi-AST builder.

Used by the report generator to incrementally populate every AST layer
while keeping cross-references consistent (e.g. a Paragraph added here
gets a matching GeometryNode + LayoutBlock reference).
"""
from __future__ import annotations

from typing import Any

from .schema import (
    AnalyticsAST, BBox, Chart, ChartAST, Citation, CitationAST,
    ContentAST, EvidenceAST, EvidenceEntry, Fact, FactAST, Figure, FigureAST,
    GeometryAST, GeometryNode, LayoutAST, LayoutBlock, LayoutPage,
    MultiAST, Paragraph, SemanticAST, SemanticNode, Style, StyleAST,
    Table, TableAST,
)


class MultiASTBuilder:
    """Mutates a MultiAST safely with auto-ID assignment + back-references."""

    def __init__(self, ast: MultiAST | None = None):
        self.ast = ast or MultiAST()
        # ID counters
        self._next: dict[str, int] = {
            "page": 1, "block": 1, "para": 1, "list": 1, "table": 1,
            "figure": 1, "chart": 1, "geom": 1, "evid": 1, "fact": 1,
            "cite": 1, "ent": 1, "rel": 1, "concept": 1,
        }

    # ---------------- ID helpers ----------------

    def _nid(self, key: str, prefix: str) -> str:
        n = self._next[key]
        self._next[key] += 1
        return f"{prefix}_{n:03d}"

    # ---------------- Style ----------------

    def add_style(self, style_id: str, **kwargs: Any) -> Style:
        st = Style(styleId=style_id, **kwargs)
        # Replace if id already exists
        self.ast.styleAST.styles = [s for s in self.ast.styleAST.styles
                                     if s.styleId != style_id]
        self.ast.styleAST.styles.append(st)
        return st

    # ---------------- Pages / blocks ----------------

    def add_page(self, *, page_id: str | None = None,
                 width: float = 595, height: float = 842) -> LayoutPage:
        pid = page_id or self._nid("page", "page")
        page = LayoutPage(pageId=pid, width=width, height=height)
        self.ast.layoutAST.pages.append(page)
        return page

    def add_block(self, page: LayoutPage, *, type_: str,
                  element_refs: list[str] | None = None,
                  block_id: str | None = None) -> LayoutBlock:
        bid = block_id or f"b{len(self.ast.layoutAST.pages)}_{len(page.blocks) + 1}"
        block = LayoutBlock(blockId=bid, type=type_,
                             elementRefs=list(element_refs or []))
        page.blocks.append(block)
        return block

    # ---------------- Geometry ----------------

    def add_geometry(self, *, element_ref: str, bbox: BBox,
                     style_id: str | None = None,
                     page_id: str | None = None,
                     node_id: str | None = None) -> GeometryNode:
        nid = node_id or f"node_{element_ref}"
        node = GeometryNode(nodeId=nid, bbox=bbox, styleId=style_id,
                            pageId=page_id, elementRef=element_ref)
        # Remove any existing node for the same element to keep mapping 1:1
        self.ast.geometryAST.nodes = [n for n in self.ast.geometryAST.nodes
                                       if n.elementRef != element_ref]
        self.ast.geometryAST.nodes.append(node)
        return node

    # ---------------- Content ----------------

    def add_paragraph(self, *, type_: str, content: str,
                       style_id: str | None = None,
                       evidence_refs: list[str] | None = None,
                       para_id: str | None = None) -> Paragraph:
        pid = para_id or self._nid("para", "p")
        para = Paragraph(id=pid, type=type_, content=content,
                          styleId=style_id,
                          evidenceRefs=list(evidence_refs or []))
        self.ast.contentAST.paragraphs.append(para)
        return para

    def add_table(self, *, table_id: str | None = None, title: str,
                   columns: list[str], rows: list[list[Any]],
                   footnotes: list[str] | None = None,
                   metadata: dict[str, Any] | None = None,
                   evidence_refs: list[str] | None = None,
                   style_id: str | None = None) -> Table:
        tid = table_id or self._nid("table", "table")
        t = Table(tableId=tid, title=title, columns=columns, rows=rows,
                   footnotes=list(footnotes or []),
                   metadata=dict(metadata or {}),
                   evidenceRefs=list(evidence_refs or []),
                   styleId=style_id)
        self.ast.tableAST.tables.append(t)
        return t

    def add_chart(self, *, chart_id: str | None = None, type_: str,
                   title: str, series: list[dict[str, Any]],
                   x_axis: str = "", y_axis: str = "",
                   evidence_refs: list[str] | None = None) -> Chart:
        cid = chart_id or self._nid("chart", "chart")
        ch = Chart(chartId=cid, type=type_, title=title, series=series,
                    xAxis=x_axis, yAxis=y_axis,
                    evidenceRefs=list(evidence_refs or []))
        self.ast.chartAST.charts.append(ch)
        return ch

    def add_figure(self, *, figure_id: str | None = None,
                    caption: str = "", asset_ref: str = "",
                    description: str = "") -> Figure:
        fid = figure_id or self._nid("figure", "fig")
        f = Figure(figureId=fid, caption=caption,
                    assetRef=asset_ref, description=description)
        self.ast.figureAST.figures.append(f)
        return f

    # ---------------- Semantic tree ----------------

    def add_section(self, *, node_id: str, title: str,
                     type_: str = "section",
                     parent: SemanticNode | None = None,
                     content_refs: list[str] | None = None) -> SemanticNode:
        n = SemanticNode(id=node_id, type=type_, title=title,
                          contentRefs=list(content_refs or []))
        if parent is None:
            self.ast.semanticAST.nodes.append(n)
        else:
            parent.children.append(n)
        return n

    # ---------------- Evidence ----------------

    def add_evidence(self, *, claim: str, value: Any,
                      source: str = "dataset",
                      row_ids: list[int] | None = None,
                      computation: dict[str, Any] | None = None,
                      confidence: float = 0.0,
                      verified: bool = False,
                      diagnostics: dict[str, Any] | None = None,
                      evidence_id: str | None = None) -> EvidenceEntry:
        eid = evidence_id or self._nid("evid", "ev")
        e = EvidenceEntry(evidenceId=eid, claim=claim, value=value,
                           source=source, row_ids=list(row_ids or []),
                           computation=dict(computation or {}),
                           confidence=float(confidence), verified=bool(verified),
                           diagnostics=dict(diagnostics or {}))
        self.ast.evidenceAST.entries.append(e)
        return e

    # ---------------- Facts ----------------

    def add_fact(self, *, statement: str, confidence: float,
                  source_refs: list[str] | None = None,
                  evidence_refs: list[str] | None = None,
                  fact_id: str | None = None) -> Fact:
        fid = fact_id or self._nid("fact", "fact")
        f = Fact(factId=fid, statement=statement,
                  confidence=float(confidence),
                  sourceRefs=list(source_refs or []),
                  evidenceRefs=list(evidence_refs or []))
        self.ast.factAST.facts.append(f)
        return f
