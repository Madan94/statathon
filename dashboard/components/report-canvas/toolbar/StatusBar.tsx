'use client';
import { Check, Loader2, MapPin } from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════
   StatusBar (U3) — thin bottom strip filling previously-empty space.
   Shows: current section · page x/y · word & figure counts · save state.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  sectionLabel?: string;
  pageNumber: number;     // 1-based, including front matter
  totalPages: number;
  wordCount: number;
  tableCount: number;
  figureCount: number;
  saveState: 'saved' | 'saving' | 'idle';
}

export function StatusBar({ sectionLabel, pageNumber, totalPages, wordCount, tableCount, figureCount, saveState }: Props) {
  return (
    <div className="flex h-8 shrink-0 items-center justify-between border-t border-slate-200 bg-slate-50 px-4 text-[11px] text-slate-500">
      <div className="flex min-w-0 items-center gap-3">
        {sectionLabel && (
          <span className="flex min-w-0 items-center gap-1 truncate font-medium text-slate-700"><MapPin className="h-3 w-3 shrink-0 text-blue-500" /> <span className="truncate">{sectionLabel}</span></span>
        )}
        <span className="tabular-nums">Page {pageNumber} / {totalPages}</span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="tabular-nums">{wordCount.toLocaleString('en-IN')} words</span>
        <span className="tabular-nums">{tableCount} tables</span>
        <span className="tabular-nums">{figureCount} figures</span>
        <span className="flex items-center gap-1 font-medium">
          {saveState === 'saving'
            ? <><Loader2 className="h-3 w-3 animate-spin" /> Saving…</>
            : saveState === 'saved'
            ? <><Check className="h-3 w-3 text-emerald-500" /> Saved</>
            : 'Draft'}
        </span>
      </div>
    </div>
  );
}
