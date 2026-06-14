'use client';
import { AlignCenter, AlignLeft, AlignRight, BarChart3, Bold, Hash, Italic, Table2, Type, Underline } from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════
   FormatRibbon — MS Word-style formatting toolbar below nav.
   ═══════════════════════════════════════════════════════════════════ */

export function FormatRibbon() {
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
      <select className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600"><option>A4 (210×297mm)</option><option>MoSPI Standard</option><option>Letter</option></select>
      <select className="ml-1 rounded border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600"><option>100%</option><option>75%</option><option>Fit width</option></select>
    </div>
  );
}
