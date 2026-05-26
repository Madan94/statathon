'use client';

import { useState } from 'react';
import type { AnalysisResult, AnomalyCandidate, ImputationCandidate, ColumnProfile } from '@/lib/api';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import { Search, ChevronLeft, TrendingUp, Minus } from 'lucide-react';

interface Props {
  results: AnalysisResult;
  selectedColumn: string | null;
  onSelectColumn: (col: string) => void;
  onBack: () => void;
}

function columnRisk(
  col: string,
  anomalyCandidates: AnomalyCandidate[],
  imputationCandidates: ImputationCandidate[],
  health?: { missing_per_column?: Record<string, number>; rows?: number }
): 'high' | 'medium' | 'low' | 'none' {
  const anomalies = anomalyCandidates.filter((c) => c.column === col);
  const highAnomaly = anomalies.some((a) => a.severity.toLowerCase() === 'high');
  const hasAnomaly = anomalies.length > 0;
  const missingCount = health?.missing_per_column?.[col] ?? 0;
  const totalRows = health?.rows ?? 1;
  const missingPct = missingCount / totalRows;

  if (highAnomaly || missingPct > 0.3) return 'high';
  if (hasAnomaly || missingPct > 0.1) return 'medium';
  if (anomalies.length > 0 || missingPct > 0) return 'low';
  return 'none';
}

const riskBadge: Record<string, 'danger' | 'warning' | 'muted' | 'success'> = {
  high: 'danger',
  medium: 'warning',
  low: 'muted',
  none: 'success',
};

const riskDot: Record<string, string> = {
  high: 'bg-danger',
  medium: 'bg-warning',
  low: 'bg-text-muted',
  none: 'bg-success',
};

export default function ColumnNav({ results, selectedColumn, onSelectColumn, onBack }: Props) {
  const [query, setQuery] = useState('');

  const health = results.health as {
    missing_per_column?: Record<string, number>;
    rows?: number;
    dtypes?: Record<string, string>;
  } | undefined;

  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};
  const allColumns = Object.keys(columnProfiles ?? schema);

  const anomalyCandidates = (
    (results.phase3 as { anomaly_candidates?: AnomalyCandidate[] } | undefined)
      ?.anomaly_candidates ?? []
  );
  const imputationCandidates = (
    (results.phase3 as { imputation_candidates?: ImputationCandidate[] } | undefined)
      ?.imputation_candidates ?? []
  );

  const filteredColumns = allColumns.filter((c) =>
    c.toLowerCase().includes(query.toLowerCase())
  );

  // Group by semantic domain
  const domainMap: Record<string, string> = {};
  results.semantic_mapping?.forEach((row) => {
    if (row.domain) domainMap[row.column] = row.domain;
  });

  const domains = [...new Set(Object.values(domainMap))].sort();
  const undomained = filteredColumns.filter((c) => !domainMap[c]);

  function renderColumn(col: string) {
    const risk = columnRisk(col, anomalyCandidates, imputationCandidates, health);
    const missingCount = health?.missing_per_column?.[col] ?? 0;
    const totalRows = health?.rows ?? 1;
    const missingPct = missingCount / totalRows;
    const anomalyCount = anomalyCandidates.filter((c) => c.column === col).length;
    const isSelected = col === selectedColumn;

    return (
      <button
        key={col}
        type="button"
        onClick={() => onSelectColumn(col)}
        className={cn(
          'w-full text-left px-3 py-2.5 rounded-lg transition-all group',
          isSelected
            ? 'bg-accent/10 border border-accent/30'
            : 'hover:bg-border/40 border border-transparent'
        )}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={cn('h-2 w-2 rounded-full shrink-0', riskDot[risk])} />
          <span
            className={cn(
              'text-xs font-mono truncate flex-1',
              isSelected ? 'text-primary font-semibold' : 'text-text'
            )}
          >
            {col}
          </span>
        </div>
        <div className="flex items-center gap-1.5 mt-1 ml-4">
          {anomalyCount > 0 && (
            <span className="flex items-center gap-0.5 text-[10px] text-warning">
              <TrendingUp className="h-3 w-3" />
              {anomalyCount}
            </span>
          )}
          {missingPct > 0 && (
            <span className="flex items-center gap-0.5 text-[10px] text-text-muted">
              <Minus className="h-3 w-3" />
              {(missingPct * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </button>
    );
  }

  return (
    <aside className="w-56 lg:w-64 shrink-0 flex flex-col border-r border-border bg-surface-card h-full overflow-hidden">
      {/* Back */}
      <div className="p-3 border-b border-border">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text transition-colors w-full"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          Back to pipeline
        </button>
      </div>

      {/* Search */}
      <div className="p-3 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-muted" />
          <input
            type="search"
            placeholder="Search columns…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-lg border border-border bg-surface pl-7 pr-2 py-1.5 text-xs placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      </div>

      {/* Legend */}
      <div className="px-3 py-2 border-b border-border flex items-center gap-3 text-[10px] text-text-muted">
        {[
          { label: 'High', cls: 'bg-danger' },
          { label: 'Med', cls: 'bg-warning' },
          { label: 'Low', cls: 'bg-text-muted' },
          { label: 'OK', cls: 'bg-success' },
        ].map(({ label, cls }) => (
          <span key={label} className="flex items-center gap-1">
            <span className={cn('h-2 w-2 rounded-full', cls)} />
            {label}
          </span>
        ))}
      </div>

      {/* Column list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-3">
        {domains.length > 0 ? (
          <>
            {domains.map((domain) => {
              const domainCols = filteredColumns.filter((c) => domainMap[c] === domain);
              if (domainCols.length === 0) return null;
              return (
                <div key={domain}>
                  <p className="px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                    {domain}
                  </p>
                  {domainCols.map(renderColumn)}
                </div>
              );
            })}
            {undomained.length > 0 && (
              <div>
                <p className="px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                  Other
                </p>
                {undomained.map(renderColumn)}
              </div>
            )}
          </>
        ) : (
          filteredColumns.map(renderColumn)
        )}
      </div>

      {/* Footer counts */}
      <div className="p-3 border-t border-border text-[10px] text-text-muted">
        {allColumns.length} column{allColumns.length !== 1 ? 's' : ''} total ·{' '}
        {anomalyCandidates.length} anomal{anomalyCandidates.length !== 1 ? 'ies' : 'y'} ·{' '}
        {imputationCandidates.length} missing
      </div>
    </aside>
  );
}
