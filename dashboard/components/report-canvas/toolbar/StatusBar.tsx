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
    <div className="flex h-6 shrink-0 items-center justify-between border-t border-slate-200 bg-white px-3 text-[9px] text-slate-400">
      <div className="flex items-center gap-3">
        {sectionLabel && (
          <span className="flex items-center gap-1"><MapPin className="h-2.5 w-2.5 text-blue-400" /> {sectionLabel}</span>
        )}
        <span className="tabular-nums">Page {pageNumber} / {totalPages}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="tabular-nums">{wordCount.toLocaleString('en-IN')} words</span>
        <span className="tabular-nums">{tableCount} tables</span>
        <span className="tabular-nums">{figureCount} figures</span>
        <span className="flex items-center gap-1">
          {saveState === 'saving'
            ? <><Loader2 className="h-2.5 w-2.5 animate-spin" /> Saving…</>
            : saveState === 'saved'
            ? <><Check className="h-2.5 w-2.5 text-emerald-500" /> Saved</>
            : 'Draft'}
        </span>
      </div>
    </div>
  );
}
