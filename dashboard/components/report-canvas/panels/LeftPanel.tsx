'use client';
import { useState } from 'react';
import { BarChart3, FileText, Hash, Minus, Pencil, Table2, TrendingUp, Type, Upload, List, LayoutGrid } from 'lucide-react';
import type { CanvasPage, PageBlock } from '../engine/useCanvasState';
import type { TocEntry } from '../engine/useDocumentModel';

/* ═══════════════════════════════════════════════════════════════════
   LeftPanel — document Navigator (U1): Outline tree + Pages thumbnails
   + Elements + Upload. The Outline lists §-numbered headings with a
   "you are here" highlight that tracks the current page.
   ═══════════════════════════════════════════════════════════════════ */

type Tab = 'outline' | 'pages' | 'elements' | 'upload';

interface Props {
  pages: CanvasPage[];
  currentPage: number;
  onGoToPage: (idx: number) => void;
  getPageBlocks: (idx: number) => PageBlock[];
  onInsertBlock: (kind: PageBlock['kind']) => void;
  /** Document outline (numbered headings → page) for the Outline tab. */
  toc?: TocEntry[];
  /** Jump to a section anchor. */
  onJumpToAnchor?: (anchor: string) => void;
  /** Active section anchor from the viewport scroll-spy (preferred for the
   *  "you are here" highlight; falls back to page tracking when absent). */
  activeAnchor?: string;
}

export function LeftPanel({ pages, currentPage, onGoToPage, getPageBlocks, onInsertBlock, toc = [], onJumpToAnchor, activeAnchor }: Props) {
  const [tab, setTab] = useState<Tab>('outline');

  // The current section: the scroll-spy anchor when available, otherwise the
  // deepest TOC entry on/above the current page.
  const currentAnchor = (() => {
    if (activeAnchor) return activeAnchor;
    if (currentPage < 0) return undefined;
    let best: string | undefined;
    for (const e of toc) { if (e.page - 1 <= currentPage) best = e.anchor; }
    return best;
  })();

  const TABS: Array<{ id: Tab; icon: typeof List; label: string }> = [
    { id: 'outline', icon: List, label: 'Outline' },
    { id: 'pages', icon: LayoutGrid, label: 'Pages' },
    { id: 'elements', icon: Type, label: 'Insert' },
    { id: 'upload', icon: Upload, label: 'Upload' },
  ];

  return (
    <div className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-100 bg-slate-50 px-3 py-2">
        <p className="text-[11px] font-semibold text-slate-700">Document Navigator</p>
        <p className="text-[9px] text-slate-400">Outline, pages and insertable blocks</p>
      </div>
      <div className="flex border-b border-slate-100">
        {TABS.map(({ id, icon: Icon, label }) => (
          <button key={id} onClick={() => setTab(id)} title={label}
            className={`flex flex-1 items-center justify-center gap-1 py-2 text-[9px] font-semibold uppercase tracking-wide transition-colors ${tab === id ? 'border-b-2 border-blue-500 text-blue-600' : 'text-slate-400 hover:text-slate-600'}`}>
            <Icon className="h-3 w-3" />
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-auto p-2.5">
        {/* OUTLINE — §-numbered navigation tree with "you are here" */}
        {tab === 'outline' && (
          <div className="space-y-0.5">
            {toc.length === 0 && (
              <p className="px-2 py-6 text-center text-[10px] italic text-slate-300">Generate the report to build its outline.</p>
            )}
            {toc.map((e) => {
              const here = e.anchor === currentAnchor;
              return (
                <button
                  key={e.anchor}
                  onClick={() => onJumpToAnchor?.(e.anchor)}
                  className={`relative flex w-full items-baseline gap-1.5 rounded px-2 py-1 text-left transition-colors ${
                    here ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-50'
                  } ${e.depth === 1 ? 'font-bold' : e.depth === 2 ? 'pl-4 font-medium' : 'pl-7'}`}
                  style={{ fontSize: e.depth === 1 ? 11 : e.depth === 2 ? 10 : 9.5 }}
                >
                  {here && <span className="absolute left-0 text-blue-500">▸</span>}
                  <span className="tabular-nums text-slate-400">{e.number}</span>
                  <span className="truncate">{e.label}</span>
                </button>
              );
            })}
          </div>
        )}

        {tab === 'pages' && (
          <div className="grid grid-cols-2 gap-2">
            {pages.map((page, i) => {
              const blocks = getPageBlocks(i);
              const done = blocks.filter(b => b.status === 'done').length;
              return (
                <button key={page.id} onClick={() => onGoToPage(i)}
                  className={`rounded-lg border p-2 text-left transition-all ${i === currentPage ? 'border-blue-400 bg-blue-50/50 ring-1 ring-blue-200' : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'}`}>
                  <div className="mb-1 aspect-[210/297] rounded bg-white border border-slate-100 flex items-center justify-center text-[7px] text-slate-300">
                    {blocks.length > 0 ? `${done}/${blocks.length}` : 'Empty'}
                  </div>
                  <p className="text-[9px] font-medium text-slate-600 text-center">Page {i + 1}</p>
                </button>
              );
            })}
          </div>
        )}
        {tab === 'elements' && (
          <div className="grid grid-cols-2 gap-1.5">
            {[
              { i: BarChart3, l: 'Chart', k: 'chart' as const },
              { i: Table2, l: 'Table', k: 'table' as const },
              { i: Hash, l: 'Metric', k: 'metric' as const },
              { i: FileText, l: 'Text', k: 'narrative' as const },
              { i: Minus, l: 'Divider', k: 'divider' as const },
              { i: TrendingUp, l: 'Finding', k: 'key_finding' as const },
              { i: Pencil, l: 'Source', k: 'source_note' as const },
              { i: Type, l: 'Heading', k: 'heading' as const },
            ].map(({ i: Icon, l, k }) => (
              <button key={l} onClick={() => onInsertBlock(k)}
                className="flex flex-col items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-2.5 hover:border-blue-300 hover:bg-blue-50 active:scale-95 transition-all">
                <Icon className="h-4 w-4 text-slate-600" /><span className="text-[9px] font-medium text-slate-600">{l}</span>
              </button>
            ))}
          </div>
        )}
        {tab === 'upload' && (
          <div className="flex flex-col items-center rounded-lg border-2 border-dashed border-slate-200 bg-slate-50 p-6 text-center">
            <Upload className="h-6 w-6 text-slate-300" />
            <p className="mt-2 text-[10px] text-slate-500">Drop images or files</p>
            <button className="mt-2 rounded bg-slate-200 px-3 py-1 text-[9px] font-medium text-slate-600 hover:bg-slate-300">Browse</button>
          </div>
        )}
      </div>
    </div>
  );
}
