'use client';
import { useRef, useState, useCallback, useEffect } from 'react';
import type { PageBlock } from '../engine/useCanvasState';
import type { NumberedHeading, TableSplitPart } from '../engine/paginationEngine';
import { BlockRenderer } from '../blocks/BlockRenderer';

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

const MM_TO_PX = 3.7795;            // 96dpi
const SNAP = 6;                     // snap threshold (unscaled px)
const PAD = { top: 18, right: 22, bottom: 20, left: 22 }; // mm
const MIN_W = 60;                   // min block width (px)
const MIN_H = 28;                   // min block height (px)
const LONG_PRESS_MS = 220;          // hold this long before a drag arms
const PRESS_CANCEL = 8;             // moving more than this before arming cancels the long-press

/** Intrinsic default width (px) per block kind — so a metric card isn't full
 *  width and a table stays wide. ``full`` resolves to the content width. */
function intrinsicWidth(kind: PageBlock['kind'], contentW: number): number {
  switch (kind) {
    case 'metric':       return 190;
    case 'source_note':  return 320;
    case 'chart':        return 360;
    case 'key_finding':  return 440;
    case 'narrative':    return Math.min(480, contentW);   // ~65ch readable column
    case 'heading':      return contentW;
    case 'table':        return contentW;
    case 'divider':      return contentW;
    default:             return Math.min(440, contentW);
  }
}

/** The 8 resize handles + which edges each drives. */
type HandleDir = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
const HANDLES: { dir: HandleDir; cls: string; cursor: string }[] = [
  { dir: 'nw', cls: 'left-0 top-0 -translate-x-1/2 -translate-y-1/2', cursor: 'nwse-resize' },
  { dir: 'n',  cls: 'left-1/2 top-0 -translate-x-1/2 -translate-y-1/2', cursor: 'ns-resize' },
  { dir: 'ne', cls: 'right-0 top-0 translate-x-1/2 -translate-y-1/2', cursor: 'nesw-resize' },
  { dir: 'e',  cls: 'right-0 top-1/2 translate-x-1/2 -translate-y-1/2', cursor: 'ew-resize' },
  { dir: 'se', cls: 'right-0 bottom-0 translate-x-1/2 translate-y-1/2', cursor: 'nwse-resize' },
  { dir: 's',  cls: 'left-1/2 bottom-0 -translate-x-1/2 translate-y-1/2', cursor: 'ns-resize' },
  { dir: 'sw', cls: 'left-0 bottom-0 -translate-x-1/2 translate-y-1/2', cursor: 'nesw-resize' },
  { dir: 'w',  cls: 'left-0 top-1/2 -translate-x-1/2 -translate-y-1/2', cursor: 'ew-resize' },
];

interface A4PageProps {
  blocks: PageBlock[];
  pageNumber: number;
  totalPages: number;
  selectedBlockId: string | null;
  onSelectBlock: (id: string | null) => void;
  onGenerate?: (index: number) => void;
  onMoveBlock?: (id: string, x: number, y: number, w?: number) => void;
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
}

interface DragRef {
  id: string;
  pointerId: number;
  el: HTMLElement;
  armed: boolean;          // becomes true only after the long-press fires
  pointerStartX: number;
  pointerStartY: number;
  blockStartX: number;
  blockStartY: number;
  w: number;
  h: number;
  moved: boolean;
  xTargets: number[];
  yTargets: number[];
}

export function A4Page({
  blocks, pageNumber, totalPages, selectedBlockId, onSelectBlock,
  onGenerate, onMoveBlock, onUpdateBlock, onDeleteBlock, onDuplicateBlock, onResizeBlock, pageSize = 'a4', zoom = 100,
  numbering, tableCaptions, tableSplits, chapterLabel, reportTitle = 'MoSPI Statistical Report', onAskBlock, onAddFootnote,
  onCommentBlock, onFlagBlock, commentCount, isFlagged, numerals, footerOrg = 'MoSPI · Government of India',
}: A4PageProps) {
  const dim = PAGE_DIMENSIONS[pageSize];
  const scale = zoom / 100;
  const pageW = dim.w * MM_TO_PX;
  const pageH = dim.h * MM_TO_PX;
  const contentW = (dim.w - PAD.left - PAD.right) * MM_TO_PX;
  const contentH = (dim.h - PAD.top - PAD.bottom) * MM_TO_PX;

  const contentRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragRef | null>(null);
  const pressTimer = useRef<number | null>(null);
  const [pressing, setPressing] = useState<string | null>(null);   // block armed for move
  const [live, setLive] = useState<{ id: string; x: number; y: number } | null>(null);
  const [guideX, setGuideX] = useState<number | null>(null);
  const [guideY, setGuideY] = useState<number | null>(null);

  // ── Resize ──────────────────────────────────────────────────────────────
  const resizeRef = useRef<{
    id: string; dir: HandleDir; px: number; py: number;
    x0: number; y0: number; w0: number; h0: number; positioned: boolean;
    xTargets: number[]; yTargets: number[];
  } | null>(null);
  const [resizeLive, setResizeLive] = useState<{ id: string; w: number; h: number; x: number; y: number } | null>(null);

  const mm = (px: number) => Math.round(px / MM_TO_PX);

  // Clear any pending long-press timer on unmount.
  useEffect(() => () => { if (pressTimer.current) window.clearTimeout(pressTimer.current); }, []);

  /** The effective width of a block (explicit ``w`` or its intrinsic default). */
  const widthOf = (b: PageBlock) => b.w ?? intrinsicWidth(b.kind, contentW);

  // ── Pointer down: select + START LONG-PRESS timer (drag arms only on hold) ─
  // Deferring pointer capture until the hold fires keeps fast clicks free for
  // single-click=select and double-click=edit. A quick move cancels the hold.
  const onPointerDown = useCallback((e: React.PointerEvent, block: PageBlock) => {
    if (block.status !== 'done') return;       // only finished blocks are movable
    e.stopPropagation();                        // don't let the page deselect
    onSelectBlock(block.id);
    const content = contentRef.current;
    if (!content) return;
    const cRect = content.getBoundingClientRect();
    const el = e.currentTarget as HTMLElement;
    const bRect = el.getBoundingClientRect();
    const startX = (bRect.left - cRect.left) / scale;
    const startY = (bRect.top - cRect.top) / scale;
    const w = bRect.width / scale;
    const h = bRect.height / scale;

    // Gather alignment targets from every OTHER block + the page frame.
    const xTargets: number[] = [0, contentW, contentW / 2];
    const yTargets: number[] = [0, contentH, contentH / 2];
    content.querySelectorAll<HTMLElement>('[data-block-id]').forEach(node => {
      if (node.dataset.blockId === block.id) return;
      const r = node.getBoundingClientRect();
      const x0 = (r.left - cRect.left) / scale;
      const y0 = (r.top - cRect.top) / scale;
      const wEl = r.width / scale;
      const hEl = r.height / scale;
      xTargets.push(x0, x0 + wEl / 2, x0 + wEl);
      yTargets.push(y0, y0 + hEl / 2, y0 + hEl);
    });

    const pointerId = e.pointerId;
    dragRef.current = {
      id: block.id, pointerId, el, armed: false,
      pointerStartX: e.clientX, pointerStartY: e.clientY,
      blockStartX: startX, blockStartY: startY, w, h, moved: false, xTargets, yTargets,
    };
    // Arm the drag after a deliberate hold.
    if (pressTimer.current) window.clearTimeout(pressTimer.current);
    pressTimer.current = window.setTimeout(() => {
      const d = dragRef.current;
      if (!d) return;
      d.armed = true;
      try { d.el.setPointerCapture(pointerId); } catch { /* noop */ }
      setPressing(d.id);
    }, LONG_PRESS_MS);
  }, [onSelectBlock, scale, contentW, contentH]);

  // ── Pointer move: cancel hold on a quick drag, else move with snap+guides ──
  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = (e.clientX - d.pointerStartX) / scale;
    const dy = (e.clientY - d.pointerStartY) / scale;

    if (!d.armed) {
      // Moving before the hold fires = a click/scroll intent, not a move.
      if (Math.hypot(dx, dy) > PRESS_CANCEL) {
        if (pressTimer.current) { window.clearTimeout(pressTimer.current); pressTimer.current = null; }
        dragRef.current = null;
      }
      return;
    }
    d.moved = true;

    let nx = d.blockStartX + dx;
    let ny = d.blockStartY + dy;

    // Snap X: test left / centre / right edges against targets.
    let gx: number | null = null;
    let bestX = SNAP + 1;
    for (const edge of [nx, nx + d.w / 2, nx + d.w]) {
      for (const t of d.xTargets) {
        const dist = Math.abs(edge - t);
        if (dist <= SNAP && dist < bestX) { bestX = dist; nx += t - edge; gx = t; }
      }
    }
    // Snap Y: top / middle / bottom.
    let gy: number | null = null;
    let bestY = SNAP + 1;
    for (const edge of [ny, ny + d.h / 2, ny + d.h]) {
      for (const t of d.yTargets) {
        const dist = Math.abs(edge - t);
        if (dist <= SNAP && dist < bestY) { bestY = dist; ny += t - edge; gy = t; }
      }
    }

    // Clamp inside the content frame.
    nx = Math.max(0, Math.min(nx, Math.max(0, contentW - d.w)));
    ny = Math.max(0, Math.min(ny, Math.max(0, contentH - d.h)));

    setLive({ id: d.id, x: nx, y: ny });
    setGuideX(gx);
    setGuideY(gy);
  }, [scale, contentW, contentH]);

  // ── Pointer up: commit position (or treat as a click if not moved) ───────
  const onPointerUp = useCallback((e: React.PointerEvent) => {
    if (pressTimer.current) { window.clearTimeout(pressTimer.current); pressTimer.current = null; }
    const d = dragRef.current;
    dragRef.current = null;
    setPressing(null);
    setGuideX(null);
    setGuideY(null);
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch { /* noop */ }
    if (d && d.armed && d.moved && live && onMoveBlock) {
      onMoveBlock(d.id, live.x, live.y, d.w);
    }
    setLive(null);
  }, [live, onMoveBlock]);

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
      y: positioned ? block.y! : (bRect.top - cRect.top) / scale });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }, [scale]);

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

    setResizeLive({ id: r.id, w, h, x, y });
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
    const dragging = !!liveThis && !!dragRef.current?.moved;
    const armed = pressing === block.id;          // long-press fired, ready to move
    const resizing = !!rs;
    const isSel = selectedBlockId === block.id;

    const width = rs ? rs.w : widthOf(block);
    const height = rs && (resizeRef.current?.dir.includes('n') || resizeRef.current?.dir.includes('s'))
      ? rs.h : block.h;

    const lift = dragging || armed;
    const style: React.CSSProperties = positioned
      ? {
          position: 'absolute', left: x, top: y, width,
          height: height ?? undefined,
          zIndex: lift || resizing ? 50 : isSel ? 20 : 1,
          opacity: dragging ? 0.92 : 1,
          boxShadow: lift ? '0 8px 24px rgba(37,99,235,0.18)' : undefined,
          transition: dragging || resizing ? 'none' : 'box-shadow 0.15s',
        }
      : {
          width, height: height ?? undefined,
          boxShadow: lift ? '0 8px 24px rgba(37,99,235,0.18)' : undefined,
          transition: dragging ? 'none' : 'box-shadow 0.15s',
        };

    return (
      <div
        key={block.id}
        data-block-id={block.id}
        onPointerDown={e => onPointerDown(e, block)}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className={`relative touch-none ${block.status === 'done' ? (armed ? 'cursor-grabbing' : 'cursor-grab') : ''}`}
        style={style}
      >
        {/* Hold-to-move hint while the long-press is active */}
        {armed && !dragging && (
          <div className="pointer-events-none absolute -top-5 left-1/2 z-[60] -translate-x-1/2 rounded bg-blue-600 px-1.5 py-0.5 text-[8px] font-medium text-white shadow">
            Drag to move
          </div>
        )}
        <div className={height ? 'h-full overflow-hidden' : ''}>
          <BlockRenderer
            block={block}
            isSelected={isSel}
            onSelect={() => onSelectBlock(block.id)}
            onGenerate={onGenerate}
            onUpdate={onUpdateBlock}
            onDelete={onDeleteBlock}
            onDuplicate={onDuplicateBlock}
            onAsk={onAskBlock}
            onAddFootnote={onAddFootnote}
            onComment={onCommentBlock}
            onFlag={onFlagBlock}
            commentCount={commentCount?.(origId) ?? 0}
            flagged={isFlagged?.(origId) ?? false}
            numerals={numerals}
            numbering={numbering?.[origId]}
            tableCaption={tableCaptions?.[origId]}
            splitPart={partOf(block, origId)}
          />
        </div>

        {/* Resize handles (Canva-style) — only on the selected, finished block */}
        {isSel && block.status === 'done' && onResizeBlock && !dragging && (
          <>
            {HANDLES.map(h => (
              <div
                key={h.dir}
                onPointerDown={e => onResizeDown(e, block, h.dir)}
                onPointerMove={onResizeMove}
                onPointerUp={onResizeUp}
                style={{ cursor: h.cursor }}
                className={`absolute z-40 h-2 w-2 rounded-[2px] border border-blue-500 bg-white shadow-sm ${h.cls}`}
              />
            ))}
          </>
        )}
      </div>
    );
  };

  const flowBlocks = blocks.filter(b => (b.x === undefined || b.y === undefined) && live?.id !== b.id);
  const posBlocks = blocks.filter(b => (b.x !== undefined && b.y !== undefined) || live?.id === b.id);

  const badge = live && dragRef.current?.moved
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
        {/* Content area — positioning context for absolute blocks + guides */}
        <div ref={contentRef} className="relative h-full overflow-hidden">
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
              {/* Flow stack (unpositioned blocks) */}
              {flowBlocks.length > 0 && (
                <div className="space-y-3">
                  {flowBlocks.map(b => renderWrapper(b, false))}
                </div>
              )}
              {/* Free-positioned blocks (absolute overlay) */}
              {posBlocks.map(b => renderWrapper(b, true))}

              {/* Alignment guides (Canva-style) */}
              {guideX !== null && (
                <div className="pointer-events-none absolute top-0 bottom-0 w-px bg-pink-500/70" style={{ left: guideX }} />
              )}
              {guideY !== null && (
                <div className="pointer-events-none absolute left-0 right-0 h-px bg-pink-500/70" style={{ top: guideY }} />
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
