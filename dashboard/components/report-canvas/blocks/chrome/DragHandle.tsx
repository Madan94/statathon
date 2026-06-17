'use client';
import { GripVertical } from 'lucide-react';
import { Z } from '../../engine/canvasTokens';

/* ═══════════════════════════════════════════════════════════════════
   DragHandle — the Notion-style grip in the left gutter of a block.

   This is the ONE place a drag starts, which keeps the block body free for
   click-to-type. Press and move to reorder (or move, when floating).
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  onPointerDown: (e: React.PointerEvent) => void;
  onPointerMove: (e: React.PointerEvent) => void;
  onPointerUp: (e: React.PointerEvent) => void;
  active?: boolean;
}

export function DragHandle({ onPointerDown, onPointerMove, onPointerUp, active }: Props) {
  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      title="Drag to move"
      className={`absolute -left-6 top-0 flex h-6 w-5 cursor-grab items-center justify-center rounded text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-500 active:cursor-grabbing ${active ? 'bg-slate-100 text-slate-500' : ''}`}
      style={{ zIndex: Z.dragHandle, touchAction: 'none' }}
    >
      <GripVertical className="h-3.5 w-3.5" />
    </div>
  );
}
