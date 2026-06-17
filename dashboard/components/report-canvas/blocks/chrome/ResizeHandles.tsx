'use client';
import type { HandleDir } from '../../engine/canvasTokens';
import { HANDLE_SIZE, HANDLE_HIT_PAD, Z } from '../../engine/canvasTokens';

/* ═══════════════════════════════════════════════════════════════════
   ResizeHandles — the square grips on a selected block.

   • Only the edges a block actually supports are rendered (width-only for
     flowing text, all eight for figures / floating blocks).
   • Each grip has a small VISIBLE dot but a much larger INVISIBLE hit area
     (padding) so it is easy to grab — fixing the "2px target" friction.
   ═══════════════════════════════════════════════════════════════════ */

// Each grip is positioned to a corner/edge and then translated by half its
// own size so its CENTRE lands exactly on the block edge. Left/top edges
// translate negative; right/bottom translate positive.
const HANDLE_META: Record<HandleDir, { cls: string; cursor: string }> = {
  nw: { cls: 'left-0  top-0    -translate-x-1/2 -translate-y-1/2', cursor: 'nwse-resize' },
  n:  { cls: 'left-1/2 top-0   -translate-x-1/2 -translate-y-1/2', cursor: 'ns-resize' },
  ne: { cls: 'right-0 top-0     translate-x-1/2 -translate-y-1/2', cursor: 'nesw-resize' },
  e:  { cls: 'right-0 top-1/2   translate-x-1/2 -translate-y-1/2', cursor: 'ew-resize' },
  se: { cls: 'right-0 bottom-0  translate-x-1/2  translate-y-1/2', cursor: 'nwse-resize' },
  s:  { cls: 'left-1/2 bottom-0 -translate-x-1/2  translate-y-1/2', cursor: 'ns-resize' },
  sw: { cls: 'left-0  bottom-0 -translate-x-1/2  translate-y-1/2', cursor: 'nesw-resize' },
  w:  { cls: 'left-0  top-1/2  -translate-x-1/2 -translate-y-1/2', cursor: 'ew-resize' },
};

interface Props {
  edges: HandleDir[];
  onResizeDown: (e: React.PointerEvent, dir: HandleDir) => void;
  onResizeMove: (e: React.PointerEvent) => void;
  onResizeUp: (e: React.PointerEvent) => void;
}

export function ResizeHandles({ edges, onResizeDown, onResizeMove, onResizeUp }: Props) {
  return (
    <>
      {edges.map(dir => {
        const meta = HANDLE_META[dir];
        return (
          <div
            key={dir}
            onPointerDown={e => onResizeDown(e, dir)}
            onPointerMove={onResizeMove}
            onPointerUp={onResizeUp}
            // Outer box is the (large) hit target, centred on the edge via the
            // 1/2 translate. The visible dot sits centred inside it.
            className={`absolute flex items-center justify-center ${meta.cls}`}
            style={{ padding: HANDLE_HIT_PAD, cursor: meta.cursor, zIndex: Z.resizeHandles }}
          >
            <div
              className="rounded-[2px] border border-blue-500 bg-white shadow-sm"
              style={{ width: HANDLE_SIZE, height: HANDLE_SIZE }}
            />
          </div>
        );
      })}
    </>
  );
}
