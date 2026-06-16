'use client';
import { useCallback, useRef, useState } from 'react';
import { packBlocks, PAGE_BUDGET } from './paginationEngine';

/* ═══════════════════════════════════════════════════════════════════
   Canvas State — central state for the entire report canvas.
   ═══════════════════════════════════════════════════════════════════ */

export interface PageBlock {
  id: string;
  index: number;
  kind: 'heading' | 'narrative' | 'table' | 'chart' | 'metric' | 'key_finding' | 'source_note' | 'divider';
  title: string;
  content: string;
  tableData?: Record<string, unknown>;
  metricValue?: string;
  metricUnit?: string;
  sectionPath: string[];
  status: 'pending' | 'generating' | 'done' | 'error';
  pageIndex: number; // which page this block lives on
  // Free-positioning (Canva-style). Unset = flows in the normal stack; once a
  // block is dragged it gets absolute coordinates (unscaled px, relative to the
  // page content area). ``w``/``h`` are the block's width/height (unscaled px);
  // ``h`` is optional — unset means auto height (content-driven).
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  /** Set by the packer when this is a table-split part: the original block id.
   *  The renderer uses it with `tableSplits` to show only that part's rows. */
  _origId?: string;
}

export interface CanvasPage {
  id: string;
  index: number;
  blocks: string[]; // block IDs on this page
}

export type Phase = 'init' | 'ready' | 'generating' | 'paused' | 'complete';
export type Panel = 'left' | 'right' | null;

export interface QueueItem {
  index: number;
  plan_id: string;
  question_id: string;
  component_type: string;
  title: string;
  section_path: string[];
  status: string;
}

export function useCanvasState() {
  const [phase, setPhase] = useState<Phase>('init');
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [blocks, setBlocks] = useState<Map<string, PageBlock>>(new Map());
  const [pages, setPages] = useState<CanvasPage[]>([{ id: 'page-1', index: 0, blocks: [] }]);
  /** Canonical block order (flow sequence). The packer derives `pages` from
   *  this + measured heights, so pagination is height-aware, not count-based. */
  const [order, setOrder] = useState<string[]>([]);
  /** Table split parts produced by the packer (origId → parts), for the renderer. */
  const [tableSplits, setTableSplits] = useState<Record<string, import('./paginationEngine').TableSplitPart[]>>({});
  const [currentPage, setCurrentPage] = useState(0);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [generating, setGenerating] = useState(false);
  /** Live typography metrics for the packer so page assignment tracks the
   *  document type-scale / line-height (kept in a ref to avoid re-creating
   *  repackFrom; CanvasShell pushes updates via setLayoutMetrics). */
  const layoutMetricsRef = useRef<{ scale: number; lineHeight: number }>({ scale: 1, lineHeight: 1.7 });

  // ── Undo/redo history (U5) ──────────────────────────────────────────────
  // Each snapshot captures the canonical content (blocks + order). Pages are
  // re-derived by the packer on restore, so we don't store them.
  type Snapshot = { blocks: Map<string, PageBlock>; order: string[] };
  const undoStack = useRef<Snapshot[]>([]);
  const redoStack = useRef<Snapshot[]>([]);
  const [historyVer, setHistoryVer] = useState(0); // bump to refresh canUndo/canRedo

  const snapshot = useCallback((b: Map<string, PageBlock>, o: string[]) => {
    undoStack.current.push({ blocks: new Map(b), order: [...o] });
    if (undoStack.current.length > 50) undoStack.current.shift();
    redoStack.current = [];
    setHistoryVer(v => v + 1);
  }, []);

  const togglePanel = useCallback((p: Panel) => {
    setPanel(prev => prev === p ? null : p);
  }, []);

  /** Re-derive pages from the canonical order using the height-aware packer.
   *  Pass the freshest blocks map (functional updates may race the state). */
  const repackFrom = useCallback((blockMap: Map<string, PageBlock>, ord: string[]) => {
    const ordered = ord.map(id => blockMap.get(id)).filter(Boolean) as PageBlock[];
    // Only flow blocks WITHOUT manual coordinates participate in packing; a
    // dragged block keeps its absolute position and is pinned to its page.
    const flow = ordered.filter(b => b.x === undefined || b.y === undefined);
    const pinned = ordered.filter(b => b.x !== undefined && b.y !== undefined);
    const { pages: packed, splits } = packBlocks(flow, PAGE_BUDGET, layoutMetricsRef.current);

    const nextPages: CanvasPage[] = packed.length
      ? packed.map(p => ({ id: `page-${p.index + 1}`, index: p.index, blocks: [...p.blocks] }))
      : [{ id: 'page-1', index: 0, blocks: [] }];

    // Re-attach pinned blocks to their stored pageIndex (clamped).
    for (const b of pinned) {
      const tgt = Math.min(b.pageIndex ?? 0, nextPages.length - 1);
      if (tgt >= 0 && !nextPages[tgt].blocks.includes(b.id)) nextPages[tgt].blocks.push(b.id);
    }

    // Stamp each flow block's pageIndex so other views stay consistent.
    setBlocks(prev => {
      const m = new Map(prev);
      packed.forEach(p => p.blocks.forEach(bid => {
        const origId = bid.includes('#') ? bid.split('#')[0] : bid;
        const b = m.get(origId);
        if (b) m.set(origId, { ...b, pageIndex: p.index });
      }));
      return m;
    });
    setTableSplits(splits);
    setPages(nextPages);
  }, []);

  /** Public: repack using current state (after edits that change heights). */
  const repack = useCallback(() => {
    setOrder(ord => { setBlocks(bm => { repackFrom(bm, ord); return bm; }); return ord; });
  }, [repackFrom]);

  /** Push live typography metrics (type-scale + line-height) and repack so page
   *  assignment stays in sync with what the renderer paints. No-op when nothing
   *  changed, so it's safe to call from a typography effect. */
  const setLayoutMetrics = useCallback((scale: number, lineHeight: number) => {
    const m = layoutMetricsRef.current;
    if (m.scale === scale && m.lineHeight === lineHeight) return;
    layoutMetricsRef.current = { scale, lineHeight };
    repack();
  }, [repack]);

  /** Undo the last content mutation (U5). Restores blocks + order, repacks. */
  const undo = useCallback(() => {
    const snap = undoStack.current.pop();
    if (!snap) return;
    setBlocks(curB => {
      setOrder(curO => {
        redoStack.current.push({ blocks: new Map(curB), order: [...curO] });
        repackFrom(snap.blocks, snap.order);
        return snap.order;
      });
      return snap.blocks;
    });
    setHistoryVer(v => v + 1);
  }, [repackFrom]);

  /** Redo the last undone mutation (U5). */
  const redo = useCallback(() => {
    const snap = redoStack.current.pop();
    if (!snap) return;
    setBlocks(curB => {
      setOrder(curO => {
        undoStack.current.push({ blocks: new Map(curB), order: [...curO] });
        repackFrom(snap.blocks, snap.order);
        return snap.order;
      });
      return snap.blocks;
    });
    setHistoryVer(v => v + 1);
  }, [repackFrom]);

  const addPage = useCallback(() => {
    setPages(prev => {
      const newPage: CanvasPage = { id: `page-${prev.length + 1}`, index: prev.length, blocks: [] };
      return [...prev, newPage];
    });
  }, []);

  const goToPage = useCallback((idx: number) => {
    setCurrentPage(Math.max(0, Math.min(idx, pages.length - 1)));
  }, [pages.length]);

  const nextPage = useCallback(() => goToPage(currentPage + 1), [currentPage, goToPage]);
  const prevPage = useCallback(() => goToPage(currentPage - 1), [currentPage, goToPage]);

  const addBlockToPage = useCallback((block: PageBlock, pageIdx?: number) => {
    const targetPage = pageIdx ?? currentPage;
    setBlocks(prev => {
      const m = new Map(prev).set(block.id, { ...block, pageIndex: targetPage });
      setOrder(prevOrder => {
        const ord = prevOrder.includes(block.id) ? prevOrder : [...prevOrder, block.id];
        repackFrom(m, ord);
        return ord;
      });
      return m;
    });
  }, [currentPage, repackFrom]);

  /** Append a block to the canonical order; the height-aware packer assigns it
   *  to the right page (auto-creating pages as the budget fills). Replaces the
   *  old count-based behaviour. The `maxPerPage` arg is ignored (kept for API
   *  compatibility with existing callers). */
  const appendBlockAuto = useCallback((block: PageBlock, _maxPerPage?: number) => {
    void _maxPerPage;
    setBlocks(prev => {
      const m = new Map(prev).set(block.id, { ...block });
      setOrder(prevOrder => {
        const ord = prevOrder.includes(block.id) ? prevOrder : [...prevOrder, block.id];
        repackFrom(m, ord);
        return ord;
      });
      return m;
    });
  }, [repackFrom]);

  const updateBlock = useCallback((id: string, updates: Partial<PageBlock>) => {
    setBlocks(prev => {
      const m = new Map(prev);
      const existing = m.get(id);
      if (existing) m.set(id, { ...existing, ...updates });
      // Height-affecting changes (content/table/status) need a repack.
      const reflow = 'content' in updates || 'tableData' in updates || 'status' in updates || 'metricValue' in updates;
      if (reflow) setOrder(ord => { repackFrom(m, ord); return ord; });
      return m;
    });
  }, [repackFrom]);

  const removeBlock = useCallback((id: string) => {
    setBlocks(prev => {
      const m = new Map(prev); m.delete(id);
      setOrder(prevOrder => {
        snapshot(prev, prevOrder);            // history (U5)
        const ord = prevOrder.filter(bid => bid !== id);
        repackFrom(m, ord);
        return ord;
      });
      return m;
    });
  }, [repackFrom, snapshot]);

  /** Reposition a block to absolute coordinates (Canva-style free placement). */
  const moveBlock = useCallback((id: string, x: number, y: number, w?: number) => {
    setBlocks(prev => {
      setOrder(o => { snapshot(prev, o); return o; });   // history (U5)
      const m = new Map(prev);
      const b = m.get(id);
      if (b) m.set(id, { ...b, x, y, ...(w !== undefined ? { w } : {}) });
      return m;
    });
  }, [snapshot]);

  /** Resize a block (Canva-style). May also shift x/y when resizing from a
   *  top/left handle so the opposite edge stays anchored. */
  const resizeBlock = useCallback((id: string, patch: { w?: number; h?: number; x?: number; y?: number }) => {
    setBlocks(prev => {
      setOrder(o => { snapshot(prev, o); return o; });   // history (U5)
      const m = new Map(prev);
      const b = m.get(id);
      if (b) m.set(id, { ...b, ...patch });
      return m;
    });
  }, [snapshot]);

  const getPageBlocks = useCallback((pageIdx: number): PageBlock[] => {
    const page = pages[pageIdx];
    if (!page) return [];
    // Page block ids may be split-part ids (origId#partN). Resolve to the
    // underlying block; the renderer uses tableSplits to window the rows.
    return page.blocks
      .map(id => {
        const origId = id.includes('#') ? id.split('#')[0] : id;
        const b = blocks.get(origId);
        if (!b) return null;
        // Carry the part id so the renderer can look up its row window.
        return id === origId ? b : ({ ...b, id, _origId: origId } as PageBlock & { _origId: string });
      })
      .filter(Boolean) as PageBlock[];
  }, [pages, blocks]);

  const currentPageBlocks = getPageBlocks(currentPage);
  const selectedBlock = selectedBlockId ? blocks.get(selectedBlockId) || null : null;
  const totalBlocks = blocks.size;
  const doneBlocks = Array.from(blocks.values()).filter(b => b.status === 'done').length;
  const progress = totalBlocks > 0 ? Math.round((doneBlocks / totalBlocks) * 100) : 0;

  return {
    phase, setPhase, queue, setQueue, blocks, pages, currentPage, selectedBlockId,
    panel, generating, setGenerating, togglePanel, addPage, goToPage, nextPage, prevPage,
    addBlockToPage, appendBlockAuto, updateBlock, removeBlock, moveBlock, resizeBlock, getPageBlocks, currentPageBlocks,
    selectedBlock, setSelectedBlockId, totalBlocks, doneBlocks, progress, setPages, setBlocks,
    order, setOrder, repack, setLayoutMetrics, tableSplits,
    undo, redo, canUndo: undoStack.current.length > 0, canRedo: redoStack.current.length > 0, historyVer,
  };
}
