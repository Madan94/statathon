'use client';

import { AnalysisResult, ColumnProfile } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import {
  Download,
  Database,
  Hash,
  AlertTriangle,
  CheckCircle2,
  TrendingUp,
  BarChart2,
} from 'lucide-react';

interface Props {
  results: AnalysisResult;
  onProceed: () => void;
}

function downloadJSON(obj: unknown, name: string) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function missingVariant(ratio: number): 'success' | 'muted' | 'warning' | 'danger' {
  if (ratio > 0.3) return 'danger';
  if (ratio > 0.1) return 'warning';
  if (ratio > 0) return 'muted';
  return 'success';
}

function typeVariant(t: string): 'default' | 'muted' {
  return t === 'numeric' || t === 'float64' || t === 'int64' ? 'default' : 'muted';
}

function snakeKey(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^\w]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '');
}

function lookupBySnake<T>(map: Record<string, T>, col: string): T | undefined {
  if (map[col] != null) return map[col];
  const target = snakeKey(col);
  for (const [key, value] of Object.entries(map)) {
    if (snakeKey(key) === target) return value;
  }
  return undefined;
}

/** Backend sends [{ value, count }] — tolerate legacy [value, count] tuples too. */
function formatTopValues(raw: ColumnProfile['top_values']): string {
  if (!raw?.length) return '—';
  return raw
    .slice(0, 3)
    .map((entry) => {
      if (Array.isArray(entry)) {
        const [v, n] = entry;
        return `${v} (${n})`;
      }
      if (entry && typeof entry === 'object' && 'value' in entry && 'count' in entry) {
        return `${entry.value} (${entry.count})`;
      }
      return String(entry);
    })
    .join(', ');
}

export default function Step1Summary({ results, onProceed }: Props) {
  const profilingSummary = results.profiling_summary as
    | {
        health?: {
          rows?: number;
          columns?: number;
          missing_per_column?: Record<string, number>;
          dtypes?: Record<string, string>;
        };
        schema?: Record<string, string>;
        column_profiles?: Record<string, ColumnProfile>;
      }
    | undefined;

  const health = (results.health ??
    profilingSummary?.health) as {
    rows?: number;
    columns?: number;
    missing_per_column?: Record<string, number>;
    dtypes?: Record<string, string>;
  } | undefined;

  const columnProfiles = (results.column_profiles ??
    profilingSummary?.column_profiles) as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? profilingSummary?.schema ?? {};
  const missingPerCol = health?.missing_per_column ?? {};
  const dtypes = (health?.dtypes as Record<string, string> | undefined) ?? {};
  const allColumns = Array.from(
    new Set([
      ...Object.keys(columnProfiles ?? {}),
      ...Object.keys(schema),
      ...Object.keys(missingPerCol),
      ...Object.keys(dtypes),
    ])
  ).sort((a, b) => a.localeCompare(b));
  const totalRows = health?.rows ?? 0;
  const totalCols = health?.columns ?? allColumns.length;

  function resolveProfile(col: string): ColumnProfile | undefined {
    const direct = lookupBySnake(columnProfiles ?? {}, col);
    if (direct) return direct;
    const normRows = results.column_normalization ?? [];
    for (const row of normRows) {
      if (!row || typeof row !== 'object') continue;
      const orig = String(row.original_name ?? '');
      const canon = String(row.canonical_name ?? row.normalized_name ?? '');
      if (orig && lookupBySnake(columnProfiles ?? {}, orig)) {
        return lookupBySnake(columnProfiles ?? {}, orig);
      }
      if (canon && lookupBySnake(columnProfiles ?? {}, canon)) {
        return lookupBySnake(columnProfiles ?? {}, canon);
      }
      if (snakeKey(orig) === snakeKey(col) && lookupBySnake(columnProfiles ?? {}, orig)) {
        return lookupBySnake(columnProfiles ?? {}, orig);
      }
      if (snakeKey(canon) === snakeKey(col) && lookupBySnake(columnProfiles ?? {}, canon)) {
        return lookupBySnake(columnProfiles ?? {}, canon);
      }
    }
    return undefined;
  }

  function missingCount(col: string): number {
    const fromHealth = lookupBySnake(missingPerCol, col);
    if (fromHealth != null && fromHealth >= 0) return fromHealth;
    const profile = resolveProfile(col);
    if (profile?.missing_count != null) return Number(profile.missing_count);
    if (profile?.missing_ratio != null && totalRows > 0) {
      return Math.round(Number(profile.missing_ratio) * totalRows);
    }
    return 0;
  }

  function columnType(col: string): string {
    const profile = resolveProfile(col);
    return (
      lookupBySnake(schema, col) ??
      profile?.datatype ??
      lookupBySnake(dtypes, col) ??
      '—'
    );
  }

  const overallMissingPct =
    totalRows > 0 && allColumns.length > 0
      ? (allColumns.reduce((sum, c) => sum + missingCount(c), 0) /
          (allColumns.length * totalRows)) *
        100
      : 0;

  const highMissingCols = allColumns.filter(
    (c) => missingCount(c) / Math.max(totalRows, 1) > 0.2
  );
  const highMissingRows = highMissingCols
    .map((col) => {
      const missing = missingCount(col);
      const ratio = totalRows > 0 ? missing / totalRows : 0;
      return {
        col,
        missing,
        ratio,
        type: columnType(col),
        severity: ratio > 0.3 ? ('critical' as const) : ('elevated' as const),
      };
    })
    .sort((a, b) => b.ratio - a.ratio);
  const numericCols = allColumns.filter(
    (c) => {
      const profile = resolveProfile(c);
      return (
        schema[c] === 'numeric' ||
        profile?.datatype?.includes('int') ||
        profile?.datatype?.includes('float') ||
        profile?.datatype === 'numeric'
      );
    }
  );
  const datasetType =
    (results.dataset_context as { dataset_type?: string; usecase?: string } | undefined)
      ?.dataset_type ||
    (results.dataset_context as { usecase?: string } | undefined)?.usecase ||
    '—';
  const ontologyHint = (results.dataset_context as { ontology_macro_type_best_hint?: string } | undefined)
    ?.ontology_macro_type_best_hint;

  const summaryBlob = {
    dataset_type: datasetType,
    rows: totalRows,
    columns: totalCols,
    overall_missing_pct: overallMissingPct.toFixed(2),
    high_missing_columns: highMissingCols,
    column_types: schema,
    missing_per_column: missingPerCol,
    column_profiles: columnProfiles,
    semantic_mapping: results.semantic_mapping,
  };

  return (
    <div className="space-y-6">
      {/* Top stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          {
            icon: Database,
            value: totalRows.toLocaleString(),
            label: 'Rows',
            color: 'text-primary',
          },
          { icon: Hash, value: totalCols, label: 'Columns', color: 'text-primary' },
          {
            icon: AlertTriangle,
            value: `${overallMissingPct.toFixed(1)}%`,
            label: 'Avg. missing',
            color: overallMissingPct > 10 ? 'text-warning' : 'text-success',
          },
          {
            icon: BarChart2,
            value: numericCols.length,
            label: 'Numeric cols',
            color: 'text-primary',
          },
        ].map(({ icon: Icon, value, label, color }) => (
          <Card key={label} className="!p-4">
            <div className="flex items-center gap-3">
              <Icon className={cn('h-9 w-9 shrink-0', color)} />
              <div>
                <p className="text-2xl font-bold text-text">{value}</p>
                <p className="text-xs text-text-muted">{label}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Dataset context */}
      <Card title="Dataset context">
        <div className="flex flex-wrap gap-4">
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wide">Archetype</p>
            <p className="mt-1 font-semibold text-text">{datasetType}</p>
            <p className="mt-1 text-[11px] text-text-muted max-w-xs">
              Semantic pipeline usecase / survey family (embedding or usecase detector).
            </p>
          </div>
          {ontologyHint && (
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wide">Ontology macro hint</p>
              <p className="mt-1 font-medium text-text">{ontologyHint}</p>
              <p className="mt-1 text-[11px] text-text-muted max-w-xs">
                From column-name token match against static MoSPI ontology (profiling).
              </p>
            </div>
          )}
          {results.dataset_context &&
            Object.entries(results.dataset_context as Record<string, unknown>)
              .filter(
                ([k, v]) =>
                  k !== 'dataset_type' &&
                  k !== 'ontology_macro_type_best_hint' &&
                  typeof v !== 'object' &&
                  v != null
              )
              .slice(0, 4)
              .map(([k, v]) => (
                <div key={k}>
                  <p className="text-xs text-text-muted uppercase tracking-wide">
                    {k.replace(/_/g, ' ')}
                  </p>
                  <p className="mt-1 font-medium text-text">{String(v)}</p>
                </div>
              ))}
        </div>
      </Card>

      {/* Column profiles table */}
      <Card
        title="Column profiles"
        description="Every column in the uploaded file — type, completeness, cardinality and sample values. Domain mapping happens in Step 3."
      >
        <div className="overflow-x-auto -mx-6">
          <table className="w-full text-sm min-w-[660px]">
            <thead>
              <tr className="border-b border-border">
                {['Column', 'Type', 'Missing', 'Cardinality', 'Range / top values'].map((h) => (
                  <th
                    key={h}
                    className="px-4 pb-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allColumns.map((col) => {
                const profile = resolveProfile(col);
                const missing = missingCount(col);
                const ratio =
                  totalRows > 0 ? missing / totalRows : profile?.missing_ratio ?? 0;
                const colType = columnType(col);

                // Human-readable stats
                let sampleStr = '—';
                if (profile?.mean_std) {
                  const mean = profile.mean_std.mean;
                  const std = profile.mean_std.std;
                  const fmt = (n: number) =>
                    Math.abs(n) >= 1000
                      ? n.toLocaleString('en-IN', { maximumFractionDigits: 0 })
                      : n.toFixed(2);
                  sampleStr = `μ=${fmt(mean)}, σ=${fmt(std)}`;
                  if (profile.min_max) {
                    sampleStr += ` [${fmt(profile.min_max.min)}, ${fmt(profile.min_max.max)}]`;
                  }
                } else if (profile?.top_values?.length) {
                  sampleStr = formatTopValues(profile.top_values);
                } else if (profile?.sample_values?.length) {
                  sampleStr = profile.sample_values
                    .slice(0, 3)
                    .map((v) => String(v))
                    .join(', ');
                }

                return (
                  <tr
                    key={col}
                    className="border-b border-border/30 hover:bg-surface/60 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-xs font-medium text-text">{col}</td>
                    <td className="px-4 py-3">
                      <Badge variant={typeVariant(colType)}>{colType}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-14 h-1.5 rounded-full bg-border overflow-hidden">
                          <div
                            className={cn(
                              'h-full rounded-full',
                              ratio > 0.3
                                ? 'bg-danger'
                                : ratio > 0.1
                                ? 'bg-warning'
                                : ratio > 0
                                ? 'bg-text-muted'
                                : 'bg-success'
                            )}
                            style={{ width: `${Math.min(ratio * 100, 100)}%` }}
                          />
                        </div>
                        <Badge variant={missingVariant(ratio)}>
                          {(ratio * 100).toFixed(1)}%
                        </Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {profile?.cardinality?.toLocaleString() ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted max-w-[260px]">
                      <span className="truncate block" title={sampleStr}>{sampleStr}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* High-missing columns */}
      {highMissingRows.length > 0 && (
        <Card
          title="High-missing columns"
          description={`${highMissingRows.length} column${highMissingRows.length === 1 ? '' : 's'} exceed 20% missing values. Review before normalisation, imputation, or exclusion.`}
          className="border-warning/40"
        >
          <div className="mb-4 flex items-start gap-3 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3">
            <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" aria-hidden />
            <p className="text-sm text-text-muted">
              These columns may reduce analysis quality. Consider imputation or exclusion in later
              pipeline steps.
            </p>
          </div>
          <div className="overflow-x-auto -mx-6">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-border bg-surface/80">
                  {['Column', 'Type', 'Missing cells', 'Missing %', 'Severity', 'Suggested action'].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {highMissingRows.map(({ col, missing, ratio, type, severity }) => (
                  <tr
                    key={col}
                    className={cn(
                      'border-b border-border/40 transition-colors',
                      severity === 'critical'
                        ? 'bg-danger/[0.04] hover:bg-danger/[0.08]'
                        : 'bg-warning/[0.04] hover:bg-warning/[0.08]',
                    )}
                  >
                    <td className="px-4 py-3 font-mono text-xs font-medium text-text max-w-[220px]">
                      <span className="block truncate" title={col}>
                        {col}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={typeVariant(type)}>{type}</Badge>
                    </td>
                    <td className="px-4 py-3 tabular-nums text-text">
                      {missing.toLocaleString()}
                      <span className="text-text-muted text-xs"> / {totalRows.toLocaleString()}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 min-w-[120px]">
                        <div className="w-16 h-1.5 rounded-full bg-border overflow-hidden shrink-0">
                          <div
                            className={cn(
                              'h-full rounded-full',
                              severity === 'critical' ? 'bg-danger' : 'bg-warning',
                            )}
                            style={{ width: `${Math.min(ratio * 100, 100)}%` }}
                          />
                        </div>
                        <Badge variant={severity === 'critical' ? 'danger' : 'warning'}>
                          {(ratio * 100).toFixed(1)}%
                        </Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={severity === 'critical' ? 'danger' : 'warning'}>
                        {severity === 'critical' ? 'Critical' : 'Elevated'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {ratio > 0.5 ? 'Strong candidate for exclusion' : 'Review imputation or exclude'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button
          variant="outline"
          onClick={() => downloadJSON(summaryBlob, 'dataset_summary.json')}
          className="flex items-center gap-2"
        >
          <Download className="h-4 w-4" aria-hidden />
          Download summary (JSON)
        </Button>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
          <span className="text-sm text-text-muted">Review complete</span>
          <Button onClick={onProceed} size="lg">
            Proceed to Column Normalisation →
          </Button>
        </div>
      </div>
    </div>
  );
}
