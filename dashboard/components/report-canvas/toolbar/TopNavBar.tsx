'use client';
import Link from 'next/link';
import { ChevronRight, Download, Layers, Loader2, MessageSquare, Pause, Play } from 'lucide-react';
import type { Phase, Panel } from '../engine/useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   TopNavBar — title, progress, generation controls, panel toggles.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  title: string;
  progress: number;
  doneCount: number;
  totalCount: number;
  phase: Phase;
  panel: Panel;
  onTogglePanel: (p: Panel) => void;
  onAutoGenerate: () => void;
  onPause: () => void;
  onResume: () => void;
  pdfUrl?: string;
}

export function TopNavBar({ title, progress, doneCount, totalCount, phase, panel, onTogglePanel, onAutoGenerate, onPause, onResume, pdfUrl }: Props) {
  return (
    <div className="flex h-11 items-center justify-between border-b border-slate-200 bg-white px-3 shrink-0">
      <div className="flex items-center gap-3">
        <button onClick={() => onTogglePanel('left')} className={`rounded p-1.5 transition-colors ${panel === 'left' ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}>
          <Layers className="h-4 w-4" />
        </button>
        <Link href="/report-builder" className="text-slate-400 hover:text-slate-600"><ChevronRight className="h-3.5 w-3.5 rotate-180" /></Link>
        <h1 className="text-[13px] font-semibold text-slate-800 truncate max-w-[220px]">{title}</h1>
      </div>
      <div className="flex items-center gap-2">
        {/* Progress pill */}
        <div className="flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1">
          <div className="h-1.5 w-14 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full rounded-full bg-emerald-500 transition-all duration-700" style={{ width: `${progress}%` }} />
          </div>
          <span className="text-[10px] font-medium tabular-nums text-slate-600">{doneCount}/{totalCount}</span>
        </div>

        {/* Generation controls */}
        {phase === 'init' && <Loader2 className="h-4 w-4 animate-spin text-slate-300" />}
        {phase === 'ready' && (
          <button onClick={onAutoGenerate} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-[11px] font-medium text-white shadow-sm hover:bg-blue-700 transition-colors">
            <Play className="h-3 w-3" /> Auto-Generate
          </button>
        )}
        {phase === 'generating' && (
          <button onClick={onPause} className="flex items-center gap-1.5 rounded-md bg-amber-500 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-amber-600">
            <Pause className="h-3 w-3" /> Pause
          </button>
        )}
        {phase === 'paused' && (
          <button onClick={onResume} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700">
            <Play className="h-3 w-3" /> Resume
          </button>
        )}
        {phase === 'complete' && pdfUrl && (
          <a href={pdfUrl} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-emerald-700">
            <Download className="h-3 w-3" /> Export PDF
          </a>
        )}

        {/* Chat toggle */}
        <button onClick={() => onTogglePanel('right')} className={`rounded p-1.5 transition-colors ${panel === 'right' ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}>
          <MessageSquare className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
