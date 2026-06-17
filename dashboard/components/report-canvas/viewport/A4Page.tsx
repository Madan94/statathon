'use client';
import { useRef, useState, useCallback, useEffect } from 'react';
import type { PageBlock } from '../engine/useCanvasState';
import type { NumberedHeading, TableSplitPart } from '../engine/paginationEngine';
import { BlockRenderer } from '../blocks/BlockRenderer';
import {
  MM_TO_PX, SNAP, PAD, MIN_W, MIN_H, DRAG_THRESHOLD, Z,
  intrinsicWidth, resizableEdges, type HandleDir,
} from '../engine/canvasTokens';
import { ResizeHandles } from '../blocks/chrome/ResizeHandles';
import { BlockActionBar } from '../blocks/chrome/BlockActionBar';
import { DragHandle } from '../blocks/chrome/DragHandle';
import { InsertionCaret } from '../blocks/chrome/InsertionCaret';
import { useFlip } from '../engine/interaction/useFlip';

/* ═══════════════════════════════════════════════════════════════════
   A4Page — one fixed-size sheet with Canva-style free positioning.

   • Blocks without coordinates flow in the normal vertical stack.
   • Dragging a block "lifts" it from the flow into absolute coordinates
     (unscaled px relative to the page content area).
   • While dragging: alignment guides (page centre/edges + sibling block
     edges & centres) snap within a small threshold, and a minimal
     coordinate badge (mm) follows the block — like Canva.
   ═══════════════════════════════════════════════════════════════════ */

export type PageSize = 'a4' | 'a4-extended' | 'mospi' | 'letter';

const PAGE_DIMENSIONS: Record<PageSize, { w: number; h: number; label: string }> = {
  'a4':          { w: 210, h: 297, label: 'A4 (210×297mm)' },
  'a4-extended': { w: 210, h: 350, label: 'A4 Extended' },
  'mospi':       { w: 215, h: 305, label: 'MoSPI Standard' },
  'letter':      { w: 216, h: 279, label: 'US Letter' },
};

export { PAGE_DIMENSIONS };

interface A4PageProps {
  blocks: PageBlock[];
  pageNumber: number;
  totalPages: number;
  selectedBlockId: string | null;
  onSelectBlock: (id: string | null) => void;
  onGenerate?: (index: number) => void;
  onMoveBlock?: (id: string, x: number, y: number, w?: number) => void;
  /** Reorder a flowing block to sit before ``beforeId`` (null = end). */
  onReorderBlock?: (id: string, beforeId: string | null) => void;
  /** Toggle a block between flowing and floating (opt-in overlay). */
  onSetFloating?: (id: string, floating: boolean, x?: number, y?: number) => void;
  onUpdateBlock?: (id: string, updates: Partial<PageBlock>) => void;
  onDeleteBlock?: (id: string) => void;
  onDuplicateBlock?: (id: string) => void;
  onResizeBlock?: (id: string, patch: { w?: number; h?: number; x?: number; y?: number }) => void;
  /** On-canvas "✨ ask" — opens the co-pilot scoped to a block (S4). */
  onAskBlock?: (block: PageBlock) => void;
  /** Add a footnote to a block; returns the marker number (U2). */
  onAddFootnote?: (blockId: string, text: string) => number;
  /** Review (U4): open a comment thread on a block. */
  onCommentBlock?: (block: PageBlock) => void;
  /** Review (U4): toggle the "needs attention" flag on a block. */
  onFlagBlock?: (blockId: string) => void;
  /** Open-comment count for a block (badge). */
  commentCount?: (blockId: string) => number;
  /** Whether a block is flagged for attention. */
  isFlagged?: (blockId: string) => boolean;
  /** Numeral system for figures (T6): 'intl' | 'devanagari'. */
  numerals?: 'intl' | 'devanagari';
  pageSize?: PageSize;
  zoom?: number;
  /** §-numbering for heading-like blocks, keyed by block id (whole document). */
  numbering?: Record<string, NumberedHeading>;
  /** Caption text ("Table 1.1") keyed by table block id (whole document). */
  tableCaptions?: Record<string, string>;
  /** Split parts keyed by original table id; the renderer windows the rows. */
  tableSplits?: Record<string, TableSplitPart[]>;
  /** Running-header chapter label for this page. */
  chapterLabel?: string;
  reportTitle?: string;
  /** Running-footer issuing-organisation line (dynamic, not hardcoded). */
  footerOrg?: string;
  /** Estimate-then-measure: report each flow block's real rendered height (px)
   *  so the packer can reflow on the true boundary instead of clipping. */
  onReportHeights?: (heights: Record<string, number>) => void;
}

interface DragRef {
  id: string;
  pointerId: number;
  el: HTMLElement;          // the drag-handle element (holds pointer capture)
  floating: boolean;        // float-move (absolute) vs flow-reorder
  pointerStartX: number;
  pointerStartY: number;
  blockStartX: number;      // floating only
  blockStartY: number;      // floating only
  w: number;
  h: number;
  moved: boolean;
  xTargets: number[];       // floating snap
  yTargets: number[];       // floating snap
  // Reorder: flowing siblings on this page in DOM order (content-local px).
  siblings: { id: string; top: number; mid: number; bottom: number }[];
  dropBeforeId: string | null;  // current reorder target (null = end of flow)
}

export function A4Page({
  blocks, pageNumber, totalPages, selectedBlockId, onSelectBlock,
  onGenerate, onMoveBlock, onReorderBlock, onSetFloating, onUpdateBlock, onDeleteBlock, onDuplicateBlock, onResizeBlock, pageSize = 'a4', zoom = 100,
  numbering, tableCaptions, tableSplits, chapterLabel, reportTitle = 'MoSPI Statistical Report', onAskBlock, onAddFootnote,
  onCommentBlock, onFlagBlock, commentCount, isFlagged, numerals, footerOrg = 'MoSPI · Government of India',
  onReportHeights,
}: A4PageProps) {
  const dim = PAGE_DIMENSIONS[pageSize];
  const scale = zoom / 100;
  const pageW = dim.w * MM_TO_PX;
  const pageH = dim.h * MM_TO_PX;
  const contentW = (dim.w - PAD.left - PAD.right) * MM_TO_PX;
  const contentH = (dim.h - PAD.top - PAD.bottom) * MM_TO_PX;

  const contentRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragRef | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);       // block being dragged
  const [caretY, setCaretY] = useState<number | null>(null);        // reorder insertion caret
  const [live, setLive] = useState<{ id: string; x: number; y: number } | null>(null);
  const [guideX, setGuideX] = useState<number | null>(null);
  const [guideY, setGuideY] = useState<number | null>(null);

  // ── Resize ──────────────────────────────────────────────────────────────
  const resizeRef = useRef<{
    id: string; dir: HandleDir; px: number; py: number;
    x0: number; y0: number; w0: number; h0: number; positioned: boolean;
    xTargets: number[]; yTargets: number[];
  } | null>(null);
  const [resizeLive, setResizeLive] = useState<{ id: string; w: number; h: number; x: number; y: number; vert: boolean } | null>(null);

  const mm = (px: number) => Math.round(px / MM_TO_PX);

  /** The effective width of a block (explicit ``w`` or its intrinsic default). */
  const widthOf = (b: PageBlock) => b.w ?? intrinsicWidth(b.kind, contentW);

  // Smooth FLIP glide when the flow order/heights change (disabled mid-drag so
  // the live preview isn't fought by an animation).
  useFlip(contentRef, dragId === null);

  // ── Drag from the gutter grip: reorder (flow) or free-move (floating) ──────
  // The grip is the ONE drag entry point, leaving the block body free for
  // click-to-type. Pointer capture lives on the grip element.
  const onDragHandleDown = useCallback((e: React.PointerEvent, block: PageBlock) => {
    if (block.status !== 'done') return;
    e.stopPropagation();
    e.preventDefault();
    onSelectBlock(block.id);
    const content = contentRef.current;
    if (!content) return;
    const cRect = content.getBoundingClientRect();
    const grip = e.currentTarget as HTMLElement;
    const sel = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(block.id) : block.id;
    const bNode = content.querySelector<HTMLElement>(`[data-block-id="${sel}"]`);
    const bRect = (bNode ?? grip).getBoundingClientRect();
    const startX = (bRect.left - cRect.left) / scale;
    const startY = (bRect.top - cRect.top) / scale;
    const w = bRect.width / scale;
    const h = bRect.height / scale;

    const xTargets: number[] = [0, contentW, contentW / 2];
    const yTargets: number[] = [0, contentH, contentH / 2];
    const siblings: DragRef['siblings'] = [];
    content.querySelectorAll<HTMLElement>('[data-block-id]').forEach(node => {
      if (node.dataset.blockId === block.id) return;
      const r = node.getBoundingClientRect();
      const x0 = (r.left - cRect.left) / scale;
      const y0 = (r.top - cRect.top) / scale;
      const wEl = r.width / scale;
      const hEl = r.height / scale;
      xTargets.push(x0, x0 + wEl / 2, x0 + wEl);
      yTargets.push(y0, y0 + hEl / 2, y0 + hEl);
      // Only flowing siblings (not absolute) participate in reorder targeting.
      if (node.style.position !== 'absolute' && node.dataset.blockId) {
        siblings.push({ id: node.dataset.blockId, top: y0, mid: y0 + hEl / 2, bottom: y0 + hEl });
      }
    });
    siblings.sort((a, b) => a.top - b.top);

    dragRef.current = {
      id: block.id, pointerId: e.pointerId, el: grip, floating: !!block.floating,
      pointerStartX: e.clientX, pointerStartY: e.clientY,
      blockStartX: startX, blockStartY: startY, w, h, moved: false,
      xTargets, yTargets, siblings, dropBeforeId: null,
    };
    try { grip.setPointerCapture(e.pointerId); } catch { /* noop */ }
    setDragId(block.id);
  }, [onSelectBlock, scale, contentW, contentH]);

  // ── Drag move: snap+guides when floating, insertion caret when reordering ──
  const onDragHandleMove = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = (e.clientX - d.pointerStartX) / scale;
    const dy = (e.clientY - d.pointerStartY) / scale;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    d.moved = true;

    if (d.floating) {
      // Free move with alignment snap (Canva overlay).
      let nx = d.blockStartX + dx;
      let ny = d.blockStartY + dy;
      let gx: number | null = null, bestX = SNAP + 1;
      for (const edge of [nx, nx + d.w / 2, nx + d.w]) {
        for (const t of d.xTargets) { const dist = Math.abs(edge - t); if (dist <= SNAP && dist < bestX) { bestX = dist; nx += t - edge; gx = t; } }
      }
      let gy: number | null = null, bestY = SNAP + 1;
      for (const edge of [ny, ny + d.h / 2, ny + d.h]) {
        for (const t of d.yTargets) { const dist = Math.abs(edge - t); if (dist <= SNAP && dist < bestY) { bestY = dist; ny += t - edge; gy = t; } }
      }
      nx = Math.max(0, Math.min(nx, Math.max(0, contentW - d.w)));
      ny = Math.max(0, Math.min(ny, Math.max(0, contentH - d.h)));
      setLive({ id: d.id, x: nx, y: ny });
      setGuideX(gx);
      setGuideY(gy);
    } else {
      // Reorder: drop BEFORE the first flowing sibling whose midpoint is below
      // the pointer, else at the end of the flow.
      const content = contentRef.current;
      if (!content) return;
      const pointerY = (e.clientY - content.getBoundingClientRect().top) / scale;
      let beforeId: string | null = null;
      let caret = 0;
      let placed = false;
      for (const s of d.siblings) {
        if (pointerY < s.mid) { beforeId = s.id; caret = s.top - 6; placed = true; break; }
      }
      if (!placed) { const last = d.siblings[d.siblings.length - 1]; caret = last ? last.bottom + 6 : 0; beforeId = null; }
      d.dropBeforeId = beforeId;
      setCaretY(Math.max(0, caret));
    }
  }, [scale, contentW, contentH]);

  // ── Drag up: commit the reorder or the free position ───────────────────────
  const onDragHandleUp = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    dragRef.current = null;
    setDragId(null);
    setCaretY(null);
    setGuideX(null);
    setGuideY(null);
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch { /* noop */ }
    if (d && d.moved) {
      if (d.floating && live && onMoveBlock) onMoveBlock(d.id, live.x, live.y, d.w);
      else if (!d.floating && onReorderBlock) onReorderBlock(d.id, d.dropBeforeId);
    }
    setLive(null);
  }, [live, onMoveBlock, onReorderBlock]);

  // ── Resize handle drag ───────────────────────────────────────────────────
  const onResizeDown = useCallback((e: React.PointerEvent, block: PageBlock, dir: HandleDir) => {
    e.stopPropagation();
    e.preventDefault();
    const content = contentRef.current;
    if (!content) return;
    const cRect = content.getBoundingClientRect();
    const el = (e.currentTarget as HTMLElement).closest('[data-block-id]') as HTMLElement | null;
    const bRect = (el ?? (e.currentTarget as HTMLElement)).getBoundingClientRect();
    const positioned = block.x !== undefined && block.y !== undefined;

    // Gather alignment targets (page frame + every other block's edges/centres)
    // so a resizing edge snaps to them — lets two blocks match width exactly.
    const xTargets: number[] = [0, contentW, contentW / 2];
    const yTargets: number[] = [0, contentH, contentH / 2];
    content.querySelectorAll<HTMLElement>('[data-block-id]').forEach(node => {
      if (node.dataset.blockId === block.id) return;
      const rr = node.getBoundingClientRect();
      const x0 = (rr.left - cRect.left) / scale;
      const y0 = (rr.top - cRect.top) / scale;
      const wEl = rr.width / scale;
      const hEl = rr.height / scale;
      xTargets.push(x0, x0 + wEl / 2, x0 + wEl);
      yTargets.push(y0, y0 + hEl / 2, y0 + hEl);
    });

    resizeRef.current = {
      id: block.id, dir, px: e.clientX, py: e.clientY,
      x0: positioned ? block.x! : (bRect.left - cRect.left) / scale,
      y0: positioned ? block.y! : (bRect.top - cRect.top) / scale,
      w0: bRect.width / scale, h0: bRect.height / scale, positioned, xTargets, yTargets,
    };
    setResizeLive({ id: block.id, w: bRect.width / scale, h: bRect.height / scale,
      x: positioned ? block.x! : (bRect.left - cRect.left) / scale,
      y: positioned ? block.y! : (bRect.top - cRect.top) / scale,
      vert: dir.includes('n') || dir.includes('s') });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }, [scale, contentW, contentH]);

  const onResizeMove = useCallback((e: React.PointerEvent) => {
    const r = resizeRef.current;
    if (!r) return;
    const dx = (e.clientX - r.px) / scale;
    const dy = (e.clientY - r.py) / scale;
    let { x0: x, y0: y, w0: w, h0: h } = r;

    if (r.dir.includes('e')) w = r.w0 + dx;
    if (r.dir.includes('s')) h = r.h0 + dy;
    if (r.dir.includes('w')) { w = r.w0 - dx; x = r.x0 + dx; }
    if (r.dir.includes('n')) { h = r.h0 - dy; y = r.y0 + dy; }

    // Snap the moving edge(s) to sibling edges / page centre (Canva-style).
    let gx: number | null = null;
    let gy: number | null = null;
    if (r.dir.includes('e')) {
      const right = x + w;
      for (const t of r.xTargets) { if (Math.abs(right - t) <= SNAP) { w = t - x; gx = t; break; } }
    }
    if (r.dir.includes('w')) {
      for (const t of r.xTargets) { if (Math.abs(x - t) <= SNAP) { w += x - t; x = t; gx = t; break; } }
    }
    if (r.dir.includes('s')) {
      const bottom = y + h;
      for (const t of r.yTargets) { if (Math.abs(bottom - t) <= SNAP) { h = t - y; gy = t; break; } }
    }
    if (r.dir.includes('n')) {
      for (const t of r.yTargets) { if (Math.abs(y - t) <= SNAP) { h += y - t; y = t; gy = t; break; } }
    }

    // Clamp to minimums (and keep the anchored edge fixed when pulling from n/w).
    if (w < MIN_W) { if (r.dir.includes('w')) x -= (MIN_W - w); w = MIN_W; }
    if (h < MIN_H) { if (r.dir.includes('n')) y -= (MIN_H - h); h = MIN_H; }
    // Keep inside the content frame.
    w = Math.min(w, contentW - (r.positioned ? x : 0));
    if (r.positioned) { x = Math.max(0, x); y = Math.max(0, y); }

    setResizeLive({ id: r.id, w, h, x, y, vert: r.dir.includes('n') || r.dir.includes('s') });
    setGuideX(gx);
    setGuideY(gy);
  }, [scale, contentW]);

  const onResizeUp = useCallback((e: React.PointerEvent) => {
    const r = resizeRef.current;
    resizeRef.current = null;
    setGuideX(null);
    setGuideY(null);
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch { /* noop */ }
    if (r && resizeLive && onResizeBlock) {
      const patch: { w?: number; h?: number; x?: number; y?: number } = { w: Math.round(resizeLive.w) };
      // Height only persists when the user dragged a vertical handle.
      if (r.dir.includes('n') || r.dir.includes('s')) patch.h = Math.round(resizeLive.h);
      if (r.positioned) { patch.x = Math.round(resizeLive.x); patch.y = Math.round(resizeLive.y); }
      onResizeBlock(r.id, patch);
    }
    setResizeLive(null);
  }, [resizeLive, onResizeBlock]);

  const isEmpty = blocks.length === 0;

  // Render a single block wrapper (flow or absolute) with drag + resize.
  const renderWrapper = (block: PageBlock, positioned: boolean) => {
    // A split table part carries `_origId`; its `id` is `origId#partN`.
    const origId = (block as PageBlock & { _origId?: string })._origId ?? block.id;
    const partOf = (_b: PageBlock, oid: string): TableSplitPart | undefined => {
      const parts = tableSplits?.[oid];
      if (!parts) return undefined;
      return parts.find(p => p.id === block.id) ?? parts.find(p => p.page === pageNumber - 1);
    };
    const liveThis = live && live.id === block.id;
    const rs = resizeLive && resizeLive.id === block.id ? resizeLive : null;
    const x = liveThis ? live!.x : rs ? rs.x : block.x ?? 0;
    const y = liveThis ? live!.y : rs ? rs.y : block.y ?? 0;
    // `live` is only ever set after a float-move begins, so a live entry for
    // this block means it is actively being dragged to a free position.
    const dragging = dragId === block.id;
    const resizing = !!rs;
    const isSel = selectedBlockId === block.id;
    const showChrome = isSel && block.status === 'done';

    // Document-first sizing: flowing blocks resize WIDTH only and auto-fit their
    // height (so nothing is ever clipped); figures and floating blocks may also
    // carry an explicit height.
    const allowHeight = positioned || block.kind === 'chart' || block.kind === 'table';
    const width = rs ? rs.w : widthOf(block);
    const height = allowHeight ? (rs && rs.vert ? rs.h : block.h) : undefined;
    const edges = resizableEdges(block.kind, positioned);

    const lift = dragging;
    const style: React.CSSProperties = positioned
      ? {
          position: 'absolute', left: x, top: y, width,
          height: height ?? undefined,
          zIndex: lift || resizing ? Z.dragLift : isSel ? Z.selected : Z.content,
          opacity: dragging ? 0.92 : 1,
          boxShadow: lift ? '0 8px 24px rgba(37,99,235,0.18)' : undefined,
          transition: dragging || resizing ? 'none' : 'box-shadow 0.15s',
        }
      : {
          width, height: height ?? undefined,
          zIndex: dragging ? Z.dragLift : isSel ? Z.selected : undefined,
          opacity: dragging ? 0.55 : 1,
          boxShadow: lift ? '0 8px 24px rgba(37,99,235,0.18)' : undefined,
          transition: dragging || resizing ? 'none' : 'box-shadow 0.15s, opacity 0.15s',
        };

    return (
      <div
        key={block.id}
        data-block-id={block.id}
        onPointerDown={e => { e.stopPropagation(); if (block.status === 'done') onSelectBlock(block.id); }}
        className="relative"
        style={style}
      >
        {/* Gutter drag grip — the single drag entry point (keeps body free for typing) */}
        {showChrome && (
          <DragHandle
            active={dragging}
            onPointerDown={e => onDragHandleDown(e, block)}
            onPointerMove={onDragHandleMove}
            onPointerUp={onDragHandleUp}
          />
        )}

        {/* Selection toolbar — above-left, clear of the resize grips */}
        {showChrome && (
          <BlockActionBar
            block={block}
            floating={!!block.floating}
            flagged={isFlagged?.(origId) ?? false}
            onAsk={onAskBlock}
            onComment={onCommentBlock}
            onFlag={onFlagBlock}
            onToggleFloat={onSetFloating ? (id, fl) => onSetFloating(id, fl, block.x, block.y) : undefined}
            onDuplicate={onDuplicateBlock}
            onDelete={onDeleteBlock}
          />
        )}

        {/* Content. Flowing blocks never clip (auto height); only an explicitly
            sized figure / floating block is height-bounded. */}
        <div className={height ? 'h-full overflow-hidden' : ''}>
          <BlockRenderer
            block={block}
            isSelected={isSel}
            onSelect={() => onSelectBlock(block.id)}
            onGenerate={onGenerate}
            onUpdate={onUpdateBlock}
            onAddFootnote={onAddFootnote}
            commentCount={commentCount?.(origId) ?? 0}
            flagged={isFlagged?.(origId) ?? false}
            numerals={numerals}
            numbering={numbering?.[origId]}
            tableCaption={tableCaptions?.[origId]}
            splitPart={partOf(block, origId)}
          />
        </div>

        {/* Resize grips — width-only for flowing text, all eight for figures/floats */}
        {showChrome && onResizeBlock && !dragging && (
          <ResizeHandles
            edges={edges}
            onResizeDown={(e, dir) => onResizeDown(e, block, dir)}
            onResizeMove={onResizeMove}
            onResizeUp={onResizeUp}
          />
        )}
      </div>
    );
  };

  const flowBlocks = blocks.filter(b => !b.floating && live?.id !== b.id);
  const posBlocks = blocks.filter(b => b.floating || live?.id === b.id);

  // ── Estimate-then-measure (D-L1): report each flow block's REAL rendered
  //   height so the packer reflows on the true boundary instead of clipping.
  //   A signature of the flow ids + content lengths keeps the effect cheap. ─
  const flowSig = flowBlocks.map(b => `${b.id}:${(b.content || '').length}:${b.status}`).join('|');
  useEffect(() => {
    if (!onReportHeights || !contentRef.current) return;
    const measure = () => {
      const root = contentRef.current;
      if (!root) return;
      const out: Record<string, number> = {};
      root.querySelectorAll<HTMLElement>('[data-block-id]').forEach(el => {
        const id = el.getAttribute('data-block-id');
        // Only measure flow blocks (absolute/pinned ones report their own size).
        if (!id || el.style.position === 'absolute') return;
        const h = el.offsetHeight;          // unscaled (CSS transform ignores offsetHeight)
        if (h > 0) out[id] = h;
      });
      if (Object.keys(out).length) onReportHeights(out);
    };
    const raf = requestAnimationFrame(measure);
    // Re-measure on late content/layout shifts (images, fonts, async charts).
    const ro = new ResizeObserver(() => requestAnimationFrame(measure));
    contentRef.current.querySelectorAll<HTMLElement>('[data-block-id]').forEach(el => {
      if (el.style.position !== 'absolute') ro.observe(el);
    });
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [flowSig, onReportHeights]);

  // `live` is only ever set in onPointerMove AFTER a move arms, so its presence
  // already implies the block moved — no render-time ref read needed.
  const badge = live
    ? { x: live.x, y: Math.max(0, live.y - 20), mmX: mm(live.x), mmY: mm(live.y) }
    : null;

  // Size readout while resizing (mm), pinned to the block's top-left.
  const sizeBadge = resizeLive
    ? { x: resizeLive.x, y: Math.max(0, resizeLive.y - 20), mmW: mm(resizeLive.w), mmH: mm(resizeLive.h) }
    : null;

  return (
    // Outer wrapper reserves the SCALED footprint so the parent can scroll when
    // the page is larger than the viewport. Animates on page-size / zoom change.
    <div
      className="relative transition-[width,height] duration-300 ease-out"
      style={{ width: pageW * scale, height: pageH * scale }}
    >
      <div
        className="absolute left-0 top-0 bg-white select-none origin-top-left transition-[width,height,transform] duration-300 ease-out"
        style={{
          width: `${dim.w}mm`,
          height: `${dim.h}mm`,
          padding: `${PAD.top}mm ${PAD.right}mm ${PAD.bottom}mm ${PAD.left}mm`,
          boxShadow: '0 1px 4px rgba(0,0,0,0.05), 0 4px 24px rgba(0,0,0,0.03)',
          transform: `scale(${scale})`,
        }}
        onPointerDown={() => onSelectBlock(null)}
      >
        {/* Content area — positioning context for absolute blocks + guides.
            overflow-visible so the gutter grip / action bar (which sit just
            outside a block's box) are not clipped; pagination keeps flow
            content within the page, so nothing spills in normal use. */}
        <div ref={contentRef} className="relative h-full overflow-visible">
          {isEmpty ? (
            <div className="flex h-full flex-col items-center justify-center text-slate-300">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-50">
                <svg className="h-8 w-8 text-slate-200" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4v16m8-8H4" /></svg>
              </div>
              <p className="text-[13px] font-medium">Empty page</p>
              <p className="mt-1 text-[11px]">Click a toolbar element, or drag blocks to position them</p>
            </div>
          ) : (
            <>
              {/* Flow stack (document order). FLIP-style transition lets blocks
                  glide when the order changes instead of jumping. */}
              {flowBlocks.length > 0 && (
                <div className="space-y-3">
                  {flowBlocks.map(b => renderWrapper(b, false))}
                </div>
              )}
              {/* Free-positioned blocks (absolute overlay) */}
              {posBlocks.map(b => renderWrapper(b, true))}

              {/* Reorder insertion caret (document-first drag) */}
              {caretY !== null && <InsertionCaret y={caretY} />}

              {/* Alignment guides (Canva-style) */}
              {guideX !== null && (
                <div className="pointer-events-none absolute top-0 bottom-0 w-px bg-pink-500/70" style={{ left: guideX, zIndex: Z.guides }} />
              )}
              {guideY !== null && (
                <div className="pointer-events-none absolute left-0 right-0 h-px bg-pink-500/70" style={{ top: guideY, zIndex: Z.guides }} />
              )}

              {/* Minimal coordinate badge */}
              {badge && (
                <div
                  className="pointer-events-none absolute z-[60] rounded bg-slate-800/90 px-1.5 py-0.5 text-[9px] font-medium tabular-nums text-white shadow"
                  style={{ left: badge.x, top: badge.y }}
                >
                  {badge.mmX} · {badge.mmY} mm
                </div>
              )}

              {/* Size readout while resizing */}
              {sizeBadge && (
                <div
                  className="pointer-events-none absolute z-[60] rounded bg-blue-600/95 px-1.5 py-0.5 text-[9px] font-medium tabular-nums text-white shadow"
                  style={{ left: sizeBadge.x, top: sizeBadge.y }}
                >
                  {sizeBadge.mmW} × {sizeBadge.mmH} mm
                </div>
              )}
            </>
          )}
        </div>

        {/* Running header (report title │ current chapter) */}
        <div className="absolute top-[8mm] left-[22mm] right-[22mm] flex items-center justify-between border-b border-slate-100 pb-1 text-[8px] text-slate-300">
          <span className="font-medium">{reportTitle}</span>
          {chapterLabel && <span className="italic">{chapterLabel}</span>}
        </div>

        {/* Running footer (org │ page X of Y) */}
        <div className="absolute bottom-[8mm] left-[22mm] right-[22mm] flex items-center justify-between border-t border-slate-100 pt-1 text-[8px] text-slate-300">
          <span>{footerOrg}</span>
          <span className="tabular-nums">Page {pageNumber} of {totalPages}</span>
        </div>
      </div>
    </div>
  );
}
