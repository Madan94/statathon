'use client';
import { useEffect, useRef } from 'react';
import { generatePhaseApi } from '@/lib/api';
import { CONTENT_W, CONTENT_H } from './paginationEngine';
import type { CanvasPage, PageBlock } from './useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   Layout persistence — the officer's free placement (x/y/w/h + page
   assignment) is autosaved to the backend stash and restored on mount,
   so the canvas layout survives reloads and feeds the renderer.

   • Restore runs ONCE after the generation queue has produced blocks
     (it re-applies saved x/y/w/h onto matching block ids).
   • Save is debounced; it serialises only the spatial fields (not the
     heavy content) so writes stay small.
   ═══════════════════════════════════════════════════════════════════ */

interface Params {
  templateId: string;
  signature: string;
  blocks: Map<string, PageBlock>;
  pages: CanvasPage[];
  /** Canonical document order; persisted so manual reorders survive a reload. */
  order: string[];
  setBlocks: (updater: (prev: Map<string, PageBlock>) => Map<string, PageBlock>) => void;
  setOrder: (updater: (prev: string[]) => string[]) => void;
  /** Re-derive pages from the (freshly restored) order + blocks. */
  repack: () => void;
}

const SAVE_DEBOUNCE_MS = 900;

/** Spatial fields we persist per block (presentation only). */
function spatialOf(b: PageBlock) {
  return { floating: b.floating, x: b.x, y: b.y, w: b.w, h: b.h, pageIndex: b.pageIndex };
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

export function useLayoutPersistence({ templateId, signature, blocks, pages, order, setBlocks, setOrder, repack }: Params) {
  const restored = useRef(false);
  const savedRef = useRef<Record<string, ReturnType<typeof spatialOf>>>({});
  const savedOrderRef = useRef<string[]>([]);
  const saveTimer = useRef<number | null>(null);

  // ── Restore once blocks exist ──────────────────────────────────────────
  useEffect(() => {
    if (restored.current || blocks.size === 0) return;
    restored.current = true;
    let cancelled = false;
    generatePhaseApi.getCanvasLayout(templateId, signature)
      .then(layout => {
        if (cancelled || !layout?.blocks) return;
        const saved = layout.blocks as Record<string, { floating?: boolean; x?: number; y?: number; w?: number; h?: number; pageIndex?: number }>;
        const savedOrder = Array.isArray(layout.order) ? layout.order : [];
        if (!Object.keys(saved).length && !savedOrder.length) return;
        savedRef.current = saved as Record<string, ReturnType<typeof spatialOf>>;
        savedOrderRef.current = savedOrder;
        setBlocks(prev => {
          const m = new Map(prev);
          for (const [id, s] of Object.entries(saved)) {
            const b = m.get(id);
            if (!b) continue;
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
            const present = new Set(curOrder);
            const reordered = savedOrder.filter(id => present.has(id));
            const inSaved = new Set(reordered);
            for (const id of curOrder) if (!inSaved.has(id)) reordered.push(id);
            return reordered;
          });
          repack();   // pages must be re-derived from the restored order
        }
      })
      .catch(() => { /* best-effort; no saved layout yet */ });
    return () => { cancelled = true; };
  }, [templateId, signature, blocks.size, setBlocks, setOrder, repack]);

  // ── Debounced autosave on spatial OR order change ──────────────────────
  useEffect(() => {
    if (!restored.current || blocks.size === 0) return;
    // Build the sparse spatial map; skip the save if nothing relevant changed.
    const spatial: Record<string, ReturnType<typeof spatialOf>> = {};
    for (const [id, b] of blocks) spatial[id] = spatialOf(b);
    const spatialSame = JSON.stringify(spatial) === JSON.stringify(savedRef.current);
    const orderSame = JSON.stringify(order) === JSON.stringify(savedOrderRef.current);
    if (spatialSame && orderSame) return;

    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      savedRef.current = spatial;
      savedOrderRef.current = [...order];
      generatePhaseApi.putCanvasLayout(templateId, signature, {
        blocks: spatial,
        pages: pages.map(p => ({ id: p.id, index: p.index, blocks: p.blocks })),
        order,
      }).catch(() => { /* best-effort */ });
    }, SAVE_DEBOUNCE_MS);

    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); };
  }, [templateId, signature, blocks, pages, order]);
}
