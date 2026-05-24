'use client';

import { useMemo, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import EmptyState from '@/components/ui/EmptyState';
import { ValidationCandidate } from '@/lib/api';

interface ValidationTableProps {
  candidates: ValidationCandidate[];
}

export default function ValidationTable({ candidates }: ValidationTableProps) {
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [columnFilter, setColumnFilter] = useState('');

  const severities = useMemo(() => {
    const set = new Set(candidates.map((c) => c.severity || 'REVIEW'));
    return ['all', ...Array.from(set)];
  }, [candidates]);

  const filtered = useMemo(() => {
    return candidates.filter((c) => {
      if (severityFilter !== 'all' && (c.severity || 'REVIEW') !== severityFilter) return false;
      if (columnFilter && !(c.column || '').toLowerCase().includes(columnFilter.toLowerCase())) {
        return false;
      }
      return true;
    });
  }, [candidates, severityFilter, columnFilter]);

  if (!candidates.length) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="No validation issues flagged"
        description="Rule validation found no candidates requiring review."
      />
    );
  }

  return (
    <Card title={`Rule validation (${candidates.length})`} description="Review flagged cells before applying decisions">
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="text-sm rounded-lg border border-border px-3 py-2 bg-surface-card"
          aria-label="Filter by severity"
        >
          {severities.map((s) => (
            <option key={s} value={s}>
              {s === 'all' ? 'All severities' : s}
            </option>
          ))}
        </select>
        <input
          type="search"
          placeholder="Filter by column…"
          value={columnFilter}
          onChange={(e) => setColumnFilter(e.target.value)}
          className="text-sm rounded-lg border border-border px-3 py-2 flex-1 min-w-[160px] bg-surface-card"
          aria-label="Filter by column"
        />
      </div>
      <div className="overflow-x-auto max-h-96">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
              <th className="pb-2 pr-3">Column</th>
              <th className="pb-2 pr-3">Severity</th>
              <th className="pb-2 pr-3">Kind</th>
              <th className="pb-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 100).map((c, i) => (
              <tr key={i} className="border-b border-border/60">
                <td className="py-2 pr-3 font-medium">{c.column || '—'}</td>
                <td className="py-2 pr-3">
                  <Badge variant="warning">{c.severity || 'REVIEW'}</Badge>
                </td>
                <td className="py-2 pr-3 text-text-muted">{c.kind || 'validation'}</td>
                <td className="py-2 text-text-muted">
                  {c.candidate_action || 'REVIEW'}
                  {c.row != null ? ` · row ${c.row}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
