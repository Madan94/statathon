"""Deterministic geometry planner.

The Enterprise template provides explicit GeometryAST nodes for two elements
(node_p001 and node_table1). Every *other* element needs a bbox derived from
the LayoutAST + StyleAST in a deterministic way — same input always produces
the same bbox.

The planner walks each LayoutPage in order, allocates blocks top-to-bottom
inside a configurable content frame (page margins), and writes one
GeometryNode per element_ref. If a node was already declared explicitly in
GeometryAST it is preserved verbatim — the user's coordinates always win.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schema import (
    BBox, GeometryNode, LayoutBlock, LayoutPage, MultiAST, Style,
)


@dataclass
class PageFrame:
    """Where content can live on a page (everything else is margin).

    Top margin reserves space for the Ministry header band; bottom margin
    reserves space for the page-number footer.
    """
    margin_top: float = 60.0
    margin_bottom: float = 50.0
    margin_left: float = 50.0
    margin_right: float = 50.0


@dataclass
class GeometryPlan:
    """Result of plan_geometry — explicit + computed geometry, no overlap."""
    nodes_by_element: dict[str, GeometryNode]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Height estimators per block kind
# ---------------------------------------------------------------------------


def _estimate_text_height(text: str, font_size: float, frame_width: float,
                          leading_factor: float = 1.45) -> float:
    """Best-effort wrapping height estimate.

    Uses ~0.48 * font_size per glyph (Helvetica average) plus a 1.45 leading
    factor so descenders + paragraph spacing never clip. Adds an 8pt floor
    so blocks don't visually kiss each other.
    """
    if not text:
        return font_size * leading_factor + 4
    char_w = max(0.48 * font_size, 4.0)
    chars_per_line = max(1, int(frame_width / char_w))
    paragraphs = str(text).split("\n")
    n_lines = 0
    for para in paragraphs:
        n_lines += max(1, (len(para) + chars_per_line - 1) // chars_per_line)
    return n_lines * font_size * leading_factor + 8


def _estimate_table_height(rows_count: int, has_title: bool = True,
                            font_size: float = 9) -> float:
    row_h = font_size * 1.8 + 4
    header_h = font_size * 1.8 + 6
    title_h = font_size * 2.0 + 8 if has_title else 0
    return title_h + header_h + (rows_count + 1) * row_h


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


_BLOCK_HEIGHT_OVERRIDES: dict[str, float] = {
    "header": 30.0,
    "footer": 24.0,
    "heading": 28.0,
    "chapter_heading": 40.0,
    "title": 60.0,
    "subtitle": 30.0,
    "empty_canvas": 0.0,
}


_STYLE_FOR_TYPE: dict[str, str] = {
    "header": "s_caption",
    "title": "s_h1",
    "subtitle": "s_h2",
    "chapter_heading": "s_h1",
    "heading": "s_h2",
    "text": "s_body",
    "list": "s_body",
    "caption": "s_caption",
    "footer": "s_caption",
    "table": "s_body",
    "figure": "s_caption",
    "chart": "s_caption",
}


def plan_geometry(ast: MultiAST, *, frame: PageFrame | None = None
                   ) -> GeometryPlan:
    """Compute a GeometryNode per element_ref across every layout page.

    Preserves any explicit GeometryAST entries: if a node already exists for
    a given elementRef (or its nodeId matches "node_<element_ref>") the
    explicit bbox / style is kept.
    """
    frame = frame or PageFrame()
    plan: dict[str, GeometryNode] = {}
    warnings: list[str] = []

    # 1) Index explicit geometry nodes for direct preservation
    explicit_by_ref: dict[str, GeometryNode] = {}
    for n in ast.geometryAST.nodes:
        if n.elementRef:
            explicit_by_ref[n.elementRef] = n
        # Convention: node_<id> => element id
        if n.nodeId.startswith("node_"):
            explicit_by_ref.setdefault(n.nodeId[5:], n)

    styles_by_id = {s.styleId: s for s in ast.styleAST.styles}

    # 2) Walk pages
    for page in ast.layoutAST.pages:
        cursor_y = frame.margin_top
        page_h = page.height
        max_y = page_h - frame.margin_bottom
        content_w = page.width - frame.margin_left - frame.margin_right
        x0 = frame.margin_left

        for block in page.blocks:
            # Each block may reference 0..N content elements; allocate
            # geometry for each element in turn.
            element_ids = list(block.elementRefs)
            if not element_ids:
                # An empty_canvas (table-only page) still consumes the frame.
                if block.type == "empty_canvas":
                    cursor_y = max_y
                continue

            for eid in element_ids:
                # If user already declared geometry for this element, use it as-is
                if eid in explicit_by_ref:
                    node = explicit_by_ref[eid]
                    node.pageId = page.pageId
                    plan[eid] = node
                    continue

                # Otherwise derive height from element type + style
                style_id = _STYLE_FOR_TYPE.get(block.type, "s_body")
                style = styles_by_id.get(style_id)
                font_size = style.fontSize if style else 10.0

                # Text-bearing element: look up content
                text_height = _height_for_element(ast, eid, block.type,
                                                   font_size, content_w)
                # Allow block type overrides for visually fixed blocks
                if block.type in _BLOCK_HEIGHT_OVERRIDES:
                    text_height = max(text_height,
                                       _BLOCK_HEIGHT_OVERRIDES[block.type])

                if cursor_y + text_height > max_y:
                    warnings.append(
                        f"overflow: page={page.pageId} block={block.blockId} "
                        f"element={eid} need={text_height:.0f}px "
                        f"available={max_y - cursor_y:.0f}px"
                    )
                    # Hard clamp to remaining space; overflow validator catches it.
                    text_height = max(0.0, max_y - cursor_y)

                node = GeometryNode(
                    nodeId=f"node_{eid}",
                    bbox=BBox(x=x0, y=cursor_y,
                               width=content_w, height=text_height),
                    styleId=style_id, pageId=page.pageId, elementRef=eid,
                )
                plan[eid] = node
                cursor_y += text_height + _spacing_for_type(block.type)

    return GeometryPlan(nodes_by_element=plan, warnings=warnings)


def _height_for_element(ast: MultiAST, element_id: str, block_type: str,
                         font_size: float, frame_width: float) -> float:
    if block_type in ("table",):
        t = ast.tableAST.by_id(element_id) if hasattr(ast.tableAST, "by_id") else None
        if t is None:
            # element_id may be a tableId — search directly
            for tb in ast.tableAST.tables:
                if tb.tableId == element_id:
                    t = tb
                    break
        if t is not None:
            return _estimate_table_height(len(t.rows), has_title=bool(t.title),
                                            font_size=font_size)
        return 200.0
    if block_type in ("figure", "chart"):
        return 220.0
    # Default: text-bearing paragraph/list
    p = ast.contentAST.paragraph_by_id(element_id)
    if p:
        return _estimate_text_height(p.content, font_size, frame_width)
    # List
    for l in ast.contentAST.lists:
        if l.id == element_id:
            total = sum(_estimate_text_height(item, font_size, frame_width)
                         for item in l.items)
            return total + 4.0
    return font_size * 1.5


def _spacing_for_type(block_type: str) -> float:
    return {
        "title": 14, "subtitle": 10, "chapter_heading": 18,
        "heading": 12, "text": 10, "list": 10,
        "table": 18, "figure": 16, "chart": 16,
        "header": 6, "footer": 6, "empty_canvas": 0,
    }.get(block_type, 10)


def write_geometry_to_ast(ast: MultiAST, plan: GeometryPlan) -> None:
    """Replace AST.geometryAST.nodes with the planned set, preserving explicit ones."""
    ast.geometryAST.nodes = list(plan.nodes_by_element.values())


def iterate_block_elements(page: LayoutPage) -> Iterable[tuple[LayoutBlock, str]]:
    for b in page.blocks:
        for e in b.elementRefs:
            yield b, e
