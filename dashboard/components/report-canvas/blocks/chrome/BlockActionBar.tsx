'use client';
import { Copy, Trash2, Sparkles, MessageSquare, Flag, Move, Pin } from 'lucide-react';
import type { PageBlock } from '../../engine/useCanvasState';
import { Z } from '../../engine/canvasTokens';

/* ═══════════════════════════════════════════════════════════════════
   BlockActionBar — the floating toolbar shown above a selected block
   (Ask · Comment · Flag · Float/Pin · Duplicate · Delete).

   It sits ABOVE the block, left-aligned, on its own z-layer (Z.actionBar)
   which is higher than the resize handles — and crucially it no longer
   shares the top-right corner with the NE resize grip, so they can never
   overlap or steal each other's clicks.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  block: PageBlock;
  floating: boolean;
  flagged?: boolean;
  onAsk?: (block: PageBlock) => void;
  onComment?: (block: PageBlock) => void;
  onFlag?: (id: string) => void;
  onToggleFloat?: (id: string, floating: boolean) => void;
  onDuplicate?: (id: string) => void;
  onDelete?: (id: string) => void;
}

const stop = (e: React.PointerEvent) => e.stopPropagation();

export function BlockActionBar({ block, floating, flagged, onAsk, onComment, onFlag, onToggleFloat, onDuplicate, onDelete }: Props) {
  if (!onAsk && !onComment && !onFlag && !onToggleFloat && !onDuplicate && !onDelete) return null;
  return (
    <div
      className="absolute -top-9 left-0 flex items-center gap-0.5 rounded-md border border-slate-200 bg-white px-0.5 py-0.5 shadow-md"
      style={{ zIndex: Z.actionBar }}
    >
      {onAsk && (
        <button onPointerDown={stop} onClick={e => { e.stopPropagation(); onAsk(block); }}
          title="Ask the co-pilot about this" className="rounded p-1 text-indigo-500 hover:bg-indigo-50"><Sparkles className="h-3 w-3" /></button>
      )}
      {onComment && (
        <button onPointerDown={stop} onClick={e => { e.stopPropagation(); onComment(block); }}
          title="Comment" className="rounded p-1 text-slate-500 hover:bg-blue-50 hover:text-blue-600"><MessageSquare className="h-3 w-3" /></button>
      )}
      {onFlag && (
        <button onPointerDown={stop} onClick={e => { e.stopPropagation(); onFlag(block.id); }}
          title={flagged ? 'Clear attention flag' : 'Flag for attention'}
          className={`rounded p-1 ${flagged ? 'text-amber-500 hover:bg-amber-50' : 'text-slate-500 hover:bg-amber-50 hover:text-amber-600'}`}><Flag className="h-3 w-3" /></button>
      )}
      {onToggleFloat && (
        <button onPointerDown={stop} onClick={e => { e.stopPropagation(); onToggleFloat(block.id, !floating); }}
          title={floating ? 'Pin back into the document flow' : 'Float freely (overlay)'}
          className={`rounded p-1 ${floating ? 'text-blue-600 hover:bg-blue-50' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}>
          {floating ? <Pin className="h-3 w-3" /> : <Move className="h-3 w-3" />}
        </button>
      )}
      {onDuplicate && (
        <button onPointerDown={stop} onClick={e => { e.stopPropagation(); onDuplicate(block.id); }}
          title="Duplicate" className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"><Copy className="h-3 w-3" /></button>
      )}
      {onDelete && (
        <button onPointerDown={stop} onClick={e => { e.stopPropagation(); onDelete(block.id); }}
          title="Delete" className="rounded p-1 text-slate-500 hover:bg-red-50 hover:text-red-600"><Trash2 className="h-3 w-3" /></button>
      )}
    </div>
  );
}
