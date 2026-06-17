'use client';
import { useLayoutEffect, useRef } from 'react';

/* ═══════════════════════════════════════════════════════════════════
   useFlip — smooth FLIP (First-Last-Invert-Play) transitions for the
   flowing blocks inside a container.

   On every commit it measures each block's position RELATIVE to the
   container (scroll-invariant), compares to the previous commit, and
   plays a short translate animation for any block that moved. This makes
   reorders and reflows glide instead of jumping — like Word / Notion.

   • Container-relative coords → scrolling never triggers a false glide.
   • Large deltas (page jumps / zoom changes) are skipped.
   • Absolute (floating) blocks are ignored — they own their own motion.
   ═══════════════════════════════════════════════════════════════════ */

const DURATION = 200;
const EASING = 'cubic-bezier(0.2, 0, 0, 1)';
const MAX_DX = 600;    // skip implausible horizontal jumps (zoom)
const MAX_DY = 1200;   // skip cross-page jumps

export function useFlip(containerRef: React.RefObject<HTMLElement | null>, enabled = true) {
  const prev = useRef<Map<string, { left: number; top: number }>>(new Map());

  useLayoutEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const rootRect = root.getBoundingClientRect();
    const nodes = Array.from(root.querySelectorAll<HTMLElement>('[data-block-id]'))
      .filter(el => el.style.position !== 'absolute');

    const next = new Map<string, { left: number; top: number }>();
    for (const el of nodes) {
      const id = el.dataset.blockId;
      if (!id) continue;
      const r = el.getBoundingClientRect();
      next.set(id, { left: r.left - rootRect.left, top: r.top - rootRect.top });
    }

    if (enabled && prev.current.size && typeof Element.prototype.animate === 'function') {
      for (const el of nodes) {
        const id = el.dataset.blockId;
        if (!id) continue;
        const before = prev.current.get(id);
        const after = next.get(id);
        if (!before || !after) continue;          // newly added → don't animate
        const dx = before.left - after.left;
        const dy = before.top - after.top;
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
        if (Math.abs(dx) > MAX_DX || Math.abs(dy) > MAX_DY) continue;
        el.animate(
          [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'translate(0, 0)' }],
          { duration: DURATION, easing: EASING },
        );
      }
    }
    prev.current = next;
  });   // run on every commit so positions never go stale
}
