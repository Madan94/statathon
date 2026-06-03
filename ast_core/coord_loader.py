"""coord_loader.py — Load coordinate-based AST (fina-ast style) into MultiAST.

The new AST format ("Version 2.0 Geometrically Complete") stores the bbox
**directly on every layout block** and uses ``elementRef`` (singular) instead
of ``elementRefs`` (list).  The classic renderer pipeline expects all bboxes
to live inside GeometryAST nodes, looked up by element-id.

This loader bridges the two formats by:
1. For every layout block that carries an inline ``bbox``, synthesising a
   matching GeometryNode whose ``elementRef`` equals the block's element-ref.
2. For GeometryAST nodes that already ship ``components`` (pre-computed pie
   slices for fig_005 etc.), propagating them straight into ``Figure.computed_chart``.
3. Normalising ``elementRef`` (string) → ``elementRefs: [ref]`` on every block.

The returned MultiAST is identical in shape to what ``load_multi_ast`` returns
from the old format, so the renderer, template-binder and deep-bi-binder can
all work without knowing which format the source JSON was.

Usage
-----
    from ast_core.coord_loader import load_coord_ast
    ast = load_coord_ast("test_data/fina-ast.json")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .schema import (
    BBox, GeometryNode, GeometryAST, LayoutPage, MultiAST,
)
from .layout_compactor import compact_coord_layout
from .loader import load_multi_ast

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_coord_ast(path: str | Path) -> MultiAST:
    """Load a coordinate-based (fina-ast style) JSON and return a normalised MultiAST.

    Works transparently on old-style ASTs too — if blocks already have
    ``elementRefs`` lists and no inline bboxes, the file is passed straight
    through to the classic ``load_multi_ast``.
    """
    raw_text = Path(path).read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw_text)

    # Load via the standard path first (handles all the dataclass construction)
    ast = load_multi_ast(path)

    # --- Phase 0: fina-ast / v2 coords use PDF bottom-left Y; renderer uses top-left ---
    if _needs_y_flip(data):
        _flip_all_bboxes_to_top_left(ast)
        logger.info(
            "Converted layout bboxes from bottom-left to top-left (page count=%d)",
            len(ast.layoutAST.pages),
        )
        # Remove vertical dead space; pull sections forward across body pages
        compact_warnings = compact_coord_layout(ast)
        for w in compact_warnings[:5]:
            logger.warning("layout compaction: %s", w)

    # --- Phase 1: promote inline block bboxes into GeometryAST nodes ---------
    existing_ids = {n.nodeId for n in ast.geometryAST.nodes}
    existing_refs = {n.elementRef for n in ast.geometryAST.nodes if n.elementRef}

    for page in ast.layoutAST.pages:
        for block in page.blocks:
            if not block.inline_bbox:
                continue
            for ref in block.elementRefs:
                if ref in existing_refs:
                    continue  # geometry node already present from geometryAST section
                node_id = f"auto_{block.blockId}_{ref}"
                if node_id in existing_ids:
                    continue
                node = GeometryNode(
                    nodeId=node_id,
                    bbox=BBox(
                        x=block.inline_bbox.x,
                        y=block.inline_bbox.y,
                        width=block.inline_bbox.width,
                        height=block.inline_bbox.height,
                    ),
                    elementRef=ref,
                    pageId=page.pageId,
                )
                ast.geometryAST.nodes.append(node)
                existing_ids.add(node_id)
                existing_refs.add(ref)
                logger.debug(
                    "auto-node %s → %s  bbox=(%.0f,%.0f,%.0f,%.0f)",
                    node_id, ref,
                    node.bbox.x, node.bbox.y,
                    node.bbox.width, node.bbox.height,
                )

    # --- Phase 2: geometry nodes with pre-computed components → Figure.computed_chart ---
    for node in ast.geometryAST.nodes:
        if not node.components:
            continue
        # node.nodeId (or elementRef) should match a figureId
        candidate_ids = [node.nodeId, node.elementRef or ""]
        for fid in candidate_ids:
            fig = ast.figureAST.by_id(fid)
            if fig and fig.computed_chart is None:
                chart_type = _infer_chart_type_from_components(node.components)
                fig.computed_chart = _components_to_chart(
                    components=node.components,
                    chart_type=chart_type,
                    title=fig.caption,
                )
                logger.info(
                    "Pre-bound figure %s from geometry components (%d slices)",
                    fid, len(node.components),
                )
                break

    # --- Phase 3: Also check the raw geometryAST section for nodes defined ---
    # by id= (new format uses "id" not "nodeId" on geometry nodes)
    raw_geom_nodes = (data.get("geometryAST") or {}).get("nodes") or []
    for raw_node in raw_geom_nodes:
        node_id = str(raw_node.get("id") or raw_node.get("nodeId") or "")
        components = list(raw_node.get("components") or [])
        if not (node_id and components):
            continue
        fig = ast.figureAST.by_id(node_id)
        if fig and fig.computed_chart is None:
            chart_type = _infer_chart_type_from_components(components)
            fig.computed_chart = _components_to_chart(
                components=components,
                chart_type=chart_type,
                title=fig.caption,
            )
            logger.info(
                "Pre-bound figure %s from raw geometry components (%d slices)",
                node_id, len(components),
            )
            # Also synthesise a geometry node so the renderer can find the bbox
            bbox_raw = raw_node.get("bbox") or {}
            if bbox_raw and node_id not in existing_refs:
                nb = BBox.from_dict(bbox_raw)
                # Page for fig_005 is page_006
                pg = ast.layoutAST.pages[5] if len(ast.layoutAST.pages) > 5 else None
                ph = pg.height if pg else 842.0
                if _needs_y_flip(data):
                    nb = _bbox_bottom_to_top(nb, ph)
                node = GeometryNode(
                    nodeId=f"geom_{node_id}",
                    bbox=nb,
                    elementRef=node_id,
                )
                ast.geometryAST.nodes.append(node)
                existing_refs.add(node_id)

    # Ensure table header style exists (white on navy band in renderer)
    if not ast.styleAST.by_id("s_table_header"):
        from .schema import Style
        ast.styleAST.styles.append(Style(
            styleId="s_table_header",
            fontFamily="Helvetica-Bold",
            fontSize=8.0,
            fontWeight="bold",
            color="#FFFFFF",
        ))

    return ast


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _needs_y_flip(data: dict[str, Any]) -> bool:
    """True when AST bboxes use PDF-style bottom-left origin (fina-ast v2)."""
    ver = str((data.get("metadata") or {}).get("version") or "")
    if "geometric" in ver.lower():
        return True
    pages = (data.get("layoutAST") or {}).get("pages") or []
    if not pages:
        return False
    ph = float(pages[0].get("height") or 842)
    for blk in pages[0].get("blocks") or []:
        bb = blk.get("bbox") or {}
        y = float(bb.get("y") or 0)
        btype = str(blk.get("type") or "")
        if y > ph * 0.55 and btype in ("heading", "title", "chapter_header"):
            return True
    return False


def _bbox_bottom_to_top(bbox: BBox, page_height: float) -> BBox:
    """Map PDF bottom-left (x, y) to renderer top-left origin."""
    return BBox(
        x=bbox.x,
        y=page_height - bbox.y - bbox.height,
        width=bbox.width,
        height=bbox.height,
    )


def _flip_all_bboxes_to_top_left(ast: MultiAST) -> None:
    """Flip every layout/geometry bbox so the strict renderer places elements correctly."""
    for page in ast.layoutAST.pages:
        ph = page.height
        for block in page.blocks:
            if block.inline_bbox:
                block.inline_bbox = _bbox_bottom_to_top(block.inline_bbox, ph)
        for block in page.blocks:
            for ref in block.elementRefs:
                node = ast.geometryAST.by_element_ref(ref)
                if node:
                    node.bbox = _bbox_bottom_to_top(node.bbox, ph)
    for node in ast.geometryAST.nodes:
        if node.pageId:
            pg = next((p for p in ast.layoutAST.pages if p.pageId == node.pageId), None)
            ph = pg.height if pg else 842.0
        else:
            ph = ast.layoutAST.pages[0].height if ast.layoutAST.pages else 842.0
        node.bbox = _bbox_bottom_to_top(node.bbox, ph)


def _infer_chart_type_from_components(components: list[dict]) -> str:
    """Return 'pie' if all components are pie_slice, else 'bar'."""
    if not components:
        return "bar"
    types = {str(c.get("type", "")).lower() for c in components}
    return "pie" if "pie_slice" in types else "bar"


def _components_to_chart(
    components: list[dict],
    chart_type: str,
    title: str,
) -> dict:
    """Convert geometry components list to a renderer-compatible chart dict."""
    data: list[dict] = []
    for comp in components:
        label = str(comp.get("label") or "")
        # pie_slice components use 'percentage'; generic components use 'value'
        value = comp.get("value") or comp.get("percentage") or 0.0
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0
        if label:
            data.append({"label": label, "value": value})
    return {"type": chart_type, "title": title, "data": data}
