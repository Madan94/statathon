"""Multi-AST core for research-grade report generation.

The Enterprise document AST is a graph of *layered* ASTs each describing one
facet of the rendered document:

  LayoutAST     - Pages and which blocks live on each page (ordering)
  GeometryAST   - Pixel-accurate bbox for every element (x, y, w, h)
  StyleAST      - Font / weight / colour palette
  SemanticAST   - Tree of sections / chapters / subsections (hierarchy)
  ContentAST    - Paragraphs / lists / quotes / code blocks (text content)
  TableAST      - Tables with columns, rows, footnotes, metadata
  FigureAST     - Images / charts with captions + asset refs
  ChartAST      - Chart series + types
  EntityGraph   - Named entities (states, resources, regions)
  RelationshipGraph - Predicates between entities
  KnowledgeGraph    - Concept hierarchy
  FactAST       - Verified factual statements with confidence + sourceRefs
  AnalyticsAST  - Metrics / aggregations / rankings / trends
  CitationAST   - Source provenance
  RetrievalAST  - Embeddings + keyword chunks
  EvidenceAST   - (NEW) Per-claim evidence ledger: claim -> [row_ids, aggregates, charts]
  AgentAST      - Agent scopes + accessible nodes / facts / entities

The contract: a renderer NEVER invents geometry, NEVER auto-flows text, NEVER
makes up a number. Every rendered pixel + every printed claim must trace back
to one of these ASTs.
"""
from .schema import (
    MultiAST, MetadataAST,
    LayoutAST, LayoutPage, LayoutBlock,
    StyleAST, Style,
    GeometryAST, GeometryNode, BBox,
    SemanticAST, SemanticNode,
    ContentAST, Paragraph, ListItem, Quote, CodeBlock,
    TableAST, Table, FigureAST, Figure,
    ChartAST, Chart,
    EntityGraph, Entity,
    RelationshipGraph, Relationship,
    KnowledgeGraph, KGConcept,
    FactAST, Fact,
    AnalyticsAST,
    CitationAST, Citation,
    RetrievalAST, RetrievalChunk,
    EvidenceAST, EvidenceEntry,
    AgentAST, AgentScope,
)
from .loader import load_multi_ast, save_multi_ast
from .coord_loader import load_coord_ast
try:
    from .coord_deep_bi_orchestrator import run_coord_report_strict, CoordReportResult
    run_coord_report = run_coord_report_strict
except ImportError:
    run_coord_report_strict = None
    CoordReportResult = None
    run_coord_report = None
from .builder import MultiASTBuilder

__all__ = [
    "MultiAST", "MetadataAST",
    "LayoutAST", "LayoutPage", "LayoutBlock",
    "StyleAST", "Style",
    "GeometryAST", "GeometryNode", "BBox",
    "SemanticAST", "SemanticNode",
    "ContentAST", "Paragraph", "ListItem", "Quote", "CodeBlock",
    "TableAST", "Table", "FigureAST", "Figure",
    "ChartAST", "Chart",
    "EntityGraph", "Entity",
    "RelationshipGraph", "Relationship",
    "KnowledgeGraph", "KGConcept",
    "FactAST", "Fact",
    "AnalyticsAST",
    "CitationAST", "Citation",
    "RetrievalAST", "RetrievalChunk",
    "EvidenceAST", "EvidenceEntry",
    "AgentAST", "AgentScope",
    "load_multi_ast", "save_multi_ast", "load_coord_ast",
    "run_coord_report", "CoordReportResult",
    "MultiASTBuilder",
]
