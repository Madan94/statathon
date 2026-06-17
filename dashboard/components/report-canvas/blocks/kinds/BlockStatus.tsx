'use client';
import { Loader2 } from 'lucide-react';
import type { PageBlock } from '../../engine/useCanvasState';

/* BlockStatus — the non-"done" lifecycle states for a block:
   generating shimmer · pending placeholder · error retry. */
interface Props {
  block: PageBlock;
  onGenerate?: (index: number) => void;
}

export function BlockStatus({ block, onGenerate }: Props) {
  if (block.status === 'generating') {
    return (
      <div className="rounded border border-blue-100 bg-blue-50/30 px-4 py-3">
        <div className="flex items-center gap-2">
          <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
          <span className="text-[10px] font-medium text-blue-600">{block.title}</span>
        </div>
        <div className="mt-2 space-y-1.5">
          <div className="h-2.5 w-full animate-pulse rounded bg-blue-100/60" />
          <div className="h-2.5 w-[85%] animate-pulse rounded bg-blue-100/40" />
        </div>
      </div>
    );
  }
  if (block.status === 'pending') {
    return (
      <div
        onClick={e => { e.stopPropagation(); onGenerate?.(block.index); }}
        className="flex cursor-pointer items-center justify-between rounded border border-dashed border-slate-300 bg-slate-50/50 px-4 py-3 transition-colors hover:border-blue-400 hover:bg-blue-50/30"
      >
        <span className="text-[11px] text-slate-500">{block.title}</span>
        <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-[9px] font-semibold text-blue-700">Generate</span>
      </div>
    );
  }
  // error
  return (
    <div
      onClick={e => { e.stopPropagation(); onGenerate?.(block.index); }}
      className="flex cursor-pointer items-center justify-between rounded border border-red-200 bg-red-50/50 px-4 py-2"
    >
      <span className="text-[10px] text-red-600">Failed: {block.title}</span>
      <span className="rounded bg-red-100 px-2 py-0.5 text-[9px] font-semibold text-red-700">Retry</span>
    </div>
  );
}
