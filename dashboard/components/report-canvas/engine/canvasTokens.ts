/* ═══════════════════════════════════════════════════════════════════
   canvasTokens — the single source of truth for canvas geometry, the
   z-index ladder, and per-kind interaction capabilities.

   Why this file exists:
   • Magic numbers (mm↔px, snap, padding, min sizes) used to be duplicated
     across A4Page / paginationEngine. They now live here, once.
   • Z-index used to be ad-hoc (z-20/30/40/[60]/[70]…), which is what made
     the resize handle and the action bar collide. A single ordered ladder
     (`Z`) removes that whole class of bug.
   • Resize/float behaviour is decided per block kind in one table
     (`resizableEdges`, `canFloat`), so every component agrees.
   ═══════════════════════════════════════════════════════════════════ */

import type { PageBlock } from './useCanvasState';

/* ── Geometry ─────────────────────────────────────────────────────── */

export const MM_TO_PX = 3.7795;          // 96 dpi
export const SNAP = 6;                    // alignment snap threshold (unscaled px)
export const PAD = { top: 18, right: 22, bottom: 20, left: 22 }; // page padding (mm)
export const MIN_W = 60;                  // min block width (px)
export const MIN_H = 28;                  // min block height (px)

/* ── Drag affordance ──────────────────────────────────────────────── */

/** Moving more than this (px) before a drag commits is treated as intent. */
export const DRAG_THRESHOLD = 4;
/** Visible size of a resize handle (px). The hit area is larger (below). */
export const HANDLE_SIZE = 8;
/** Invisible padding around each handle so it is easy to grab (px). */
export const HANDLE_HIT_PAD = 7;

/* ── Z-index ladder ───────────────────────────────────────────────────
   Ordered so chrome that must sit ABOVE other chrome simply has a bigger
   number. Action bar (40) intentionally beats resize handles (30); the bar
   is also relocated out of the handle corner so they never share space. */
export const Z = {
  content: 1,
  selected: 10,
  reviewMarkers: 20,
  dragHandle: 25,
  resizeHandles: 30,
  actionBar: 40,
  guides: 50,
  dragLift: 60,
  badge: 70,
  richTextToolbar: 80,
  popover: 90,
  panel: 100,
  modal: 110,
  palette: 120,
} as const;

/* ── Per-kind intrinsic width ─────────────────────────────────────────
   Default width (px) for a block kind so a metric card isn't full width and
   a table stays wide. `contentW` is the usable page width. */
export function intrinsicWidth(kind: PageBlock['kind'], contentW: number): number {
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

/* ── Resize / float capabilities ──────────────────────────────────────
   Document-first model:
   • Flow blocks resize WIDTH only (e/w). Height auto-fits content and the
     packer re-paginates — so nothing is ever clipped.
   • Figures (chart/table) and any floating block may resize height too, so
     an officer can size a chart deliberately.  */
export type HandleDir = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

const WIDTH_ONLY: HandleDir[] = ['e', 'w'];
const ALL_EDGES: HandleDir[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

/** Which resize handles a block exposes, given whether it is floating. */
export function resizableEdges(kind: PageBlock['kind'], floating: boolean): HandleDir[] {
  if (floating) return ALL_EDGES;
  if (kind === 'chart' || kind === 'table') return ALL_EDGES;
  if (kind === 'divider') return WIDTH_ONLY;
  return WIDTH_ONLY;
}

/** Whether a vertical (height) resize should persist an explicit height. */
export function edgeChangesHeight(dir: HandleDir): boolean {
  return dir.includes('n') || dir.includes('s');
}

/** Editable text kinds (single-click → caret, type immediately). */
export const EDITABLE_KINDS = new Set<PageBlock['kind']>([
  'heading', 'narrative', 'key_finding', 'source_note', 'metric',
]);

/** Kinds that use the multiline rich-text editor (vs a single-line input). */
export const MULTILINE_KINDS = new Set<PageBlock['kind']>(['narrative', 'key_finding']);
