/* ═══════════════════════════════════════════════════════════════════
   Pagination Engine — height-aware page packing for the MoSPI canvas.

   Pure, framework-free functions (no React) so they are trivially
   testable and reusable by the renderer, the auto-generator, and the
   layout-aware assistant.

   Implements the locked architecture decisions:
   • D-L1  estimate-then-measure heights, greedy pack to a px budget.
   • D-L2  decimal §-numbering (1 / 1.1 / 1.1.1) + stable anchor ids.
   • D-L3  keep-together (no orphaned heading) + oversized-table split
           with a repeated header + "(contd.)" continuation caption.
   ═══════════════════════════════════════════════════════════════════ */

import type { PageBlock } from './useCanvasState';

/* ── A4 geometry (must mirror viewport/A4Page.tsx) ─────────────────── */
export const MM_TO_PX = 3.7795; // 96 dpi
const A4 = { w: 210, h: 297 };
const PAD = { top: 18, right: 22, bottom: 20, left: 22 }; // mm
/** Usable content width / height of one sheet, in unscaled px. */
export const CONTENT_W = Math.round((A4.w - PAD.left - PAD.right) * MM_TO_PX); // ≈627
export const CONTENT_H = Math.round((A4.h - PAD.top - PAD.bottom) * MM_TO_PX); // ≈979
/** Fill target — pack to ~92% of the sheet, leaving a safe tail so small
 *  height under-estimates never overflow the ``overflow-hidden`` content area
 *  (which would clip a block instead of reflowing it to the next page). */
export const PAGE_BUDGET = Math.round(CONTENT_H * 0.92);

/* ── Per-kind height model (px) — tuned to BlockRenderer output ────── */
const ROW_H = 28;          // one table body row (matches td py + border)
const TABLE_HEAD_H = 34;   // table header strip + thead row
const TABLE_CAPTION_H = 24;// numbered caption above a table
const TABLE_FOOT_H = 30;   // unit/source note + total row padding
const NARR_LINE_H = 22;    // one wrapped narrative line
const CHARS_PER_LINE = 84; // ~ at 627px, 10.5px body (conservative)
const VSTACK_GAP = 12;     // matches the flow stack space-y-3

/** Estimate a wrapped text block's line count from its length. */
function lineCount(text: string, charsPerLine = CHARS_PER_LINE): number {
  if (!text) return 1;
  // account for explicit breaks plus soft-wrap
  const hard = text.split(/\n/);
  let lines = 0;
  for (const seg of hard) lines += Math.max(1, Math.ceil(seg.length / charsPerLine));
  return Math.max(1, lines);
}

/** Number of data rows a table block carries (any of the known shapes). */
export function tableRowCount(block: PageBlock): number {
  const td = block.tableData;
  if (!td) return 0;
  const rows =
    (td.items as unknown[]) ||
    (td.rankingData as unknown[]) ||
    (td.aggregationData as unknown[]) ||
    (td.rows as unknown[]) ||
    [];
  return Array.isArray(rows) ? rows.length : 0;
}

/**
 * Estimate the rendered height (px) of a block, including the stack gap.
 * Hierarchy headings get a type-scale height keyed off their § depth.
 *
 * `opts.scale` mirrors the live document type-scale and `opts.lineHeight` the
 * body line-height, so page packing stays in sync with what BlockRenderer
 * actually paints once the officer changes typography. Without this the packer
 * under-counts tall type and content overflows (or is clipped) on the sheet.
 */
export interface PackOpts {
  /** Document type-scale (TypographyConfig.typeScale); 1 = base. */
  scale?: number;
  /** Body line-height (TypographyConfig.lineHeight); 1.7 = base. */
  lineHeight?: number;
  /** Real rendered block heights (px), keyed by block id. When a block has a
   *  measured height the packer trusts it over the estimate — so pages break on
   *  the TRUE boundary and content never overflows the sheet / hides under the
   *  footer. Populated by the viewport after each paint (estimate-then-measure). */
  measured?: Record<string, number>;
}

const BASE_LINE_HEIGHT = 1.7;

export function estimateHeight(block: PageBlock, opts: PackOpts = {}): number {
  // Estimate-then-MEASURE: a real rendered height (when known) always wins, so
  // the packer reflows on the exact boundary instead of clipping a guess.
  const measured = opts.measured?.[block.id];
  if (measured && measured > 0 && block.kind !== 'table') {
    // Tables may be split by the packer, so they keep the row-model estimate.
    return measured + VSTACK_GAP;
  }
  const s = opts.scale ?? 1;
  const lhRatio = (opts.lineHeight ?? BASE_LINE_HEIGHT) / BASE_LINE_HEIGHT;
  const narrLine = NARR_LINE_H * s * lhRatio; // wrapped line height tracks type + leading
  const depth = headingDepth(block); // 1=topic, 2=chapter, 3=section, 0=not a heading
  switch (block.kind) {
    case 'heading': {
      // Topic (1) tallest with its underline rule, Chapter (2), Section (3).
      const base = (depth === 1 ? 46 : depth === 2 ? 34 : 30) * s;
      return base + VSTACK_GAP;
    }
    case 'narrative': {
      // Section pseudo-headings (rendered as a labelled paragraph) are compact.
      if (isSectionMarker(block)) return 30 * s + VSTACK_GAP;
      return lineCount(block.content) * narrLine + 12 + VSTACK_GAP;
    }
    case 'key_finding':
      // Rendered in a tinted card with extra padding — count generously so the
      // highlights block never overflows / clips the page.
      return lineCount(block.content) * narrLine + 40 * s + VSTACK_GAP;
    case 'metric':
      return 72 * s + VSTACK_GAP;
    case 'source_note':
      return 24 * s + VSTACK_GAP;
    case 'divider':
      return 24 + VSTACK_GAP;
    case 'chart':
      return 200 + TABLE_CAPTION_H * s + VSTACK_GAP;
    case 'table': {
      const rows = Math.max(1, tableRowCount(block));
      return (
        (TABLE_CAPTION_H + TABLE_HEAD_H + rows * ROW_H + TABLE_FOOT_H) * s +
        VSTACK_GAP
      );
    }
    default:
      return 60 + VSTACK_GAP;
  }
}

/** How many body rows of a table fit into `avail` px (after its chrome). */
export function tableRowsThatFit(avail: number, opts: PackOpts = {}): number {
  const s = opts.scale ?? 1;
  const usable = avail - (TABLE_CAPTION_H + TABLE_HEAD_H + TABLE_FOOT_H) * s - VSTACK_GAP;
  return Math.max(0, Math.floor(usable / (ROW_H * s)));
}

/* ── Hierarchy helpers (D-L2) ─────────────────────────────────────── */

/** A "Topic:"/"Chapter:" heading block carries its level via sectionPath length. */
export function headingDepth(block: PageBlock): number {
  if (block.kind === 'heading') {
    // Topic heading: 1 element; Chapter heading: 2 elements.
    return Math.min(2, Math.max(1, block.sectionPath.length));
  }
  if (isSectionMarker(block)) return 3;
  return 0;
}

/** Section markers are narrative blocks whose content starts with "Section:". */
export function isSectionMarker(block: PageBlock): boolean {
  return block.kind === 'narrative' && /^section:/i.test(block.content.trim());
}

/** True for any heading-like block (topic/chapter heading or section marker). */
export function isHeadingLike(block: PageBlock): boolean {
  return block.kind === 'heading' || isSectionMarker(block);
}

/* ── Packing (D-L1 + D-L3) ────────────────────────────────────────── */

export interface PackedPage {
  index: number;
  /** Block ids in order on this page. */
  blocks: string[];
  /** Sum of estimated block heights (px) placed on this page. */
  usedPx: number;
}

export interface PackResult {
  pages: PackedPage[];
  /** Per-block continuation metadata produced by table splits, keyed by the
   *  ORIGINAL block id. Renderer uses this to show only a row window + caption. */
  splits: Record<string, TableSplitPart[]>;
}

export interface TableSplitPart {
  /** Synthetic id for this part (origId or origId#partN). */
  id: string;
  origId: string;
  partIndex: number;     // 0-based
  partCount: number;     // total parts
  rowStart: number;      // inclusive
  rowEnd: number;        // exclusive
  page: number;
  continued: boolean;    // true for parts after the first ("(contd.)")
}

interface Sized {
  block: PageBlock;
  height: number;
}

/**
 * Greedily pack ordered blocks into pages of `budget` px with keep-together.
 *
 * Rules:
 *  • A heading-like block never sits alone at the bottom — if it would, and a
 *    following body block exists, both move to the next page together.
 *  • A table taller than the remaining space is split at a row boundary; the
 *    continuation repeats the header and is flagged `continued`.
 *  • A table taller than a WHOLE page is split across as many pages as needed.
 */
export function packBlocks(ordered: PageBlock[], budget = PAGE_BUDGET, opts: PackOpts = {}): PackResult {
  const s = opts.scale ?? 1;
  const sized: Sized[] = ordered.map((b) => ({ block: b, height: estimateHeight(b, opts) }));
  const pages: PackedPage[] = [{ index: 0, blocks: [], usedPx: 0 }];
  const splits: Record<string, TableSplitPart[]> = {};

  let pi = 0;
  const cur = () => pages[pi];
  const remaining = () => budget - cur().usedPx;
  const newPage = () => {
    pages.push({ index: pages.length, blocks: [], usedPx: 0 });
    pi = pages.length - 1;
  };

  for (let i = 0; i < sized.length; i++) {
    const { block, height } = sized[i];

    // ── Keep-together: don't orphan a heading at the very bottom ──
    if (isHeadingLike(block) && i + 1 < sized.length) {
      const next = sized[i + 1];
      const needed = height + next.height;
      if (cur().usedPx > 0 && needed > remaining() && next.height <= budget) {
        newPage();
      }
    }

    // ── Oversized table: split across pages (D-L3) ──
    if (block.kind === 'table' && height > remaining() && tableRowCount(block) > 0) {
      const totalRows = tableRowCount(block);
      const parts: TableSplitPart[] = [];
      let rowCursor = 0;
      let partIdx = 0;

      while (rowCursor < totalRows) {
        if (remaining() < (TABLE_CAPTION_H + TABLE_HEAD_H + TABLE_FOOT_H + ROW_H) * s) {
          newPage();
        }
        const fit = Math.max(1, tableRowsThatFit(remaining(), opts));
        const rowEnd = Math.min(totalRows, rowCursor + fit);
        const partId = partIdx === 0 ? block.id : `${block.id}#${partIdx}`;
        parts.push({
          id: partId,
          origId: block.id,
          partIndex: partIdx,
          partCount: 0, // patched after loop
          rowStart: rowCursor,
          rowEnd,
          page: pi,
          continued: partIdx > 0,
        });
        const partHeight =
          (TABLE_CAPTION_H + TABLE_HEAD_H + (rowEnd - rowCursor) * ROW_H + TABLE_FOOT_H) * s + VSTACK_GAP;
        cur().blocks.push(partId);
        cur().usedPx += partHeight;
        rowCursor = rowEnd;
        partIdx++;
        if (rowCursor < totalRows) newPage();
      }
      for (const p of parts) p.partCount = parts.length;
      splits[block.id] = parts;
      continue;
    }

    // ── Normal block: new page if it won't fit (unless page is empty) ──
    if (height > remaining() && cur().usedPx > 0) {
      newPage();
    }
    cur().blocks.push(block.id);
    cur().usedPx += height;
  }

  return { pages, splits };
}

/* ── Decimal numbering (D-L2) ─────────────────────────────────────── */

export interface NumberedHeading {
  id: string;
  number: string;   // "1", "1.1", "1.1.1"
  depth: number;    // 1..3
  anchor: string;   // "sec-1-1-1"
}

/**
 * Walk ordered blocks and assign decimal section numbers + anchors to every
 * heading-like block, based on Topic→Chapter→Section transitions in sectionPath.
 * Returns a map keyed by block id.
 */
export function assignNumbering(ordered: PageBlock[]): Record<string, NumberedHeading> {
  const out: Record<string, NumberedHeading> = {};
  const counters = [0, 0, 0]; // topic, chapter, section
  let lastTopic = '';
  let lastChapter = '';
  let lastSection = '';

  for (const b of ordered) {
    const depth = headingDepth(b);
    if (depth === 0) continue;

    const [topic, chapter] = b.sectionPath;
    const sectionName = sectionLabel(b);

    if (depth === 1) {
      if (topic !== lastTopic) {
        counters[0] += 1;
        counters[1] = 0;
        counters[2] = 0;
        lastTopic = topic || '';
        lastChapter = '';
        lastSection = '';
      }
      out[b.id] = mk(b.id, `${counters[0]}`, 1);
    } else if (depth === 2) {
      if (topic !== lastTopic) {
        counters[0] += 1;
        counters[1] = 0;
        counters[2] = 0;
        lastTopic = topic || '';
        lastChapter = '';
        lastSection = '';
      }
      if (chapter !== lastChapter) {
        counters[1] += 1;
        counters[2] = 0;
        lastChapter = chapter || '';
        lastSection = '';
      }
      out[b.id] = mk(b.id, `${counters[0]}.${counters[1]}`, 2);
    } else {
      // section
      if (sectionName !== lastSection) {
        counters[2] += 1;
        lastSection = sectionName;
      }
      out[b.id] = mk(b.id, `${counters[0]}.${counters[1]}.${counters[2]}`, 3);
    }
  }
  return out;

  function mk(id: string, number: string, depth: number): NumberedHeading {
    return { id, number, depth, anchor: `sec-${number.replace(/\./g, '-')}` };
  }
}

/** Display label for a heading-like block (strips the "Section:" prefix). */
export function sectionLabel(block: PageBlock): string {
  if (isSectionMarker(block)) return block.content.replace(/^section:\s*/i, '').trim();
  return (block.content || block.title || '').replace(/^(topic|chapter):\s*/i, '').trim();
}

/* ── Layout digest for the assistant (D-L5) ───────────────────────── */

export interface PageCapacity {
  page: number;       // 1-based
  usedPx: number;
  remainingPx: number;
  fillPct: number;    // 0..100
  blockCount: number;
}

export interface LayoutDigest {
  totalPages: number;
  budgetPx: number;
  pages: PageCapacity[];
  /** The page with the most free space (best landing spot for a new block). */
  emptiestPage: number;
  /** Whether the last page can still take an average narrative (~5 lines). */
  lastPageHasRoom: boolean;
}

/**
 * Summarise per-page capacity so the assistant can right-size content and
 * answer "is this page full?"/"where will this land?" questions.
 * `ordered` is the canonical flow order; pinned blocks are ignored.
 */
export function computeLayoutDigest(ordered: PageBlock[], budget = PAGE_BUDGET, opts: PackOpts = {}): LayoutDigest {
  const flow = ordered.filter(b => b.x === undefined || b.y === undefined);
  const { pages } = packBlocks(flow, budget, opts);
  const caps: PageCapacity[] = pages.map(p => {
    const remaining = Math.max(0, budget - p.usedPx);
    return {
      page: p.index + 1,
      usedPx: Math.round(p.usedPx),
      remainingPx: Math.round(remaining),
      fillPct: Math.min(100, Math.round((p.usedPx / budget) * 100)),
      blockCount: p.blocks.length,
    };
  });
  const emptiest = caps.reduce((best, c) => (c.remainingPx > (caps[best - 1]?.remainingPx ?? -1) ? c.page : best), caps[0]?.page ?? 1);
  const last = caps[caps.length - 1];
  const NARRATIVE_5_LINES = 5 * 21 + 24;
  return {
    totalPages: caps.length,
    budgetPx: budget,
    pages: caps,
    emptiestPage: emptiest,
    lastPageHasRoom: !!last && last.remainingPx >= NARRATIVE_5_LINES,
  };
}
