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

export default function Step1Summary({ results, onProceed }: Props) {
  const health = results.health as {
    rows?: number;
    columns?: number;
    missing_per_column?: Record<string, number>;
    dtypes?: Record<string, string>;
  } | undefined;

  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};
  const allColumns = Object.keys(columnProfiles ?? schema);
  const missingPerCol = health?.missing_per_column ?? {};
  const totalRows = health?.rows ?? 0;
  const totalCols = health?.columns ?? allColumns.length;

  const overallMissingPct =
    totalRows > 0 && allColumns.length > 0
      ? (Object.values(missingPerCol).reduce((a, b) => a + b, 0) /
          (allColumns.length * totalRows)) *
        100
      : 0;
  const highMissingCols = allColumns.filter(
    (c) => (missingPerCol[c] ?? 0) / Math.max(totalRows, 1) > 0.2
  );
  const numericCols = allColumns.filter(
    (c) =>
      schema[c] === 'numeric' ||
      columnProfiles?.[c]?.datatype?.includes('int') ||
      columnProfiles?.[c]?.datatype?.includes('float')
  );
  const datasetType =
    (results.dataset_context as { dataset_type?: string } | undefined)?.dataset_type ?? '—';

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
          </div>
          {results.dataset_context &&
            Object.entries(results.dataset_context as Record<string, unknown>)
              .filter(([k, v]) => k !== 'dataset_type' && typeof v !== 'object' && v != null)
              .slice(0, 6)
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
        description="Every column in the uploaded file — type, completeness, cardinality and top values."
      >
        <div className="overflow-x-auto -mx-6">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="border-b border-border">
                {[
                  'Column',
                  'Type',
                  'Missing',
                  'Cardinality',
                  'Range / top values',
                  'Semantic domain',
                ].map((h) => (
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
                const profile = columnProfiles?.[col];
                const missing = missingPerCol[col] ?? 0;
                const ratio =
                  totalRows > 0 ? missing / totalRows : profile?.missing_ratio ?? 0;
                const colType = schema[col] ?? profile?.datatype ?? '—';
                const semRow = results.semantic_mapping?.find((r) => r.column === col);

                let sampleStr = '—';
                if (profile?.mean_std) {
                  sampleStr = `μ=${profile.mean_std.mean.toFixed(2)}, σ=${profile.mean_std.std.toFixed(2)}`;
                  if (profile.min_max) {
                    sampleStr += ` [${profile.min_max.min}, ${profile.min_max.max}]`;
                  }
                } else if (profile?.top_values?.length) {
                  sampleStr = profile.top_values
                    .slice(0, 3)
                    .map(([v, n]) => `${v} (${n})`)
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
                    <td className="px-4 py-3 text-xs text-text-muted max-w-[220px] truncate">
                      {sampleStr}
                    </td>
                    <td className="px-4 py-3">
                      {semRow?.domain ? (
                        <span className="text-xs font-semibold text-primary">{semRow.domain}</span>
                      ) : (
                        <span className="text-xs text-text-muted">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Health alerts */}
      {highMissingCols.length > 0 && (
        <Card className="border-warning/30 bg-warning/5">
          <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-text">High-missing columns detected</p>
              <p className="text-sm text-text-muted mt-1">
                {highMissingCols.join(', ')} have &gt;20% missing values. Consider imputation or
                exclusion in the next steps.
              </p>
            </div>
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
