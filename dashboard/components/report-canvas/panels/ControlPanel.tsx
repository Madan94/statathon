'use client';
import { useState } from 'react';
import { X, CheckCircle2, Clock, AlertCircle, Loader2, Play, RotateCcw, Search } from 'lucide-react';
import type { BundleModel, BundleItemStatus } from '../engine/useBundleModel';

/* ═══════════════════════════════════════════════════════════════════
   Control Panel (S2) — the report's generation mission-control.
   Opened from the "Control Panel" button near Export PDF. Shows the
   full question bundle with live status, per-topic rollup, filtering,
   and per-row / bulk generation actions.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  bundle: BundleModel;
  onClose: () => void;
  onGenerateIndex: (index: number) => void;
  onGenerateTopic: (topic: string) => void;
  onGenerateRemaining: () => void;
  onRetryFailed: () => void;
  onInspect: (index: number) => void;
}

type Filter = 'all' | 'pending' | 'failed' | 'done';

const STATUS_META: Record<BundleItemStatus, { icon: typeof CheckCircle2; cls: string; label: string }> = {
  done: { icon: CheckCircle2, cls: 'text-emerald-600', label: 'Generated' },
  generating: { icon: Loader2, cls: 'text-blue-500 animate-spin', label: 'Generating' },
  error: { icon: AlertCircle, cls: 'text-red-500', label: 'Failed' },
  pending: { icon: Clock, cls: 'text-slate-400', label: 'Pending' },
};

export function ControlPanel({ bundle, onClose, onGenerateIndex, onGenerateTopic, onGenerateRemaining, onRetryFailed, onInspect }: Props) {
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');

  const rows = bundle.items.filter((it) => {
    if (filter === 'pending' && !(it.status === 'pending' || it.status === 'generating')) return false;
    if (filter === 'failed' && it.status !== 'error') return false;
    if (filter === 'done' && it.status !== 'done') return false;
    if (query && !`${it.title} ${it.sectionPath.join(' ')}`.toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/30 backdrop-blur-sm" onClick={onClose}>
      <div className="flex max-h-[82vh] w-[680px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="text-[14px] font-semibold text-slate-800">Generation Control Panel</h2>
            <p className="text-[11px] text-slate-400">
              {bundle.done}/{bundle.total} components · {bundle.pending + bundle.generating} pending
              {bundle.failed > 0 && <span className="text-red-500"> · {bundle.failed} failed</span>}
              {bundle.manual > 0 && <span className="text-slate-400"> · {bundle.manual} manual</span>}
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1.5 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>

        {/* Progress bar */}
        <div className="px-4 pt-3">
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-emerald-500 transition-all duration-500" style={{ width: `${bundle.progressPct}%` }} />
          </div>
        </div>

        {/* Per-topic rollup */}
        <div className="flex flex-wrap gap-2 px-4 py-3">
          {bundle.topics.map((t) => {
            const complete = t.done >= t.total;
            return (
              <button
                key={t.topic}
                onClick={() => !complete && onGenerateTopic(t.topic)}
                disabled={complete}
                className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[10px] font-medium transition-colors ${
                  complete
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-blue-400 hover:bg-blue-50'
                }`}
                title={complete ? 'Complete' : `Generate ${t.topic}`}
              >
                {complete ? <CheckCircle2 className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                <span className="max-w-[150px] truncate">{t.topic}</span>
                <span className="tabular-nums opacity-70">{t.done}/{t.total}</span>
              </button>
            );
          })}
        </div>

        {/* Filter + search bar */}
        <div className="flex items-center gap-2 border-y border-slate-100 bg-slate-50/60 px-4 py-2">
          {(['all', 'pending', 'failed', 'done'] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded px-2 py-0.5 text-[10px] font-medium capitalize transition-colors ${
                filter === f ? 'bg-blue-600 text-white' : 'text-slate-500 hover:bg-slate-200'
              }`}
            >
              {f}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-0.5">
            <Search className="h-3 w-3 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search components…"
              className="w-40 text-[10px] text-slate-600 outline-none"
            />
          </div>
        </div>

        {/* Bundle table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-slate-200 text-slate-400">
                <th className="px-4 py-1.5 text-left font-semibold">#</th>
                <th className="px-2 py-1.5 text-left font-semibold">Component</th>
                <th className="px-2 py-1.5 text-left font-semibold">Section</th>
                <th className="px-2 py-1.5 text-left font-semibold">Status</th>
                <th className="px-2 py-1.5 text-right font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((it) => {
                const meta = STATUS_META[it.status];
                const Icon = meta.icon;
                return (
                  <tr key={it.index} className="border-b border-slate-100 hover:bg-slate-50/60">
                    <td className="px-4 py-1.5 tabular-nums text-slate-400">{it.index}</td>
                    <td className="px-2 py-1.5">
                      <span className="font-medium text-slate-700">{it.title}</span>
                      <span className="ml-1.5 rounded bg-slate-100 px-1 py-0.5 text-[8px] text-slate-400">{it.componentType}</span>
                    </td>
                    <td className="px-2 py-1.5 max-w-[180px] truncate text-slate-500" title={it.sectionPath.join(' › ')}>
                      {it.chapter || it.topic}
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={`inline-flex items-center gap-1 ${meta.cls}`}>
                        <Icon className="h-3 w-3" /> <span className="text-[9px]">{meta.label}</span>
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <button onClick={() => onInspect(it.index)} className="mr-1 rounded px-1.5 py-0.5 text-[9px] text-slate-500 hover:bg-slate-100">Inspect</button>
                      <button
                        onClick={() => onGenerateIndex(it.index)}
                        className="rounded bg-blue-50 px-1.5 py-0.5 text-[9px] font-medium text-blue-600 hover:bg-blue-100"
                      >
                        {it.status === 'done' ? 'Redo' : it.status === 'error' ? 'Retry' : 'Generate'}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-[11px] text-slate-300">No components match this filter.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Footer bulk actions */}
        <div className="flex items-center gap-2 border-t border-slate-200 px-4 py-2.5">
          {bundle.failed > 0 && (
            <button onClick={onRetryFailed} className="flex items-center gap-1.5 rounded-md bg-red-50 px-2.5 py-1 text-[11px] font-medium text-red-600 hover:bg-red-100">
              <RotateCcw className="h-3 w-3" /> Retry failed ({bundle.failed})
            </button>
          )}
          <button
            onClick={onGenerateRemaining}
            disabled={bundle.remainingIndices.length === 0}
            className="ml-auto flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1 text-[11px] font-medium text-white hover:bg-blue-700 disabled:opacity-40"
          >
            <Play className="h-3 w-3" /> Generate remaining ({bundle.remainingIndices.length})
          </button>
        </div>
      </div>
    </div>
  );
}
