'use client';
import { useState } from 'react';
import { BarChart3, FileText, Hash, Image, Minus, Pencil, Sparkles, Table2, TrendingUp, Type, Upload } from 'lucide-react';
import type { CanvasPage, PageBlock } from '../engine/useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   LeftPanel — Pages + Elements + Upload (Canva-style).
   ═══════════════════════════════════════════════════════════════════ */

type Tab = 'pages' | 'elements' | 'upload';

interface Props {
  pages: CanvasPage[];
  currentPage: number;
  onGoToPage: (idx: number) => void;
  getPageBlocks: (idx: number) => PageBlock[];
}

export function LeftPanel({ pages, currentPage, onGoToPage, getPageBlocks }: Props) {
  const [tab, setTab] = useState<Tab>('pages');

  return (
    <div className="w-56 shrink-0 border-r border-slate-200 bg-white flex flex-col">
      <div className="flex border-b border-slate-100">
        {(['pages', 'elements', 'upload'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`flex-1 py-2 text-[10px] font-semibold uppercase tracking-wide transition-colors ${tab === t ? 'border-b-2 border-blue-500 text-blue-600' : 'text-slate-400 hover:text-slate-600'}`}>{t}</button>
        ))}
      </div>
      <div className="flex-1 overflow-auto p-2">
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
              { i: BarChart3, l: 'Chart' }, { i: Table2, l: 'Table' },
              { i: Hash, l: 'Metric' }, { i: FileText, l: 'Text' },
              { i: Image, l: 'Image' }, { i: Minus, l: 'Divider' },
              { i: TrendingUp, l: 'Finding' }, { i: Pencil, l: 'Source' },
              { i: Type, l: 'Heading' }, { i: Sparkles, l: 'AI Block' },
            ].map(({ i: Icon, l }) => (
              <button key={l} className="flex flex-col items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-2.5 hover:border-blue-300 hover:bg-blue-50 active:scale-95 transition-all">
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
