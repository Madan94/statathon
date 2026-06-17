'use client';
import { useCallback, useEffect, useRef } from 'react';
import { generatePhaseApi } from '@/lib/api';
import { CONTENT_W, CONTENT_H } from './paginationEngine';
import type { CanvasPage, PageBlock } from './useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   Layout persistence — the officer's free placement (x/y/w/h + page
   assignment) is autosaved to the backend stash and restored on mount,
   so the canvas layout survives reloads and feeds the renderer.

   • Restore runs ONCE after the generation queue has produced blocks
     (it re-applies saved x/y/w/h onto matching block ids).
   • Manual/generated canvas-only blocks are persisted with their content too,
     because they are not recreated by the backend generation queue.
   ═══════════════════════════════════════════════════════════════════ */

interface Params {
  templateId: string;
  signature: string;
  draftId?: string | null;
  enabled?: boolean;
  blocks: Map<string, PageBlock>;
  pages: CanvasPage[];
  /** Canonical document order; persisted so manual reorders survive a reload. */
  order: string[];
  setBlocks: (updater: (prev: Map<string, PageBlock>) => Map<string, PageBlock>) => void;
  setOrder: (updater: (prev: string[]) => string[]) => void;
  /** Re-derive pages from the (freshly restored) order + blocks. */
  repack: () => void;
  /** Fires after the layout/draft restore attempt finishes (success or empty). */
  onRestored?: (info: { savedBlockCount: number; restoredCanvasOwnedBlocks: number }) => void;
}

const SAVE_DEBOUNCE_MS = 900;

/** Spatial fields we persist per block (presentation only). */
function spatialOf(b: PageBlock) {
  return { floating: b.floating, x: b.x, y: b.y, w: b.w, h: b.h, pageIndex: b.pageIndex };
}

type PersistedBlock = ReturnType<typeof spatialOf> & Partial<PageBlock>;

function isCanvasOwnedBlock(b: PageBlock): boolean {
  return b.index < 0 || b.id.startsWith('sectiongen-') || b.id.startsWith('block-manual-') || b.id.startsWith('block-copy-');
}

function persistableOf(b: PageBlock): PersistedBlock {
  const spatial = spatialOf(b);
  if (!isCanvasOwnedBlock(b)) return spatial;
  return {
    ...spatial,
    id: b.id,
    index: b.index,
    kind: b.kind,
    title: b.title,
    content: b.content,
    tableData: b.tableData,
    metricValue: b.metricValue,
    metricUnit: b.metricUnit,
    sectionPath: b.sectionPath,
    status: b.status,
    _origId: b._origId,
  };
}

function isPersistedCanvasOwnedBlock(s: PersistedBlock): s is PersistedBlock & Pick<PageBlock, 'id' | 'kind' | 'title' | 'content' | 'sectionPath' | 'status'> {
  return typeof s.id === 'string' && typeof s.kind === 'string' && typeof s.title === 'string' && Array.isArray(s.sectionPath);
}

/** Full-width structural blocks should never be pinned narrow — a saved table
 *  at 40px wide is corruption, not intent. They heal back to the flow. */
const STRUCTURAL = new Set<PageBlock['kind']>(['table', 'heading', 'divider']);

/** Decide whether a saved pin is trustworthy. Implausible saves (NaN, off-page,
 *  degenerate sizes, a hairline-wide table) are rejected so the block flows. */
function pinIsPlausible(kind: PageBlock['kind'], s: { x?: number; y?: number; w?: number; h?: number }): boolean {
  const fin = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
  if (!fin(s.x) || !fin(s.y) || !fin(s.w) || !fin(s.h)) return false;
  if (s.x < 0 || s.y < 0 || s.x >= CONTENT_W || s.y >= CONTENT_H) return false;
  const minW = STRUCTURAL.has(kind) ? Math.round(CONTENT_W * 0.5) : 60;
  if (s.w < minW || s.h < 24) return false;
  if (s.w > CONTENT_W * 1.2 || s.h > CONTENT_H * 1.5) return false;
  return true;
}

export function useLayoutPersistence({ templateId, signature, draftId, enabled = true, blocks, pages, order, setBlocks, setOrder, repack, onRestored }: Params) {
  const restored = useRef(false);
  const restoredKey = useRef('');
  const savedRef = useRef<Record<string, PersistedBlock>>({});
  const savedOrderRef = useRef<string[]>([]);
  const saveTimer = useRef<number | null>(null);

  const useNamedDraft = Boolean(draftId && draftId !== '__legacy__');

  const loadLayout = useCallback(() => useNamedDraft
    ? generatePhaseApi.getCanvasDraftLayout(templateId, signature, draftId)
    : generatePhaseApi.getCanvasLayout(templateId, signature),
  [draftId, signature, templateId, useNamedDraft]);

  const saveLayout = useCallback((body: { blocks: Record<string, unknown>; pages: Array<Record<string, unknown>>; order: string[]; updatedAt?: string }) => useNamedDraft
    ? generatePhaseApi.putCanvasDraftLayout(templateId, signature, draftId, body)
    : generatePhaseApi.putCanvasLayout(templateId, signature, body),
  [draftId, signature, templateId, useNamedDraft]);

  // ── Restore once blocks exist ──────────────────────────────────────────
  useEffect(() => {
    if (!enabled) return;
    const key = `${templateId}::${signature}::${draftId || 'legacy'}`;
    if (restoredKey.current !== key) {
      restored.current = false;
      restoredKey.current = key;
      savedRef.current = {};
      savedOrderRef.current = [];
    }
    if (restored.current) return;
    restored.current = true;
    let cancelled = false;
    loadLayout()
      .then(layout => {
        if (cancelled || !layout?.blocks) return;
        const saved = layout.blocks as Record<string, PersistedBlock>;
        const savedOrder = Array.isArray(layout.order) ? layout.order : [];
        if (!Object.keys(saved).length && !savedOrder.length) {
          onRestored?.({ savedBlockCount: 0, restoredCanvasOwnedBlocks: 0 });
          return;
        }
        let restoredCanvasOwnedBlocks = 0;
        savedRef.current = saved;
        savedOrderRef.current = savedOrder;
        setBlocks(prev => {
          const m = new Map(prev);
          for (const [id, b] of Array.from(m.entries())) {
            if (isCanvasOwnedBlock(b) && !(id in saved)) m.delete(id);
          }
          for (const [id, s] of Object.entries(saved)) {
            const b = m.get(id);
            if (!b) {
              if (isPersistedCanvasOwnedBlock(s)) {
                restoredCanvasOwnedBlocks += 1;
                m.set(id, {
                  id,
                  index: typeof s.index === 'number' ? s.index : -1,
                  kind: s.kind,
                  title: s.title,
                  content: s.content || '',
                  tableData: s.tableData,
                  metricValue: s.metricValue,
                  metricUnit: s.metricUnit,
                  sectionPath: s.sectionPath,
                  status: s.status || 'done',
                  pageIndex: typeof s.pageIndex === 'number' ? s.pageIndex : 0,
                  floating: s.floating,
                  x: s.x,
                  y: s.y,
                  w: s.w,
                  h: s.h,
                  _origId: s._origId,
                } as PageBlock);
              }
              continue;
            }
            if (s.floating && pinIsPlausible(b.kind, s)) {
              // Restore an explicit floating overlay (free placement).
              m.set(id, {
                ...b, floating: true,
                x: s.x, y: s.y, w: s.w, h: s.h,
                ...(typeof s.pageIndex === 'number' && Number.isFinite(s.pageIndex) && s.pageIndex >= 0 ? { pageIndex: s.pageIndex } : {}),
              });
            } else {
              // Flowing block (also the migration path for old pins): restore a
              // custom WIDTH, plus an explicit HEIGHT only for figures — never
              // re-pin, so the document-first packer lays it out.
              const next: PageBlock = { ...b };
              if (typeof s.w === 'number' && Number.isFinite(s.w) && s.w >= 60) next.w = s.w;
              if (typeof s.h === 'number' && Number.isFinite(s.h) && s.h >= 24 && (b.kind === 'chart' || b.kind === 'table')) next.h = s.h;
              m.set(id, next);
            }
          }
          return m;
        });
        // Re-apply the saved document order: keep saved ids that still exist (in
        // saved sequence), then append any new ids not present in the save.
        if (savedOrder.length) {
          setOrder(curOrder => {
            const restorable = Object.entries(saved)
              .filter(([, s]) => isPersistedCanvasOwnedBlock(s))
              .map(([id]) => id);
            const present = new Set([...curOrder, ...restorable]);
            const reordered = savedOrder.filter(id => present.has(id));
            const inSaved = new Set(reordered);
            for (const id of curOrder) if (!inSaved.has(id)) reordered.push(id);
            return reordered;
          });
          repack();   // pages must be re-derived from the restored order
        }
        onRestored?.({
          savedBlockCount: Object.keys(saved).length,
          restoredCanvasOwnedBlocks,
        });
      })
      .catch(() => { onRestored?.({ savedBlockCount: 0, restoredCanvasOwnedBlocks: 0 }); });
    return () => { cancelled = true; };
  }, [enabled, templateId, signature, draftId, setBlocks, setOrder, repack, onRestored, loadLayout]);

  // ── Debounced autosave on spatial OR order change ──────────────────────
  useEffect(() => {
    if (!enabled) return;
    if (!restored.current || blocks.size === 0) return;
    // Build the sparse spatial map; skip the save if nothing relevant changed.
    const spatial: Record<string, PersistedBlock> = {};
    for (const [id, b] of blocks) spatial[id] = persistableOf(b);
    const spatialSame = JSON.stringify(spatial) === JSON.stringify(savedRef.current);
    const orderSame = JSON.stringify(order) === JSON.stringify(savedOrderRef.current);
    if (spatialSame && orderSame) return;

    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      savedRef.current = spatial;
      savedOrderRef.current = [...order];
      saveLayout({
        blocks: spatial,
        pages: pages.map(p => ({ id: p.id, index: p.index, blocks: p.blocks })),
        order,
      }).catch(() => { /* best-effort */ });
    }, SAVE_DEBOUNCE_MS);

    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); };
  }, [enabled, templateId, signature, draftId, blocks, pages, order, saveLayout]);
}
