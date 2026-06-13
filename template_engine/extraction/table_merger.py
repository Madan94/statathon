"""Page-Spanning Table Merger — detects and merges tables split across pages.

PLFS reports frequently have large tables (e.g., state-level data with 36+ rows)
that span multiple pages. This module detects continuation patterns and merges
them into single logical tables.

Detection heuristics:
  1. Page N ends with a table region as the last content block
  2. Page N+1 starts with a table region as the first content block
  3. Column count matches (±1 for row numbering columns)
  4. Header text on page N+1 matches "contd." or is structurally similar

The merger runs AFTER VLM extraction but BEFORE entity deduplication,
inserting merged tables as a single VLMTableData with combined rows.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from template_engine.vlm.schemas import VLMPageResult, VLMRegion, VLMTableData

logger = logging.getLogger(__name__)

# Patterns indicating table continuation
_CONTD_PATTERNS = re.compile(
    r"(cont[d']?\.?|continued|contd|continu[ée]d)",
    re.IGNORECASE,
)

# Minimum header similarity for merge
_HEADER_SIMILARITY_THRESHOLD = 0.75

# Maximum page gap allowed for continuation (usually 1)
_MAX_PAGE_GAP = 1


def merge_spanning_tables(pages: list[VLMPageResult]) -> list[VLMPageResult]:
    """Detect and merge page-spanning tables across consecutive pages.

    Modifies pages in-place: merged tables are consolidated on the first page,
    and removed from subsequent pages.

    Returns:
        The same list of pages with merged tables.
    """
    if len(pages) < 2:
        return pages

    # Sort pages by index
    sorted_pages = sorted(pages, key=lambda p: p.pageIndex)
    merged_count = 0

    i = 0
    while i < len(sorted_pages) - 1:
        current_page = sorted_pages[i]
        next_page = sorted_pages[i + 1]

        # Check page gap
        if next_page.pageIndex - current_page.pageIndex > _MAX_PAGE_GAP:
            i += 1
            continue

        # Find trailing table on current page
        trailing_table = _find_trailing_table(current_page)
        if trailing_table is None:
            i += 1
            continue

        # Find leading table on next page
        leading_table = _find_leading_table(next_page)
        if leading_table is None:
            i += 1
            continue

        # Check if they should be merged
        if _should_merge(trailing_table, leading_table, next_page):
            _do_merge(current_page, trailing_table, next_page, leading_table)
            merged_count += 1
            # Don't advance i — check if next page also continues
        else:
            i += 1

    if merged_count > 0:
        logger.info("Merged %d page-spanning tables", merged_count)

    return pages


def _find_trailing_table(page: VLMPageResult) -> VLMTableData | None:
    """Find the last table on a page (if it's near the bottom)."""
    if not page.tables:
        return None

    # Check if a table region is among the last regions on the page
    table_regions = [r for r in page.regions if r.role == "table"]
    if not table_regions:
        return page.tables[-1]  # Trust the table list

    # Find the table region with highest y-position (bottom of page)
    last_table_region = max(table_regions, key=lambda r: r.bbox.y1)

    # Check it's in the bottom 40% of the page
    if last_table_region.bbox.y1 > page.height * 0.6:
        # Find matching VLMTableData
        for tbl in page.tables:
            if tbl.regionId == last_table_region.regionId:
                return tbl
        return page.tables[-1]

    return None


def _find_leading_table(page: VLMPageResult) -> VLMTableData | None:
    """Find the first table on a page (if it's near the top)."""
    if not page.tables:
        return None

    table_regions = [r for r in page.regions if r.role == "table"]
    if not table_regions:
        return page.tables[0]

    # Find the table region with lowest y-position (top of page)
    first_table_region = min(table_regions, key=lambda r: r.bbox.y0)

    # Check it's in the top 40% of the page
    if first_table_region.bbox.y0 < page.height * 0.4:
        for tbl in page.tables:
            if tbl.regionId == first_table_region.regionId:
                return tbl
        return page.tables[0]

    return None


def _should_merge(
    trailing: VLMTableData,
    leading: VLMTableData,
    next_page: VLMPageResult,
) -> bool:
    """Determine if two tables across pages should be merged."""

    # Column count check (allow ±1 for row numbering)
    trailing_cols = len(trailing.headers) or (len(trailing.rows[0]) if trailing.rows else 0)
    leading_cols = len(leading.headers) or (len(leading.rows[0]) if leading.rows else 0)

    if abs(trailing_cols - leading_cols) > 1:
        return False

    # Check for "contd." pattern in page text or table region
    page_top_text = next_page.rawText[:200].lower() if next_page.rawText else ""
    has_contd = bool(_CONTD_PATTERNS.search(page_top_text))

    # Check header regions for continuation markers
    for region in next_page.regions[:5]:
        if _CONTD_PATTERNS.search(region.text):
            has_contd = True
            break

    if has_contd:
        return True

    # Header similarity check
    if trailing.headers and leading.headers:
        sim = _header_similarity(trailing.headers, leading.headers)
        if sim >= _HEADER_SIMILARITY_THRESHOLD:
            return True

    # Multi-level header similarity
    if trailing.headerLevels and leading.headerLevels:
        flat_t = trailing.flat_headers
        flat_l = leading.flat_headers
        sim = _header_similarity(flat_t, flat_l)
        if sim >= _HEADER_SIMILARITY_THRESHOLD:
            return True

    return False


def _header_similarity(h1: list[str], h2: list[str]) -> float:
    """Compare two header lists for structural similarity."""
    if not h1 or not h2:
        return 0.0

    # Normalize: lowercase, strip whitespace
    norm1 = [h.lower().strip() for h in h1]
    norm2 = [h.lower().strip() for h in h2]

    # Use sequence matching
    return SequenceMatcher(None, norm1, norm2).ratio()


def _do_merge(
    source_page: VLMPageResult,
    trailing_table: VLMTableData,
    next_page: VLMPageResult,
    leading_table: VLMTableData,
) -> None:
    """Merge leading_table rows into trailing_table and remove from next_page."""

    # Append rows from continuation
    rows_to_add = leading_table.rows

    # Skip the first row if it looks like a repeated header
    if rows_to_add and trailing_table.headers:
        first_row_sim = _header_similarity(rows_to_add[0], trailing_table.headers)
        if first_row_sim >= 0.8:
            rows_to_add = rows_to_add[1:]

    trailing_table.rows.extend(rows_to_add)

    # Merge hierarchical info if present
    if leading_table.mergedCells:
        row_offset = len(trailing_table.rows) - len(rows_to_add)
        for r, c, rs, cs in leading_table.mergedCells:
            trailing_table.mergedCells.append((r + row_offset, c, rs, cs))

    # Remove merged table from next page
    if leading_table in next_page.tables:
        next_page.tables.remove(leading_table)

    # Remove corresponding region
    next_page.regions = [
        r for r in next_page.regions
        if not (r.role == "table" and r.regionId == leading_table.regionId)
    ]

    logger.debug(
        "Merged table from page %d into page %d (%d rows added)",
        next_page.pageIndex, source_page.pageIndex, len(rows_to_add),
    )
