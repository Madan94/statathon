'use client';
import { AlignCenter, AlignLeft, AlignRight, BarChart3, Bold, Hash, Italic, Table2, Type, Underline } from 'lucide-react';
import type { PageSize } from '../viewport/A4Page';

/* ═══════════════════════════════════════════════════════════════════
   FormatRibbon — MS Word-style formatting toolbar below nav.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  pageSize: PageSize;
  zoom: number;
  onPageSizeChange: (size: PageSize) => void;
  onZoomChange: (zoom: number) => void;
}

export function FormatRibbon({ pageSize, zoom, onPageSizeChange, onZoomChange }: Props) {
  return (
    <div className="flex h-9 items-center gap-1 border-b border-slate-200 bg-white px-3 shrink-0">
      <div className="flex items-center gap-0.5 rounded border border-slate-200 px-1">
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100"><Bold className="h-3 w-3" /></button>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100"><Italic className="h-3 w-3" /></button>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100"><Underline className="h-3 w-3" /></button>
      </div>
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <div className="flex items-center gap-0.5 rounded border border-slate-200 px-1">
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100"><AlignLeft className="h-3 w-3" /></button>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100"><AlignCenter className="h-3 w-3" /></button>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100"><AlignRight className="h-3 w-3" /></button>
      </div>
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <div className="flex items-center gap-0.5 rounded border border-slate-200 px-1">
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100" title="Chart"><BarChart3 className="h-3 w-3" /></button>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100" title="Table"><Table2 className="h-3 w-3" /></button>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100" title="Metric"><Hash className="h-3 w-3" /></button>
        <button className="rounded p-1 text-slate-500 hover:bg-slate-100" title="Text"><Type className="h-3 w-3" /></button>
      </div>
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <select value={pageSize} onChange={e => onPageSizeChange(e.target.value as PageSize)} className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600 cursor-pointer hover:border-blue-300">
        <option value="a4">A4 (210×297mm)</option>
        <option value="mospi">MoSPI Standard</option>
        <option value="a4-extended">A4 Extended</option>
        <option value="letter">US Letter</option>
      </select>
      <select value={zoom} onChange={e => onZoomChange(Number(e.target.value))} className="ml-1 rounded border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600 cursor-pointer hover:border-blue-300">
        <option value={50}>50%</option>
        <option value={75}>75%</option>
        <option value={100}>100%</option>
        <option value={125}>125%</option>
      </select>
    </div>
  );
}
