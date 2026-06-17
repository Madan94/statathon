'use client';
import { Z } from '../../engine/canvasTokens';

/* ═══════════════════════════════════════════════════════════════════
   InsertionCaret — the horizontal blue line that shows where a dragged
   block will land when reordering the document flow (Word / Notion style).
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  /** Y offset (unscaled px) within the content area where the block will drop. */
  y: number;
}

export function InsertionCaret({ y }: Props) {
  return (
    <div
      className="pointer-events-none absolute left-0 right-0 flex items-center"
      style={{ top: y - 1, zIndex: Z.guides }}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
      <span className="h-0.5 flex-1 rounded-full bg-blue-500" />
      <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
    </div>
  );
}
