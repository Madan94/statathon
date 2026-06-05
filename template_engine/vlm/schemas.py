"""VLM output schemas — unified data model for visual PDF parsing results.

Every VLM backend (ColPali, mock, future models) must produce VLMPageResult
objects. This ensures the downstream extraction/inference pipeline is
backend-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VLMBBox:
    """Bounding box in PDF coordinate space (points, origin top-left)."""
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def to_dict(self) -> dict[str, float]:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VLMBBox:
        return cls(
            x0=float(d.get("x0") or 0),
            y0=float(d.get("y0") or 0),
            x1=float(d.get("x1") or 0),
            y1=float(d.get("y1") or 0),
        )


@dataclass
class VLMRegion:
    """A semantically identified region on a PDF page.

    Roles: title, heading_h1, heading_h2, paragraph, table, chart,
           caption, header, footer, formula, footnote, legend, axis_label
    """
    regionId: str
    role: str = "paragraph"
    text: str = ""
    bbox: VLMBBox = field(default_factory=VLMBBox)
    confidence: float = 1.0
    children: list[str] = field(default_factory=list)  # child regionIds
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "regionId": self.regionId,
            "role": self.role,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
        }
        if self.children:   out["children"] = self.children
        if self.metadata:   out["metadata"] = self.metadata
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VLMRegion:
        return cls(
            regionId=str(d.get("regionId") or ""),
            role=str(d.get("role") or "paragraph"),
            text=str(d.get("text") or ""),
            bbox=VLMBBox.from_dict(d.get("bbox") or {}),
            confidence=float(d.get("confidence") or 1.0),
            children=list(d.get("children") or []),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class VLMEntity:
    """An entity identified by the VLM from visual context.

    sourceRegion links back to the VLMRegion where this entity was found.
    """
    name: str
    entityType: str = "dimension"  # dimension | measure | filter | metadata
    sourceType: str = "table_header"  # table_header | chart_axis | chart_legend | section_heading | narrative_term | footnote | formula_variable
    sourceRegion: str = ""  # regionId
    confidence: float = 1.0
    context: str = ""  # surrounding text for disambiguation

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entityType": self.entityType,
            "sourceType": self.sourceType,
            "sourceRegion": self.sourceRegion,
            "confidence": self.confidence,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VLMEntity:
        return cls(
            name=str(d.get("name") or ""),
            entityType=str(d.get("entityType") or "dimension"),
            sourceType=str(d.get("sourceType") or "table_header"),
            sourceRegion=str(d.get("sourceRegion") or ""),
            confidence=float(d.get("confidence") or 1.0),
            context=str(d.get("context") or ""),
        )


@dataclass
class VLMTableData:
    """Structured table data extracted by VLM."""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    regionId: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"headers": self.headers, "rows": self.rows, "regionId": self.regionId}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VLMTableData:
        return cls(
            headers=list(d.get("headers") or []),
            rows=[list(r) for r in (d.get("rows") or [])],
            regionId=str(d.get("regionId") or ""),
        )


@dataclass
class VLMChartData:
    """Chart metadata extracted by VLM."""
    chartType: str = "bar"  # bar | line | pie | scatter | grouped_bar | stacked_bar
    title: str = ""
    xAxis: str = ""
    yAxis: str = ""
    legendItems: list[str] = field(default_factory=list)
    regionId: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chartType": self.chartType, "title": self.title,
            "xAxis": self.xAxis, "yAxis": self.yAxis,
            "legendItems": self.legendItems, "regionId": self.regionId,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VLMChartData:
        return cls(
            chartType=str(d.get("chartType") or "bar"),
            title=str(d.get("title") or ""),
            xAxis=str(d.get("xAxis") or ""),
            yAxis=str(d.get("yAxis") or ""),
            legendItems=list(d.get("legendItems") or []),
            regionId=str(d.get("regionId") or ""),
        )


@dataclass
class VLMPageResult:
    """Complete VLM extraction result for a single PDF page.

    Contains:
      - Semantic regions (with roles and bounding boxes)
      - Entities identified on this page
      - Structured table data (if tables detected)
      - Chart metadata (if charts detected)
      - Hierarchical relationships between regions (parent-child)
    """
    pageIndex: int
    width: float = 595.0
    height: float = 842.0
    regions: list[VLMRegion] = field(default_factory=list)
    entities: list[VLMEntity] = field(default_factory=list)
    tables: list[VLMTableData] = field(default_factory=list)
    charts: list[VLMChartData] = field(default_factory=list)
    rawText: str = ""
    confidence: float = 1.0  # overall page extraction confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "pageIndex": self.pageIndex,
            "width": self.width,
            "height": self.height,
            "regions": [r.to_dict() for r in self.regions],
            "entities": [e.to_dict() for e in self.entities],
            "tables": [t.to_dict() for t in self.tables],
            "charts": [c.to_dict() for c in self.charts],
            "rawText": self.rawText,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VLMPageResult:
        return cls(
            pageIndex=int(d.get("pageIndex") or 0),
            width=float(d.get("width") or 595),
            height=float(d.get("height") or 842),
            regions=[VLMRegion.from_dict(r) for r in (d.get("regions") or [])],
            entities=[VLMEntity.from_dict(e) for e in (d.get("entities") or [])],
            tables=[VLMTableData.from_dict(t) for t in (d.get("tables") or [])],
            charts=[VLMChartData.from_dict(c) for c in (d.get("charts") or [])],
            rawText=str(d.get("rawText") or ""),
            confidence=float(d.get("confidence") or 1.0),
        )

    @property
    def headings(self) -> list[str]:
        return [r.text for r in self.regions
                if r.role in ("title", "heading_h1", "heading_h2")]

    @property
    def has_tables(self) -> bool:
        return bool(self.tables)

    @property
    def has_charts(self) -> bool:
        return bool(self.charts)
