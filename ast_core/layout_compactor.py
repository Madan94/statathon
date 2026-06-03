"""Compact coordinate-based layouts to eliminate large vertical white gaps.

MoSPI-style coordinate ASTs place elements at absolute positions that often
leave most of a page empty (e.g. a section heading alone at the bottom, or
content ending mid-page).  This module reflows blocks top-to-bottom within
the printable frame while preserving horizontal position and element order.

Table-only appendix pages are compacted in-page only (stacked from the top).
Cover (page 0) and TOC (page 1) are left unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .geometry_planner import (
    PageFrame,
    _estimate_table_height,
    _estimate_text_height,
    _height_for_element,
)
from .schema import BBox, LayoutBlock, LayoutPage, MultiAST, StyleAST

logger = logging.getLogger(__name__)

_FRAME = PageFrame(margin_top=52.0, margin_bottom=48.0, margin_left=54.0, margin_right=54.0)
_ROW_Y_TOLERANCE = 18.0
_BLOCK_GAP = 8.0

_TEXT_TYPES = frozenset({
    "text", "paragraph", "body", "meta",
    "heading", "heading_1", "heading_2",
    "chapter_heading", "chapter_header", "subtitle", "title", "caption",
})
_HEADING_TYPES = frozenset({
    "heading", "heading_1", "heading_2", "chapter_heading", "chapter_header",
})


@dataclass
class _Row:
    blocks: list[LayoutBlock]
    y_key: float


def compact_coord_layout(ast: MultiAST) -> list[str]:
    """Reflow body pages; return compaction warnings."""
    warnings: list[str] = []
    if len(ast.layoutAST.pages) < 3:
        return warnings

    table_page_indices = [
        i for i, pg in enumerate(ast.layoutAST.pages)
        if _is_table_only_page(pg)
    ]
    first_table = min(table_page_indices) if table_page_indices else len(ast.layoutAST.pages)

    # Body pages: after TOC, before table appendix
    body_start = 2
    body_end = first_table - 1
    if body_end >= body_start:
        warnings.extend(_reflow_body_pages(ast, body_start, body_end))

    for pi in table_page_indices:
        warnings.extend(_compact_table_page(ast.layoutAST.pages[pi], ast))

    _expand_single_figure_pages(ast)
    _sync_geometry_from_blocks(ast)
    return warnings


def _expand_single_figure_pages(ast: MultiAST) -> None:
    """When a page is only one figure, grow it to use the printable frame."""
    for page in ast.layoutAST.pages:
        real = [b for b in page.blocks if b.type != "empty_canvas"]
        if len(real) != 1 or real[0].type != "figure" or not real[0].inline_bbox:
            continue
        block = real[0]
        bb = block.inline_bbox
        cap_reserve = 18.0
        max_h = page.height - _FRAME.margin_bottom - bb.y - cap_reserve
        if max_h > bb.height:
            block.inline_bbox = BBox(
                x=bb.x, y=bb.y, width=bb.width, height=max_h,
            )


def _is_table_only_page(page: LayoutPage) -> bool:
    real = [b for b in page.blocks if b.type != "empty_canvas"]
    if not real:
        return False
    return all(b.type == "table" for b in real)


def _reflow_body_pages(ast: MultiAST, start: int, end: int) -> list[str]:
    warnings: list[str] = []
    pages = ast.layoutAST.pages
    page_h = pages[start].height if pages else 842.0
    max_y = page_h - _FRAME.margin_bottom

    # Collect rows in reading order across body pages
    rows: list[_Row] = []
    for pi in range(start, end + 1):
        pg = pages[pi]
        sorted_blocks = sorted(
            pg.blocks,
            key=lambda b: (
                b.inline_bbox.y if b.inline_bbox else 0,
                b.inline_bbox.x if b.inline_bbox else 0,
            ),
        )
        rows.extend(_group_into_rows(sorted_blocks))

    if not rows:
        return warnings

    # Assign rows to pages with vertical packing
    assignments: list[list[LayoutBlock]] = [[] for _ in range(end - start + 1)]
    page_slot = 0
    cursor_y = _FRAME.margin_top
    content_w = pages[start].width - _FRAME.margin_left - _FRAME.margin_right

    for row in rows:
        row_h = _row_height(ast, row)
        if cursor_y + row_h > max_y and page_slot < len(assignments) - 1:
            page_slot += 1
            cursor_y = _FRAME.margin_top

        if cursor_y + row_h > max_y:
            warnings.append(
                f"compaction overflow on body page slot {page_slot + start}"
            )
            row_h = max(0.0, max_y - cursor_y)

        _place_row(ast, row, cursor_y, content_w, row_h)
        assignments[page_slot].extend(row.blocks)
        cursor_y += row_h + _BLOCK_GAP

    for i, pi in enumerate(range(start, end + 1)):
        pages[pi].blocks = assignments[i]
        if not assignments[i]:
            logger.debug("body page %s empty after compaction", pages[pi].pageId)

    logger.info(
        "Compacted body pages %d–%d (%d blocks into %d pages)",
        start, end, sum(len(r.blocks) for r in rows), end - start + 1,
    )
    return warnings


def _compact_table_page(page: LayoutPage, ast: MultiAST) -> list[str]:
    warnings: list[str] = []
    blocks = sorted(
        [b for b in page.blocks if b.type == "table" and b.inline_bbox],
        key=lambda b: b.inline_bbox.y,  # type: ignore[union-attr]
    )
    if not blocks:
        return warnings

    cursor_y = _FRAME.margin_top
    max_y = page.height - _FRAME.margin_bottom
    content_w = page.width - _FRAME.margin_left - _FRAME.margin_right

    for block in blocks:
        ref = block.elementRefs[0] if block.elementRefs else ""
        h = _block_height(ast, block, content_w)
        if cursor_y + h > max_y:
            warnings.append(f"table compaction overflow {block.blockId}")
            h = max(0.0, max_y - cursor_y)
        block.inline_bbox = BBox(
            x=_FRAME.margin_left,
            y=cursor_y,
            width=content_w,
            height=h,
        )
        cursor_y += h + _BLOCK_GAP

    page.blocks = blocks
    return warnings


def _group_into_rows(blocks: list[LayoutBlock]) -> list[_Row]:
    if not blocks:
        return []
    rows: list[_Row] = []
    current: list[LayoutBlock] = [blocks[0]]
    y0 = blocks[0].inline_bbox.y if blocks[0].inline_bbox else 0.0

    for block in blocks[1:]:
        y = block.inline_bbox.y if block.inline_bbox else 0.0
        if abs(y - y0) <= _ROW_Y_TOLERANCE:
            current.append(block)
        else:
            rows.append(_Row(blocks=current, y_key=y0))
            current = [block]
            y0 = y
    rows.append(_Row(blocks=current, y_key=y0))
    return rows


def _row_height(ast: MultiAST, row: _Row) -> float:
    content_w = 487.0
    if len(row.blocks) == 1:
        return _block_height(ast, row.blocks[0], content_w)
    return max(_block_height(ast, b, content_w) for b in row.blocks)


def _place_row(
    ast: MultiAST,
    row: _Row,
    cursor_y: float,
    content_w: float,
    row_h: float,
) -> None:
    if len(row.blocks) == 1:
        block = row.blocks[0]
        old = block.inline_bbox
        w = old.width if old else content_w
        x = old.x if old else _FRAME.margin_left
        h = _block_height(ast, block, w)
        block.inline_bbox = BBox(x=x, y=cursor_y, width=w, height=max(h, row_h))
        return

    for block in row.blocks:
        old = block.inline_bbox
        if not old:
            continue
        block.inline_bbox = BBox(
            x=old.x,
            y=cursor_y,
            width=old.width,
            height=row_h,
        )


def _block_height(ast: MultiAST, block: LayoutBlock, content_w: float) -> float:
    old = block.inline_bbox
    declared = old.height if old else 0.0
    eid = block.elementRefs[0] if block.elementRefs else ""

    if block.type == "figure":
        return max(declared, 120.0)
    if block.type == "chart":
        return max(declared, 160.0)
    if block.type == "table":
        return _height_for_element(ast, eid, "table", 9.0, content_w)
    if block.type == "list":
        return max(declared, _height_for_element(ast, eid, "list", 11.0, content_w))

    font_size = _font_size_for_block(ast.styleAST, block.type)
    if eid and block.type in _TEXT_TYPES:
        est = _height_for_element(ast, eid, block.type, font_size, content_w)
        # Headings: tight band; paragraphs: use content-driven height
        if block.type in _HEADING_TYPES:
            return max(declared, est, font_size * 1.6)
        return max(declared * 0.85, est)

    return max(declared, 14.0)


def _font_size_for_block(style_ast: StyleAST, block_type: str) -> float:
    sid = {
        "title": "s_h1",
        "chapter_header": "s_h1",
        "chapter_heading": "s_h1",
        "heading_1": "s_h1",
        "heading_2": "s_h2",
        "heading": "s_h2",
        "subtitle": "s_h2",
    }.get(block_type, "s_body")
    st = style_ast.by_id(sid) or style_ast.by_id("s_body")
    return st.fontSize if st else 11.0


def _sync_geometry_from_blocks(ast: MultiAST) -> None:
    """Keep GeometryAST nodes aligned with compacted inline bboxes."""
    ref_to_node: dict[str, object] = {}
    for node in ast.geometryAST.nodes:
        if node.elementRef:
            ref_to_node[node.elementRef] = node

    for page in ast.layoutAST.pages:
        for block in page.blocks:
            if not block.inline_bbox:
                continue
            for ref in block.elementRefs:
                node = ref_to_node.get(ref)
                if node is not None:
                    node.bbox = BBox(
                        x=block.inline_bbox.x,
                        y=block.inline_bbox.y,
                        width=block.inline_bbox.width,
                        height=block.inline_bbox.height,
                    )
                    node.pageId = page.pageId
