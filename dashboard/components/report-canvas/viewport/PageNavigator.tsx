'use client';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════
   PageNavigator — Elegant page dots + arrows + add page.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  current: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  onAddPage: () => void;
  onGoToPage: (idx: number) => void;
}

export function PageNavigator({ current, total, onPrev, onNext, onAddPage, onGoToPage }: Props) {
  return (
    <div className="flex items-center justify-center gap-1 py-2">
      <button onClick={onPrev} disabled={current <= 0}
        className="flex h-6 w-6 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700 disabled:opacity-20 disabled:cursor-not-allowed">
        <ChevronLeft className="h-4 w-4" />
      </button>

      {/* Page number buttons */}
      <div className="flex items-center gap-1 px-2">
        {Array.from({ length: Math.min(total, 9) }, (_, i) => {
          const pageIdx = total <= 9 ? i : (current <= 4 ? i : current >= total - 5 ? total - 9 + i : current - 4 + i);
          return (
            <button key={pageIdx} onClick={() => onGoToPage(pageIdx)}
              className={`flex h-6 min-w-[24px] items-center justify-center rounded text-[9px] font-semibold tabular-nums transition-all ${
                pageIdx === current ? 'bg-blue-600 text-white shadow-sm scale-110' : 'text-slate-500 hover:bg-slate-200'
              }`}>
              {pageIdx + 1}
            </button>
          );
        })}
      </div>

      <button onClick={onNext} disabled={current >= total - 1}
        className="flex h-6 w-6 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700 disabled:opacity-20 disabled:cursor-not-allowed">
        <ChevronRight className="h-4 w-4" />
      </button>

      <span className="mx-2 h-4 w-px bg-slate-200" />

      <button onClick={onAddPage}
        className="flex h-6 w-6 items-center justify-center rounded border border-dashed border-slate-300 text-slate-400 transition-all hover:border-blue-400 hover:text-blue-600 hover:bg-blue-50">
        <Plus className="h-3 w-3" />
      </button>

      <span className="ml-3 text-[8px] text-slate-300">Ctrl+← → to navigate</span>
    </div>
  );
}
