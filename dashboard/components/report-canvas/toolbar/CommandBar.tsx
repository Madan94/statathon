'use client';
import Link from 'next/link';
import { useState } from 'react';
import {
  BarChart3, ChevronLeft, ClipboardCheck, Download, FileText, Hash, Heading,
  Layers, LayoutDashboard, Loader2, Maximize2, MessageSquare, Minus, Pause,
  Play, Plus, Quote, Sparkles, Table2, Type, Undo2, Redo2,
} from 'lucide-react';
import type { Phase, Panel, PageBlock } from '../engine/useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   CommandBar — primary report actions only.
   View/page/zoom controls live in CanvasViewBar so this row stays stable.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  title: string;
  bundle: { done: number; total: number; pending: number; generating: number; failed: number; manual: number; progressPct: number };
  phase: Phase;
  panel: Panel;
  onTogglePanel: (p: Panel) => void;
  onAutoGenerate: () => void;
  onPause: () => void;
  onResume: () => void;
  onOpenControlPanel: () => void;
  pdfUrl?: string;
  exportLabel?: 'Draft' | 'Final';
  onOpenReview?: () => void;
  reviewStatus?: 'draft' | 'in_review' | 'approved';
  reviewOpenIssues?: number;
  activeDraftName?: string;
  onOpenDrafts?: () => void;
  onOpenSectionGenerator?: () => void;
  onInsertBlock: (kind: PageBlock['kind']) => void;
  onToggleFocus: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
}

const INSERT_ITEMS: Array<{ kind: PageBlock['kind']; label: string; icon: typeof Type }> = [
  { kind: 'heading', label: 'Heading', icon: Heading },
  { kind: 'narrative', label: 'Paragraph', icon: Type },
  { kind: 'table', label: 'Table', icon: Table2 },
  { kind: 'chart', label: 'Chart', icon: BarChart3 },
  { kind: 'metric', label: 'Metric', icon: Hash },
  { kind: 'key_finding', label: 'Key finding', icon: Quote },
  { kind: 'source_note', label: 'Source note', icon: FileText },
  { kind: 'divider', label: 'Divider', icon: Minus },
];

export function CommandBar({
  title,
  bundle,
  phase,
  panel,
  onTogglePanel,
  onAutoGenerate,
  onPause,
  onResume,
  onOpenControlPanel,
  pdfUrl,
  exportLabel = 'Draft',
  onInsertBlock,
  onToggleFocus,
  onOpenReview,
  reviewStatus = 'draft',
  reviewOpenIssues = 0,
  activeDraftName,
  onOpenDrafts,
  onOpenSectionGenerator,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: Props) {
  const [insertOpen, setInsertOpen] = useState(false);

  return (
    <div className="grid h-12 shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 border-b border-slate-200 bg-white px-3">
      {/* Left: document actions */}
      <div className="flex min-w-0 items-center gap-2 overflow-hidden">
        <button
          type="button"
          onClick={() => onTogglePanel('left')}
          title="Navigator"
          aria-label="Navigator"
          className={`shrink-0 rounded p-1.5 transition-colors ${panel === 'left' ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}
        >
          <Layers className="h-4 w-4" />
        </button>
        <Link href="/report-builder/canvas" className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="Back" aria-label="Back">
          <ChevronLeft className="h-3.5 w-3.5" />
        </Link>
        <h1 className="min-w-0 max-w-[220px] truncate text-[13px] font-semibold text-slate-800">{title}</h1>

        <span className="mx-0.5 hidden h-5 w-px shrink-0 bg-slate-200 sm:block" />

        <div className="relative shrink-0">
          <button
            type="button"
            onClick={() => setInsertOpen(o => !o)}
            onBlur={() => setTimeout(() => setInsertOpen(false), 150)}
            className="flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Insert</span>
          </button>
          {insertOpen && (
            <div className="absolute left-0 top-full z-50 mt-1 w-44 rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
              {INSERT_ITEMS.map(({ kind, label, icon: Icon }) => (
                <button
                  key={kind}
                  type="button"
                  onMouseDown={() => { onInsertBlock(kind); setInsertOpen(false); }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] text-slate-600 hover:bg-blue-50 hover:text-blue-700"
                >
                  <Icon className="h-3.5 w-3.5" /> {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {onOpenSectionGenerator && (
          <button
            type="button"
            onClick={onOpenSectionGenerator}
            title="Generate section from a filtered data slice"
            className="flex shrink-0 items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-100"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span className="hidden md:inline">Generate Section</span>
            <span className="md:hidden">Generate</span>
          </button>
        )}
      </div>

      {/* Center: compact generation status */}
      <button
        type="button"
        onClick={onOpenControlPanel}
        title="Control Panel"
        className="hidden items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 hover:bg-slate-200 lg:flex"
      >
        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-emerald-500 transition-all duration-700" style={{ width: `${bundle.progressPct}%` }} />
        </div>
        <span className="text-[10px] font-medium tabular-nums text-slate-600">{bundle.done}/{bundle.total}</span>
        {bundle.failed > 0 && <span className="text-[9px] tabular-nums text-red-500">✕{bundle.failed}</span>}
      </button>

      {/* Right: review/generation/export/copilot */}
      <div className="flex min-w-0 items-center justify-end gap-2">
        <button
          type="button"
          onClick={onOpenControlPanel}
          title="Control Panel"
          aria-label="Control Panel"
          className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 lg:hidden"
        >
          <LayoutDashboard className="h-3.5 w-3.5" />
        </button>

        {onOpenDrafts && (
          <button
            type="button"
            onClick={onOpenDrafts}
            title="Open canvas drafts"
            className="hidden max-w-[170px] truncate rounded-md border border-blue-100 bg-blue-50 px-2.5 py-1.5 text-[11px] font-medium text-blue-700 hover:bg-blue-100 md:block"
          >
            {activeDraftName || 'Choose draft'}
          </button>
        )}

        {onOpenReview && (
          <button
            type="button"
            onClick={onOpenReview}
            title="Review & sign-off"
            className={`relative flex items-center gap-1 rounded-md border px-2 py-1.5 text-[11px] font-medium transition-colors ${
              reviewStatus === 'approved' ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : reviewStatus === 'in_review' ? 'border-amber-200 bg-amber-50 text-amber-700'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            <ClipboardCheck className="h-3.5 w-3.5" />
            <span className="hidden lg:inline">{reviewStatus === 'approved' ? 'Approved' : reviewStatus === 'in_review' ? 'In Review' : 'Review'}</span>
            {reviewOpenIssues > 0 && <span className="ml-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-red-500 px-1 text-[8px] font-bold text-white">{reviewOpenIssues}</span>}
          </button>
        )}

        {phase === 'init' && <Loader2 className="h-4 w-4 animate-spin text-slate-300" />}
        {phase === 'ready' && (
          <button type="button" onClick={onAutoGenerate} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700">
            <Play className="h-3 w-3" /> <span className="hidden lg:inline">Auto-Generate</span>
          </button>
        )}
        {phase === 'generating' && (
          <button type="button" onClick={onPause} className="flex items-center gap-1.5 rounded-md bg-amber-500 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-amber-600">
            <Pause className="h-3 w-3" /> <span className="hidden lg:inline">Pause</span>
          </button>
        )}
        {phase === 'paused' && (
          <button type="button" onClick={onResume} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700">
            <Play className="h-3 w-3" /> <span className="hidden lg:inline">Resume</span>
          </button>
        )}

        {(phase === 'complete' || bundle.done > 0) && pdfUrl && (
          <a href={pdfUrl} target="_blank" rel="noreferrer" className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-white ${exportLabel === 'Final' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-slate-600 hover:bg-slate-700'}`}>
            <Download className="h-3 w-3" /> <span className="hidden lg:inline">Export {exportLabel}</span>
          </a>
        )}

        <button type="button" onClick={onToggleFocus} title="Focus mode" aria-label="Focus mode" className="rounded p-1.5 text-slate-500 hover:bg-slate-100">
          <Maximize2 className="h-4 w-4" />
        </button>
        <button type="button" onClick={() => onTogglePanel('right')} title="Co-Pilot" aria-label="Co-Pilot" className={`rounded p-1.5 transition-colors ${panel === 'right' ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}>
          <MessageSquare className="h-4 w-4" />
        </button>

        {(onUndo || onRedo) && (
          <div className="hidden items-center gap-0.5 xl:flex">
            <button type="button" onClick={onUndo} disabled={!canUndo} title="Undo (⌘Z)" className="rounded p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-25"><Undo2 className="h-3.5 w-3.5" /></button>
            <button type="button" onClick={onRedo} disabled={!canRedo} title="Redo (⇧⌘Z)" className="rounded p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-25"><Redo2 className="h-3.5 w-3.5" /></button>
          </div>
        )}
      </div>
    </div>
  );
}
