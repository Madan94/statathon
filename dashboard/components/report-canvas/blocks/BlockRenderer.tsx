'use client';
import { Loader2 } from 'lucide-react';
import type { PageBlock } from '../engine/useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   BlockRenderer — dispatches to the correct block type renderer.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  block: PageBlock;
  isSelected: boolean;
  onSelect: () => void;
  onGenerate?: (index: number) => void;
}

function fmtNum(n: number | string | undefined | null): string {
  if (n == null || n === '') return '\u2014';
  const v = typeof n === 'string' ? parseFloat(n) : n;
  if (v == null || isNaN(v)) return '\u2014';
  if (Math.abs(v) >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
  if (Math.abs(v) >= 1e5) return (v / 1e5).toFixed(2) + ' L';
  if (Math.abs(v) >= 1000) return v.toLocaleString('en-IN', { maximumFractionDigits: 1 });
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

export function BlockRenderer({ block, isSelected, onSelect, onGenerate }: Props) {
  // ── GENERATING shimmer ──
  if (block.status === 'generating') {
    return (
      <div className="rounded border border-blue-100 bg-blue-50/30 px-4 py-3">
        <div className="flex items-center gap-2">
          <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
          <span className="text-[10px] font-medium text-blue-600">{block.title}</span>
        </div>
        <div className="mt-2 space-y-1.5">
          <div className="h-2.5 w-full animate-pulse rounded bg-blue-100/60" />
          <div className="h-2.5 w-[85%] animate-pulse rounded bg-blue-100/40" />
        </div>
      </div>
    );
  }

  // ── PENDING placeholder ──
  if (block.status === 'pending') {
    return (
      <div
        onClick={e => { e.stopPropagation(); onGenerate?.(block.index); }}
        className="flex cursor-pointer items-center justify-between rounded border border-dashed border-slate-300 bg-slate-50/50 px-4 py-3 transition-colors hover:border-blue-400 hover:bg-blue-50/30"
      >
        <span className="text-[11px] text-slate-500">{block.title}</span>
        <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-[9px] font-semibold text-blue-700">Generate</span>
      </div>
    );
  }

  // ── ERROR ──
  if (block.status === 'error') {
    return (
      <div
        onClick={e => { e.stopPropagation(); onGenerate?.(block.index); }}
        className="flex cursor-pointer items-center justify-between rounded border border-red-200 bg-red-50/50 px-4 py-2"
      >
        <span className="text-[10px] text-red-600">Failed: {block.title}</span>
        <span className="rounded bg-red-100 px-2 py-0.5 text-[9px] font-semibold text-red-700">Retry</span>
      </div>
    );
  }

  // ── DONE: Real content ──
  return (
    <div
      onClick={e => { e.stopPropagation(); onSelect(); }}
      className={`rounded transition-all ${isSelected ? 'ring-2 ring-blue-400 ring-offset-1 bg-blue-50/10' : 'hover:bg-slate-50/50'}`}
    >
      {/* HEADING */}
      {block.kind === 'heading' && (
        <h2 className="py-1 text-[15px] font-bold text-slate-900">{block.content || block.title}</h2>
      )}

      {/* NARRATIVE */}
      {block.kind === 'narrative' && (
        <p className="py-1 text-[12px] leading-[1.8] text-slate-700">{block.content}</p>
      )}

      {/* KEY FINDING */}
      {block.kind === 'key_finding' && (
        <div className="rounded-md bg-blue-50/70 px-4 py-2.5">
          <p className="text-[12px] font-medium leading-[1.7] text-slate-700">{block.content}</p>
        </div>
      )}

      {/* TABLE */}
      {block.kind === 'table' && block.tableData && (
        <div className="overflow-hidden rounded border border-slate-200">
          <div className="border-b border-slate-100 bg-slate-50 px-3 py-1.5">
            <span className="text-[10px] font-semibold text-slate-600">{block.title}</span>
          </div>
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/50">
                <th className="px-2.5 py-1 text-left font-semibold text-slate-500">#</th>
                <th className="px-2.5 py-1 text-left font-semibold text-slate-500">State/UT</th>
                <th className="px-2.5 py-1 text-right font-semibold text-slate-500">Value</th>
                <th className="px-2.5 py-1 text-right font-semibold text-slate-500">Share</th>
              </tr>
            </thead>
            <tbody>
              {((block.tableData.items || block.tableData.rankingData || []) as Array<{ rank?: number; key?: Record<string, string>; value?: number }>).slice(0, 8).map((item, i) => {
                const all = (block.tableData!.items || block.tableData!.rankingData || []) as Array<{ value?: number }>;
                const total = all.reduce((s, x) => s + (x.value || 0), 0);
                const pct = total > 0 && item.value ? ((item.value / total) * 100).toFixed(1) : '\u2014';
                return (
                  <tr key={i} className="border-b border-slate-100/80 last:border-b-0">
                    <td className="px-2.5 py-1 tabular-nums text-slate-400">{item.rank ?? i + 1}</td>
                    <td className="px-2.5 py-1 text-slate-700">{item.key ? Object.values(item.key)[0] : '\u2014'}</td>
                    <td className="px-2.5 py-1 text-right tabular-nums font-medium text-slate-800">{fmtNum(item.value)}</td>
                    <td className="px-2.5 py-1 text-right tabular-nums text-slate-400">{pct}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {block.kind === 'table' && !block.tableData && (
        <p className="py-1 text-[12px] leading-[1.8] text-slate-700">{block.content}</p>
      )}

      {/* METRIC */}
      {block.kind === 'metric' && (
        <div className="flex items-baseline gap-2 rounded border border-slate-200 bg-gradient-to-r from-white to-slate-50 px-4 py-3">
          <span className="text-[22px] font-bold tabular-nums text-slate-800">{fmtNum(block.metricValue)}</span>
          {block.metricUnit && <span className="text-[11px] text-slate-400">{block.metricUnit}</span>}
          {block.content && <span className="ml-2 text-[10px] text-slate-500">{block.content}</span>}
        </div>
      )}

      {/* CHART placeholder */}
      {block.kind === 'chart' && (
        <div className="rounded border border-slate-200 p-3">
          <div className="flex h-24 items-end gap-[3%]">
            {[55, 80, 45, 70, 48, 85, 38, 62, 72, 50].map((h, i) => (
              <div key={i} className="flex-1 rounded-t" style={{ height: `${h}%`, background: `hsl(${215 + i * 3}, 50%, ${62 + i}%)` }} />
            ))}
          </div>
          <p className="mt-1.5 text-center text-[9px] text-slate-400">{block.title}</p>
        </div>
      )}

      {/* SOURCE NOTE */}
      {block.kind === 'source_note' && (
        <p className="py-0.5 text-[9px] text-slate-400">Source: {block.content}</p>
      )}

      {/* DIVIDER */}
      {block.kind === 'divider' && <div className="my-3 h-px bg-slate-200" />}
    </div>
  );
}
