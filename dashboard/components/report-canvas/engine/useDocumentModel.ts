'use client';
import { useMemo } from 'react';
import type { CanvasPage, PageBlock } from './useCanvasState';
import {
  assignNumbering, isHeadingLike, headingDepth, sectionLabel,
  type NumberedHeading,
} from './paginationEngine';

/* ═══════════════════════════════════════════════════════════════════
   Document model — derives the publication structure (D-L2 numbering,
   D-L4 furniture data) from the canonical block order + page layout.

   Produces:
   • numbering        §-number + anchor per heading-like block
   • tableCaptions    "Table X.Y" per table block (sequential per chapter-less
                      global counter, matching printed MoSPI volumes)
   • toc              flat outline (number, label, depth, page) for the auto-TOC
   • listOfTables     numbered tables → page, for the "List of Tables"
   • chapterByPage    running-header chapter label per page index
   ═══════════════════════════════════════════════════════════════════ */

export interface TocEntry {
  number: string;
  label: string;
  depth: number;     // 1..3
  anchor: string;
  page: number;      // 1-based
}

export interface TableEntry {
  caption: string;   // "Table 1.1"
  title: string;
  page: number;      // 1-based
}

export interface DocumentModel {
  numbering: Record<string, NumberedHeading>;
  tableCaptions: Record<string, string>;
  toc: TocEntry[];
  listOfTables: TableEntry[];
  listOfFigures: TableEntry[];
  chapterByPage: Record<number, string>;
}

/** 1-based page index that a given block id lives on (split parts resolve to
 *  the page of their first part). */
function pageOfBlock(pages: CanvasPage[], id: string): number {
  for (const p of pages) {
    if (p.blocks.some(bid => bid === id || bid.startsWith(`${id}#`))) return p.index + 1;
  }
  return 1;
}

export function useDocumentModel(
  order: string[],
  blocks: Map<string, PageBlock>,
  pages: CanvasPage[],
): DocumentModel {
  return useMemo(() => {
    const ordered = order.map(id => blocks.get(id)).filter(Boolean) as PageBlock[];
    const numbering = assignNumbering(ordered);

    const tableCaptions: Record<string, string> = {};
    const listOfTables: TableEntry[] = [];
    const listOfFigures: TableEntry[] = [];
    const toc: TocEntry[] = [];
    const chapterByPage: Record<number, string> = {};

    // Sequential figure/table numbering tied to the current chapter number.
    let lastChapterNo = '';
    let tableCounter = 0;
    let figureCounter = 0;

    for (const b of ordered) {
      // Track the active chapter number for caption prefixes + running header.
      if (b.kind === 'heading' && headingDepth(b) <= 2) {
        const nb = numbering[b.id];
        if (nb && nb.depth === 2) { lastChapterNo = nb.number; tableCounter = 0; figureCounter = 0; }
        if (nb && nb.depth === 1) { lastChapterNo = nb.number; tableCounter = 0; figureCounter = 0; }
      }

      if (isHeadingLike(b)) {
        const nb = numbering[b.id];
        if (nb) {
          toc.push({
            number: nb.number,
            label: sectionLabel(b),
            depth: nb.depth,
            anchor: nb.anchor,
            page: pageOfBlock(pages, b.id),
          });
        }
      }

      if (b.kind === 'table') {
        tableCounter += 1;
        const prefix = lastChapterNo || '1';
        const cap = `Table ${prefix}.${tableCounter}`;
        tableCaptions[b.id] = cap;
        listOfTables.push({ caption: cap, title: b.title, page: pageOfBlock(pages, b.id) });
      }
      if (b.kind === 'chart') {
        figureCounter += 1;
        const prefix = lastChapterNo || '1';
        const cap = `Figure ${prefix}.${figureCounter}`;
        tableCaptions[b.id] = cap;
        listOfFigures.push({ caption: cap, title: b.title, page: pageOfBlock(pages, b.id) });
      }
    }

    // Running-header chapter label per page: the last chapter heading at/above
    // the top of each page.
    let runningChapter = '';
    for (const p of pages) {
      for (const bid of p.blocks) {
        const origId = bid.includes('#') ? bid.split('#')[0] : bid;
        const b = blocks.get(origId);
        if (b && b.kind === 'heading' && headingDepth(b) === 2) {
          const nb = numbering[b.id];
          runningChapter = nb ? `${nb.number} ${sectionLabel(b)}` : sectionLabel(b);
        }
      }
      chapterByPage[p.index] = runningChapter;
    }

    return { numbering, tableCaptions, toc, listOfTables, listOfFigures, chapterByPage };
  }, [order, blocks, pages]);
}
