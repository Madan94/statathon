'use client';
import Link from 'next/link';
import { useState } from 'react';
import {
  Layers, ChevronRight, Plus, BarChart3, Table2, Hash, Type, Heading,
  Quote, FileText, Minus, Download, MessageSquare, LayoutDashboard,
  Play, Pause, Loader2, ScrollText, BookOpen, Maximize2, ChevronLeft, ClipboardCheck, Undo2, Redo2,
} from 'lucide-react';
import type { Phase, Panel, PageBlock } from '../engine/useCanvasState';
import type { PageSize } from '../viewport/A4Page';

/* ═══════════════════════════════════════════════════════════════════
   CommandBar (U3) — ONE unified toolbar replacing the three stacked
   bars. Three zones:
     • left   = document menu (Insert ▾, Page, Density, Theme)
     • centre = view (Paged/Scroll, Front Matter, page nav, Zoom)
     • right  = actions (Control Panel, Auto-Generate, Export, Co-Pilot)
   Text formatting is NOT here — it floats over the edited block (U2).
   ═══════════════════════════════════════════════════════════════════ */

export type Density = 'compact' | 'comfortable';
export type ViewMode = 'paged' | 'scroll';

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
  /** Document final/draft state gates the export label (U4). */
  exportLabel?: 'Draft' | 'Final';
  /** Open the review & sign-off popup (U4). */
  onOpenReview?: () => void;
  /** Review status badge + open-issue count (U4). */
  reviewStatus?: 'draft' | 'in_review' | 'approved';
  reviewOpenIssues?: number;
  // Insert
  onInsertBlock: (kind: PageBlock['kind']) => void;
  // Page + density + theme
  pageSize: PageSize;
  onPageSizeChange: (s: PageSize) => void;
  density: Density;
  onDensityChange: (d: Density) => void;
  /** Document typography preset (T6). */
  typographyPreset?: string;
  onTypographyPresetChange?: (id: string) => void;
  typographyPresets?: Array<{ id: string; label: string }>;
  /** Open the full typography settings panel (T6). */
  onOpenTypography?: () => void;
  // View
  viewMode: ViewMode;
  onViewModeChange: (v: ViewMode) => void;
  showFrontMatter: boolean;
  onToggleFrontMatter: () => void;
  zoom: number;
  onZoomChange: (z: number) => void;
  // Paged nav
  currentPage: number;
  totalPages: number;
  onGoToPage: (i: number) => void;
  onAddPage: () => void;
  // Focus mode
  onToggleFocus: () => void;
  // Undo/redo (U5)
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

export function CommandBar(props: Props) {
  const {
    title, bundle, phase, panel, onTogglePanel, onAutoGenerate, onPause, onResume,
    onOpenControlPanel, pdfUrl, exportLabel = 'Draft', onInsertBlock, pageSize, onPageSizeChange,
    density, onDensityChange, viewMode, onViewModeChange, showFrontMatter, onToggleFrontMatter,
    zoom, onZoomChange, currentPage, totalPages, onGoToPage, onAddPage, onToggleFocus,
    onOpenReview, reviewStatus = 'draft', reviewOpenIssues = 0, onUndo, onRedo, canUndo, canRedo,
    typographyPreset, onTypographyPresetChange, typographyPresets, onOpenTypography,
  } = props;
  const [insertOpen, setInsertOpen] = useState(false);

  return (
    <div className="flex h-11 items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 shrink-0">
      {/* ── LEFT: document menu ── */}
      <div className="flex items-center gap-2">
        <button onClick={() => onTogglePanel('left')} title="Navigator" className={`rounded p-1.5 transition-colors ${panel === 'left' ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}>
          <Layers className="h-4 w-4" />
        </button>
        <Link href="/report-builder/canvas" className="text-slate-400 hover:text-slate-600" title="Back"><ChevronLeft className="h-3.5 w-3.5" /></Link>
        <h1 className="max-w-[160px] truncate text-[13px] font-semibold text-slate-800">{title}</h1>

        <span className="mx-0.5 h-4 w-px bg-slate-200" />

        {/* Insert ▾ */}
        <div className="relative">
          <button onClick={() => setInsertOpen(o => !o)} onBlur={() => setTimeout(() => setInsertOpen(false), 150)}
            className="flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50">
            <Plus className="h-3.5 w-3.5" /> Insert
          </button>
          {insertOpen && (
            <div className="absolute left-0 top-full z-50 mt-1 w-44 rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
              {INSERT_ITEMS.map(({ kind, label, icon: Icon }) => (
                <button key={kind} onMouseDown={() => { onInsertBlock(kind); setInsertOpen(false); }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] text-slate-600 hover:bg-blue-50 hover:text-blue-700">
                  <Icon className="h-3.5 w-3.5" /> {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Page size */}
        <select value={pageSize} onChange={e => onPageSizeChange(e.target.value as PageSize)} title="Page size"
          className="rounded border border-slate-200 bg-white px-1.5 py-1 text-[10px] text-slate-600 hover:border-blue-300">
          <option value="a4">A4</option>
          <option value="mospi">MoSPI</option>
          <option value="a4-extended">A4+</option>
          <option value="letter">Letter</option>
        </select>

        {/* Density */}
        <select value={density} onChange={e => onDensityChange(e.target.value as Density)} title="Density"
          className="rounded border border-slate-200 bg-white px-1.5 py-1 text-[10px] text-slate-600 hover:border-blue-300">
          <option value="comfortable">Comfortable</option>
          <option value="compact">Compact</option>
        </select>

        {/* Typography preset (T6) */}
        {onTypographyPresetChange && typographyPresets && (
          <select value={typographyPreset} onChange={e => onTypographyPresetChange(e.target.value)} title="Document font"
            className="rounded border border-slate-200 bg-white px-1.5 py-1 text-[10px] text-slate-600 hover:border-blue-300">
            {typographyPresets.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        )}
        {/* Full typography settings (T6) */}
        {onOpenTypography && (
          <button onClick={onOpenTypography} title="Typography settings"
            className="rounded border border-slate-200 px-1.5 py-1 text-[11px] font-semibold leading-none text-slate-600 hover:bg-slate-50">Aa</button>
        )}

        {/* Undo / Redo (U5) */}
        {(onUndo || onRedo) && (
          <div className="flex items-center gap-0.5">
            <button onClick={onUndo} disabled={!canUndo} title="Undo (⌘Z)" className="rounded p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-25"><Undo2 className="h-3.5 w-3.5" /></button>
            <button onClick={onRedo} disabled={!canRedo} title="Redo (⇧⌘Z)" className="rounded p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-25"><Redo2 className="h-3.5 w-3.5" /></button>
          </div>
        )}
      </div>

      {/* ── CENTRE: view controls ── */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-0.5 rounded-md border border-slate-200 bg-white p-0.5">
          <button onClick={() => onViewModeChange('paged')} title="Paged view"
            className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${viewMode === 'paged' ? 'bg-blue-600 text-white' : 'text-slate-500 hover:bg-slate-100'}`}>
            <BookOpen className="h-3 w-3" /> Paged
          </button>
          <button onClick={() => onViewModeChange('scroll')} title="Scroll view"
            className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${viewMode === 'scroll' ? 'bg-blue-600 text-white' : 'text-slate-500 hover:bg-slate-100'}`}>
            <ScrollText className="h-3 w-3" /> Scroll
          </button>
        </div>

        <button onClick={onToggleFrontMatter} title="Front matter"
          className={`rounded px-2 py-1 text-[10px] font-medium transition-colors ${showFrontMatter ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}>
          Front Matter
        </button>

        {/* Paged nav lives here (top, not bottom) */}
        {viewMode === 'paged' && totalPages > 0 && (
          <div className="flex items-center gap-0.5">
            <button onClick={() => onGoToPage(currentPage - 1)} disabled={currentPage <= 0}
              className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-200 disabled:opacity-20"><ChevronLeft className="h-4 w-4" /></button>
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              const p = totalPages <= 7 ? i : (currentPage <= 3 ? i : currentPage >= totalPages - 4 ? totalPages - 7 + i : currentPage - 3 + i);
              return (
                <button key={p} onClick={() => onGoToPage(p)}
                  className={`flex h-6 min-w-[22px] items-center justify-center rounded text-[9px] font-semibold tabular-nums transition-all ${p === currentPage ? 'bg-blue-600 text-white scale-110' : 'text-slate-500 hover:bg-slate-200'}`}>
                  {p + 1}
                </button>
              );
            })}
            <button onClick={() => onGoToPage(currentPage + 1)} disabled={currentPage >= totalPages - 1}
              className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-200 disabled:opacity-20"><ChevronRight className="h-4 w-4" /></button>
            <button onClick={onAddPage} title="Add page"
              className="flex h-6 w-6 items-center justify-center rounded border border-dashed border-slate-300 text-slate-400 hover:border-blue-400 hover:text-blue-600"><Plus className="h-3 w-3" /></button>
          </div>
        )}

        {/* Zoom */}
        <div className="flex items-center gap-0.5">
          <button onClick={() => onZoomChange(Math.max(25, zoom - 10))} title="Zoom out" className="rounded border border-slate-200 px-1.5 py-0.5 text-[11px] leading-none text-slate-500 hover:bg-slate-100">−</button>
          <select value={zoom} onChange={e => onZoomChange(Number(e.target.value))} className="rounded border border-slate-200 bg-white px-1 py-0.5 text-[10px] text-slate-600 hover:border-blue-300">
            {[50, 75, 100, 125, 150].map(z => <option key={z} value={z}>{z}%</option>)}
          </select>
          <button onClick={() => onZoomChange(Math.min(150, zoom + 10))} title="Zoom in" className="rounded border border-slate-200 px-1.5 py-0.5 text-[11px] leading-none text-slate-500 hover:bg-slate-100">+</button>
        </div>
      </div>

      {/* ── RIGHT: actions ── */}
      <div className="flex items-center gap-2">
        {/* Bundle progress pill → Control Panel */}
        <button onClick={onOpenControlPanel} title="Control Panel" className="flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 hover:bg-slate-200">
          <div className="h-1.5 w-12 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full rounded-full bg-emerald-500 transition-all duration-700" style={{ width: `${bundle.progressPct}%` }} />
          </div>
          <span className="text-[10px] font-medium tabular-nums text-slate-600">{bundle.done}/{bundle.total}</span>
          {(bundle.pending + bundle.generating) > 0 && <span className="text-[9px] tabular-nums text-slate-400">◷{bundle.pending + bundle.generating}</span>}
          {bundle.failed > 0 && <span className="text-[9px] tabular-nums text-red-500">✕{bundle.failed}</span>}
        </button>

        <button onClick={onOpenControlPanel} title="Control Panel" className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50"><LayoutDashboard className="h-3.5 w-3.5" /></button>

        {/* Review & sign-off (U4) */}
        {onOpenReview && (
          <button onClick={onOpenReview} title="Review & sign-off"
            className={`relative flex items-center gap-1 rounded-md border px-2 py-1.5 text-[11px] font-medium transition-colors ${
              reviewStatus === 'approved' ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : reviewStatus === 'in_review' ? 'border-amber-200 bg-amber-50 text-amber-700'
              : 'border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}>
            <ClipboardCheck className="h-3.5 w-3.5" />
            {reviewStatus === 'approved' ? 'Approved' : reviewStatus === 'in_review' ? 'In Review' : 'Review'}
            {reviewOpenIssues > 0 && <span className="ml-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-red-500 px-1 text-[8px] font-bold text-white">{reviewOpenIssues}</span>}
          </button>
        )}

        {phase === 'init' && <Loader2 className="h-4 w-4 animate-spin text-slate-300" />}
        {phase === 'ready' && (
          <button onClick={onAutoGenerate} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700"><Play className="h-3 w-3" /> Auto-Generate</button>
        )}
        {phase === 'generating' && (
          <button onClick={onPause} className="flex items-center gap-1.5 rounded-md bg-amber-500 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-amber-600"><Pause className="h-3 w-3" /> Pause</button>
        )}
        {phase === 'paused' && (
          <button onClick={onResume} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700"><Play className="h-3 w-3" /> Resume</button>
        )}
        {(phase === 'complete' || bundle.done > 0) && pdfUrl && (
          <a href={pdfUrl} target="_blank" rel="noreferrer" className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-white ${exportLabel === 'Final' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-slate-600 hover:bg-slate-700'}`}>
            <Download className="h-3 w-3" /> Export {exportLabel}
          </a>
        )}

        <button onClick={onToggleFocus} title="Focus mode" className="rounded p-1.5 text-slate-500 hover:bg-slate-100"><Maximize2 className="h-4 w-4" /></button>
        <button onClick={() => onTogglePanel('right')} title="Co-Pilot" className={`rounded p-1.5 transition-colors ${panel === 'right' ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}><MessageSquare className="h-4 w-4" /></button>
      </div>
    </div>
  );
}
