'use client';

import { Database, TrendingUp, Grid3X3, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Badge } from '@/components/ui/Badge';
import type { DatasetAst, DatasetColumnProfile } from '@/lib/api';

const ROLE_STYLES: Record<DatasetColumnProfile['role'], string> = {
  measure: 'bg-success/10 text-success',
  dimension: 'bg-amber-100 text-amber-800',
  time: 'bg-sky-100 text-sky-700',
  id: 'bg-slate-100 text-slate-600',
  metadata: 'bg-slate-100 text-slate-500',
};

const ROLE_BAR_COLORS: Record<DatasetColumnProfile['role'], string> = {
  measure: 'bg-success/60',
  dimension: 'bg-warning/60',
  time: 'bg-primary/60',
  id: 'bg-border',
  metadata: 'bg-border',
};

function RoleChip({ role }: { role: DatasetColumnProfile['role'] }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize',
        ROLE_STYLES[role]
      )}
    >
      {role}
    </span>
  );
}

function NullBar({ pct }: { pct: number }) {
  if (pct <= 0) return <span className="text-[10px] text-text-muted">—</span>;
  return (
    <div className="flex items-center gap-1">
      <div className="h-1 w-10 overflow-hidden rounded-full bg-border/30">
        <div className={cn('h-full rounded-full', pct > 0.5 ? 'bg-danger/60' : pct > 0.1 ? 'bg-warning/60' : 'bg-text-muted/30')} style={{ width: `${Math.round(pct * 100)}%` }} />
      </div>
      <span className={cn('text-[10px] tabular-nums', pct > 0.5 ? 'text-danger' : pct > 0.1 ? 'text-warning' : 'text-text-muted')}>
        {Math.round(pct * 100)}%
      </span>
    </div>
  );
}

function formatSamples(values: unknown[]): string {
  if (!values?.length) return '—';
  return values
    .slice(0, 3)
    .map((v) => (v === null || v === undefined ? '∅' : String(v)))
    .join(', ');
}

interface DatasetProfileCardProps {
  dataset: DatasetAst;
  className?: string;
}

/** Compact, scannable summary of the profiled dataset (datasetAST). */
export function DatasetProfileCard({ dataset, className }: DatasetProfileCardProps) {
  const cols = dataset.columns;
  const measures = cols.filter((c) => c.role === 'measure');
  const dimensions = cols.filter((c) => c.role === 'dimension');
  const timeColumns = cols.filter((c) => c.role === 'time');
  const metaCols = cols.filter((c) => c.role === 'metadata' || c.role === 'id');
  const highNullCols = cols.filter((c) => c.nullPct > 0.3);
  const total = cols.length || 1;

  return (
    <div className={cn('rounded-xl border border-border bg-surface-card shadow-sm', className)}>
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-border px-5 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Database className="h-4.5 w-4.5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-text">{dataset.sourceFile || dataset.datasetId}</h3>
          <p className="text-xs text-text-muted">Profiled dataset · {dataset.archetype || 'generic'} archetype</p>
        </div>
        <Badge variant="muted" className="text-[9px]">{dataset.rowCount.toLocaleString()} rows</Badge>
      </div>

      {/* Role distribution bar */}
      <div className="px-5 py-3">
        <div className="flex items-center gap-2 text-[10px] text-text-muted">
          <span className="font-semibold text-text">{cols.length} columns</span>
          <div className="flex h-2 flex-1 overflow-hidden rounded-full">
            {measures.length > 0 && <span className={ROLE_BAR_COLORS.measure} style={{ width: `${(measures.length / total) * 100}%` }} title={`${measures.length} measures`} />}
            {dimensions.length > 0 && <span className={ROLE_BAR_COLORS.dimension} style={{ width: `${(dimensions.length / total) * 100}%` }} title={`${dimensions.length} dimensions`} />}
            {timeColumns.length > 0 && <span className={ROLE_BAR_COLORS.time} style={{ width: `${(timeColumns.length / total) * 100}%` }} title={`${timeColumns.length} time`} />}
            {metaCols.length > 0 && <span className={ROLE_BAR_COLORS.metadata} style={{ width: `${(metaCols.length / total) * 100}%` }} title={`${metaCols.length} metadata`} />}
          </div>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-3 text-[10px] text-text-muted">
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-success/60" />{measures.length} measures</span>
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-warning/60" />{dimensions.length} dimensions</span>
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-primary/60" />{timeColumns.length} time</span>
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-border" />{metaCols.length} metadata</span>
          {highNullCols.length > 0 && (
            <span className="flex items-center gap-1 text-warning"><AlertTriangle className="h-3 w-3" />{highNullCols.length} high-null</span>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-2 border-t border-border px-5 py-3">
        <div className="text-center">
          <p className="text-lg font-bold text-text">{measures.length}</p>
          <p className="text-[10px] uppercase text-text-muted">Measures</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-text">{dimensions.length}</p>
          <p className="text-[10px] uppercase text-text-muted">Dimensions</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-text">{timeColumns.length}</p>
          <p className="text-[10px] uppercase text-text-muted">Time</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-text">{dataset.columnGroups?.length ?? 0}</p>
          <p className="text-[10px] uppercase text-text-muted">Groups</p>
        </div>
      </div>

      {/* Column groups */}
      {dataset.columnGroups && dataset.columnGroups.length > 0 && (
        <div className="border-t border-border px-5 py-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-text-muted">Column groups</p>
          <div className="flex flex-wrap gap-2">
            {dataset.columnGroups.map((g) => (
              <div key={g.stem} className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs">
                <span className="font-semibold text-text">{g.stem}</span>
                <Badge variant="muted" className="ml-1.5 text-[8px]">{g.kind}</Badge>
                <span className="ml-1 text-text-muted">({g.members.length})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Column table */}
      <div className="max-h-[26rem] overflow-y-auto border-t border-border px-2 pb-3">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-surface-card">
            <tr className="text-left text-[10px] uppercase tracking-wide text-text-muted">
              <th className="px-3 py-2 font-medium">Column</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium text-right">Cardinality</th>
              <th className="px-3 py-2 font-medium">Null %</th>
              <th className="px-3 py-2 font-medium">Samples</th>
            </tr>
          </thead>
          <tbody>
            {cols.map((col) => (
              <tr key={col.name} className="border-t border-border/50 align-top hover:bg-surface/50">
                <td className="px-3 py-2">
                  <p className="font-mono text-xs font-medium text-text">{col.name}</p>
                  <p className="mt-0.5 text-[10px] text-text-muted">{col.dtype}</p>
                </td>
                <td className="px-3 py-2">
                  <RoleChip role={col.role} />
                </td>
                <td className="px-3 py-2 text-right">
                  <span className="tabular-nums text-xs text-text-muted">{col.cardinality.toLocaleString()}</span>
                </td>
                <td className="px-3 py-2">
                  <NullBar pct={col.nullPct} />
                </td>
                <td className="max-w-[10rem] px-3 py-2">
                  <p className="truncate text-[10px] text-text-muted">{formatSamples(col.sampleValues)}</p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default DatasetProfileCard;
