'use client';
import { ChevronLeft, ChevronRight } from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════
   PageNavigator — ◄ Page N of M ► navigation bar below the page.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  current: number; // 0-indexed
  total: number;
  onPrev: () => void;
  onNext: () => void;
  onAddPage: () => void;
}

export function PageNavigator({ current, total, onPrev, onNext, onAddPage }: Props) {
  return (
    <div className="flex items-center justify-center gap-3 py-3">
      <button
        onClick={onPrev}
        disabled={current <= 0}
        className="flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>

      <span className="text-[11px] font-medium tabular-nums text-slate-600">
        Page {current + 1} of {total}
      </span>

      <button
        onClick={onNext}
        disabled={current >= total - 1}
        className="flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </button>

      <span className="mx-2 h-4 w-px bg-slate-200" />

      <button
        onClick={onAddPage}
        className="flex items-center gap-1 rounded-full border border-dashed border-slate-300 bg-white px-3 py-1 text-[10px] font-medium text-slate-500 transition-all hover:border-blue-400 hover:text-blue-600 hover:bg-blue-50"
      >
        <span className="text-sm">+</span> Add Page
      </button>
    </div>
  );
}
