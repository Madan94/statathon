'use client';

import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import Card from '@/components/ui/Card';
import ConfidenceScore from '@/components/ConfidenceScore';
import { SemanticMappingRow } from '@/lib/api';
import EmptyState from '@/components/ui/EmptyState';
import { GitBranch } from 'lucide-react';

interface SemanticTableProps {
  rows: SemanticMappingRow[];
  clusters?: Array<Record<string, unknown>>;
  graphEdges?: Array<{ source?: string; target?: string; weight?: number }>;
}

export default function SemanticTable({ rows, clusters = [], graphEdges = [] }: SemanticTableProps) {
  const [search, setSearch] = useState('');
  const [edgeSearch, setEdgeSearch] = useState('');

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.column.toLowerCase().includes(q) ||
        String(r.domain || '').toLowerCase().includes(q)
    );
  }, [rows, search]);

  const filteredEdges = useMemo(() => {
    const q = edgeSearch.toLowerCase();
    if (!q) return graphEdges;
    return graphEdges.filter(
      (e) =>
        String(e.source || '').toLowerCase().includes(q) ||
        String(e.target || '').toLowerCase().includes(q)
    );
  }, [graphEdges, edgeSearch]);

  if (!rows.length && !clusters.length && !graphEdges.length) {
    return (
      <EmptyState
        icon={GitBranch}
        title="No semantic mapping yet"
        description="Run analysis to generate domain mappings and schema graph."
      />
    );
  }

  return (
    <div className="space-y-6">
      {rows.length > 0 && (
        <Card title="Column → domain mapping">
          <div className="relative mb-4">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" aria-hidden />
            <input
              type="search"
              placeholder="Search columns or domains…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-3 py-2 text-sm rounded-lg border border-border bg-surface focus:ring-2 focus:ring-accent/40"
              aria-label="Search semantic mappings"
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
                  <th className="pb-2 pr-4 font-medium">Column</th>
                  <th className="pb-2 pr-4 font-medium">Domain</th>
                  <th className="pb-2 font-medium w-32">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr key={row.column} className="border-b border-border/60 last:border-0">
                    <td className="py-3 pr-4 font-mono text-text">{row.column}</td>
                    <td className="py-3 pr-4 text-text-muted">{row.domain || '—'}</td>
                    <td className="py-3">
                      {typeof row.confidence === 'number' ? (
                        <ConfidenceScore score={row.confidence} size="sm" />
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {clusters.length > 0 && (
        <Card title="Semantic clusters">
          <div className="flex flex-wrap gap-2">
            {clusters.map((cluster, idx) => (
              <div
                key={String(cluster.cluster_id ?? idx)}
                className="rounded-lg border border-border px-3 py-2 text-sm max-w-full"
              >
                <span className="font-medium text-primary">
                  {String(cluster.cluster_id ?? `cluster_${idx}`)}
                </span>
                <span className="text-text-muted"> · {String(cluster.domain ?? '')}</span>
                <p className="text-xs text-text-muted mt-1 truncate">
                  {Array.isArray(cluster.columns)
                    ? (cluster.columns as string[]).join(', ')
                    : '—'}
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {graphEdges.length > 0 && (
        <Card title={`Schema graph (${graphEdges.length} edges)`}>
          <input
            type="search"
            placeholder="Filter edges…"
            value={edgeSearch}
            onChange={(e) => setEdgeSearch(e.target.value)}
            className="w-full mb-3 px-3 py-2 text-sm rounded-lg border border-border bg-surface focus:ring-2 focus:ring-accent/40"
            aria-label="Filter schema edges"
          />
          <ul className="text-sm space-y-1 max-h-64 overflow-auto font-mono">
            {filteredEdges.slice(0, 50).map((e, i) => (
              <li key={i} className="text-text-muted py-1 border-b border-border/40 last:border-0">
                {e.source} → {e.target}
                {e.weight != null ? ` (${Number(e.weight).toFixed(2)})` : ''}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
