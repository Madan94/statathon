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
  setBlocks: (updater: (prev: Map<string, PageBlock>) => Map<string, PageBlock>) => void;
}

const SAVE_DEBOUNCE_MS = 900;

/** Spatial fields we persist per block (presentation only). */
function spatialOf(b: PageBlock) {
  return { x: b.x, y: b.y, w: b.w, h: b.h, pageIndex: b.pageIndex };
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

export function useLayoutPersistence({ templateId, signature, blocks, pages, setBlocks }: Params) {
  const restored = useRef(false);
  const savedRef = useRef<Record<string, ReturnType<typeof spatialOf>>>({});
  const saveTimer = useRef<number | null>(null);

  // ── Restore once blocks exist ──────────────────────────────────────────
  useEffect(() => {
    if (restored.current || blocks.size === 0) return;
    restored.current = true;
    let cancelled = false;
    generatePhaseApi.getCanvasLayout(templateId, signature)
      .then(layout => {
        if (cancelled || !layout?.blocks) return;
        const saved = layout.blocks as Record<string, { x?: number; y?: number; w?: number; h?: number; pageIndex?: number }>;
        if (!Object.keys(saved).length) return;
        savedRef.current = saved as Record<string, ReturnType<typeof spatialOf>>;
        setBlocks(prev => {
          const m = new Map(prev);
          for (const [id, s] of Object.entries(saved)) {
            const b = m.get(id);
            if (!b) continue;
            // Self-heal corrupt layouts: only re-pin a block when the saved
            // position is plausible; otherwise leave it in the flow so the
            // height-aware packer lays it out (fixes tables stuck at 40×20).
            if (pinIsPlausible(b.kind, s)) {
              m.set(id, {
                ...b,
                x: s.x, y: s.y, w: s.w, h: s.h,
                ...(typeof s.pageIndex === 'number' && Number.isFinite(s.pageIndex) && s.pageIndex >= 0 ? { pageIndex: s.pageIndex } : {}),
              });
            }
            // else: discard the bad pin — block flows naturally on repack.
          }
          return m;
        });
      })
      .catch(() => { /* best-effort; no saved layout yet */ });
    return () => { cancelled = true; };
  }, [templateId, signature, blocks.size, setBlocks]);

  // ── Debounced autosave on spatial change ───────────────────────────────
  useEffect(() => {
    if (!restored.current || blocks.size === 0) return;
    // Build the sparse spatial map; skip the save if nothing spatial changed.
    const spatial: Record<string, ReturnType<typeof spatialOf>> = {};
    for (const [id, b] of blocks) spatial[id] = spatialOf(b);
    if (JSON.stringify(spatial) === JSON.stringify(savedRef.current)) return;

    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      savedRef.current = spatial;
      generatePhaseApi.putCanvasLayout(templateId, signature, {
        blocks: spatial,
        pages: pages.map(p => ({ id: p.id, index: p.index, blocks: p.blocks })),
      }).catch(() => { /* best-effort */ });
    }, SAVE_DEBOUNCE_MS);

    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); };
  }, [templateId, signature, blocks, pages]);
}
