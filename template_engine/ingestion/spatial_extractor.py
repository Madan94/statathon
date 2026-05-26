"""Spatial layout extractor — maps page content into semantic regions.

Given raw PageData objects, this module:
  1. Detects the page layout region (header, body, footer, sidebar).
  2. Groups adjacent lines into coherent text paragraphs.
  3. Identifies visual structure: title block, section heading, body text,
     caption, table, footnote.
  4. Produces a structured SpatialLayout per page, ready for the AST builder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from template_engine.ingestion.pdf_loader import PageData, TextBlock


# ---------------------------------------------------------------------------
# Region classification
# ---------------------------------------------------------------------------

_HEADING_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9 \-/:\.]{3,100}$")
_CHAPTER_RE = re.compile(r"^(chapter|section|appendix|annex|part)\s+[\dIVX]+", re.I)
_TABLE_NOTE_RE = re.compile(r"^(note|source|table|fig)\s*[:.]", re.I)


def _classify_block(block: TextBlock, page_height: float) -> str:
    """Assign a semantic role to a text block."""
    y_rel = block.y0 / max(page_height, 1)
    t = block.text.strip()

    if y_rel < 0.08:
        return "header"
    if y_rel > 0.92:
        return "footer"

    if block.font_size >= 18:
        return "title"
    if block.font_size >= 14 or (block.bold and block.font_size >= 11):
        if len(t) < 90:
            return "heading_h1"
    if block.font_size >= 12 or block.bold:
        if len(t) < 120:
            return "heading_h2"
    if block.all_caps and _HEADING_CAPS_RE.match(t) and len(t) < 90:
        return "heading_h2"
    if _CHAPTER_RE.match(t):
        return "heading_h1"
    if _TABLE_NOTE_RE.match(t):
        return "caption"

    return "body"


# ---------------------------------------------------------------------------
# SpatialRegion
# ---------------------------------------------------------------------------

@dataclass
class SpatialRegion:
    role: str                      # title/heading_h1/heading_h2/body/caption/header/footer
    text: str
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    font_size: float = 10.0
    bold: bool = False


@dataclass
class SpatialLayout:
    page_index: int
    width: float
    height: float
    regions: list[SpatialRegion] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    has_charts: bool = False

    @property
    def headings(self) -> list[str]:
        return [
            r.text for r in self.regions
            if r.role in ("title", "heading_h1", "heading_h2")
        ]

    @property
    def body_text(self) -> str:
        return " ".join(r.text for r in self.regions if r.role == "body")

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "width": self.width,
            "height": self.height,
            "headings": self.headings[:20],
            "has_tables": bool(self.tables),
            "table_count": len(self.tables),
            "raw_text_sample": self.body_text[:800],
            "has_charts": self.has_charts,
            "word_count": len(self.body_text.split()),
            "regions": [
                {"role": r.role, "text": r.text[:120], "font_size": r.font_size}
                for r in self.regions[:40]
            ],
        }


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

def extract_spatial_layout(pages: list[PageData]) -> list[SpatialLayout]:
    """Convert raw PageData → structured SpatialLayout per page."""
    layouts: list[SpatialLayout] = []

    for page in pages:
        regions: list[SpatialRegion] = []

        for block in page.text_blocks:
            role = _classify_block(block, page.height)
            # Merge adjacent body lines into paragraphs
            if (
                regions
                and role == "body"
                and regions[-1].role == "body"
                and abs(block.y0 - regions[-1].y1) < 20
            ):
                regions[-1].text += " " + block.text
                regions[-1].y1 = block.y1
                regions[-1].x1 = max(regions[-1].x1, block.x1)
            else:
                regions.append(SpatialRegion(
                    role=role,
                    text=block.text,
                    x0=block.x0,
                    y0=block.y0,
                    x1=block.x1,
                    y1=block.y1,
                    font_size=block.font_size,
                    bold=block.bold,
                ))

        tables = [
            {
                "row_count": t.row_count,
                "col_count": t.col_count,
                "header_row": t.rows[0] if t.rows else [],
                "preview_rows": t.rows[1:4],
            }
            for t in page.tables
        ]

        layouts.append(SpatialLayout(
            page_index=page.page_index,
            width=page.width,
            height=page.height,
            regions=regions,
            tables=tables,
            has_charts=page.has_charts,
        ))

    return layouts
