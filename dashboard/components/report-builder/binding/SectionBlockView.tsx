'use client';

import { Badge } from '@/components/ui/Badge';
import type { GeneratedSectionBlock } from '@/lib/report-section';

// ─────────────────────────────────────────────────────────────────────────────
// Shared read-only renderer for one generated section block. Used by both the
// Query interpreter preview and the section-loop canvas so block visuals stay
// identical across the loop (narrative / table / chart / metric / key_finding).
// ─────────────────────────────────────────────────────────────────────────────

type SectionTableRow = { key: Record<string, unknown>; value: number | null; n: number };

function fmtVal(value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—';
  return Math.abs(value) >= 1000
    ? value.toLocaleString('en-IN', { maximumFractionDigits: 1 })
    : value.toFixed(Number.isInteger(value) ? 0 : 2);
}

function keyLabel(k: Record<string, unknown>): string {
  const vals = Object.values(k).filter((v) => v != null && v !== '');
  return vals.length ? vals.map(String).join(' / ') : 'All';
}

export function SectionBlockView({ block }: { block: GeneratedSectionBlock }) {
  const rows = (block.tableData?.rows as SectionTableRow[] | undefined) ?? [];
  const maxVal = rows.reduce((mx, r) => Math.max(mx, Math.abs(r.value ?? 0)), 0) || 1;

  return (
    <div className="rounded-xl border border-border bg-surface-card p-4">
      <div className="mb-2 flex items-center gap-2">
        <Badge
          variant={block.kind === 'chart' ? 'default' : block.kind === 'table' ? 'warning' : block.kind === 'metric' ? 'success' : 'muted'}
          className="text-[9px] uppercase"
        >
          {block.kind}
        </Badge>
        <span className="text-sm font-semibold text-text">{block.title}</span>
      </div>

      {(block.kind === 'narrative' || block.kind === 'key_finding' || block.kind === 'source_note') && (
        <p className="text-xs leading-relaxed text-text">{block.content || '—'}</p>
      )}

      {block.kind === 'metric' && (
        <p className="text-2xl font-bold text-primary">
          {block.metricValue}
          {block.metricUnit ? <span className="ml-1 text-sm font-normal text-text-muted">{block.metricUnit}</span> : null}
        </p>
      )}

      {block.kind === 'table' && (
        <div className="overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase text-text-muted">
                <th className="px-3 py-1.5">Group</th>
                <th className="px-3 py-1.5 text-right">{String(block.tableData?.measure ?? 'Value')}</th>
                <th className="px-3 py-1.5 text-right">n</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-3 py-1.5 font-medium text-text">{keyLabel(r.key)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-text">
                    {fmtVal(r.value)}
                    {block.tableData?.unit ? ` ${String(block.tableData.unit)}` : ''}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-text-muted">{r.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {block.kind === 'chart' && (
        <div className="space-y-1.5">
          {rows.slice(0, 12).map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-28 shrink-0 truncate text-[11px] text-text-muted" title={keyLabel(r.key)}>
                {keyLabel(r.key)}
              </span>
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-border/30">
                <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round((Math.abs(r.value ?? 0) / maxVal) * 100)}%` }} />
              </div>
              <span className="w-20 shrink-0 text-right text-[11px] tabular-nums text-text">{fmtVal(r.value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default SectionBlockView;
