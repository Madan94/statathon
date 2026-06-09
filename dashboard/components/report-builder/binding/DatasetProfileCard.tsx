'use client';

import { Database } from 'lucide-react';
import { cn } from '@/lib/cn';
import type { DatasetAst, DatasetColumnProfile } from '@/lib/api';

const ROLE_STYLES: Record<DatasetColumnProfile['role'], string> = {
  measure: 'bg-primary/10 text-primary',
  dimension: 'bg-amber-100 text-amber-800',
  time: 'bg-sky-100 text-sky-700',
  id: 'bg-slate-100 text-slate-600',
  metadata: 'bg-slate-100 text-slate-500',
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

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-text">{value}</p>
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
  return (
    <div className={cn('rounded-xl border border-border bg-surface-card shadow-sm', className)}>
      <div className="flex items-center gap-2.5 border-b border-border px-5 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Database className="h-4.5 w-4.5" aria-hidden />
        </span>
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-text">{dataset.sourceFile || dataset.datasetId}</h3>
          <p className="text-xs text-text-muted">Profiled dataset</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 px-5 py-4">
        <Stat label="Rows" value={dataset.rowCount.toLocaleString()} />
        <Stat label="Columns" value={dataset.columns.length} />
        <Stat label="Archetype" value={<span className="capitalize">{dataset.archetype.replace(/_/g, ' ')}</span>} />
      </div>

      <div className="max-h-[22rem] overflow-y-auto px-2 pb-3">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-surface-card">
            <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted">
              <th className="px-3 py-2 font-medium">Column</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Samples</th>
            </tr>
          </thead>
          <tbody>
            {dataset.columns.map((col) => (
              <tr key={col.name} className="border-t border-border/70 align-top">
                <td className="px-3 py-2">
                  <p className="font-mono text-xs font-medium text-text">{col.name}</p>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    {col.dtype} · {col.cardinality.toLocaleString()} uniq
                    {col.nullPct > 0 ? ` · ${Math.round(col.nullPct * 100)}% null` : ''}
                  </p>
                </td>
                <td className="px-3 py-2">
                  <RoleChip role={col.role} />
                </td>
                <td className="px-3 py-2">
                  <p className="line-clamp-2 text-xs text-text-muted">{formatSamples(col.sampleValues)}</p>
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
