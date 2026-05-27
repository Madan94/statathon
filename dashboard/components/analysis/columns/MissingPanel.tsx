'use client';

import { useState } from 'react';
import type { AnalysisResult, ImputationCandidate } from '@/lib/api';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';
import { CheckCircle2, Minus, BarChart2, Info } from 'lucide-react';

interface Props {
  column: string;
  results: AnalysisResult;
  className?: string;
}

const METHOD_DESCRIPTIONS: Record<string, string> = {
  mean: 'Replace missing values with the column mean. Good for symmetric, low-skew distributions.',
  median: 'Replace with the median. Robust to outliers and skewed data.',
  mode: 'Replace with the most frequent value. Suited to low-cardinality or categorical columns.',
  knn: 'k-Nearest Neighbour imputation — uses similar rows to estimate missing values. Slow but accurate.',
  ffill: 'Forward-fill: carry the last known value forward. Best for ordered time-series data.',
  bfill: 'Backward-fill: use the next known value. Best for ordered time-series data.',
};

function confidenceVariant(c: number): 'success' | 'warning' | 'danger' | 'muted' {
  if (c >= 0.8) return 'success';
  if (c >= 0.5) return 'warning';
  if (c > 0) return 'danger';
  return 'muted';
}

export default function MissingPanel({ column, results, className }: Props) {
  const impCandidates = (
    (results.phase3 as { imputation_candidates?: ImputationCandidate[] } | undefined)
      ?.imputation_candidates ?? []
  );
  const candidate = impCandidates.find((c) => c.column === column);

  // Also check health-based missing count
  const health = results.health as {
    rows?: number;
    missing_per_column?: Record<string, number>;
  } | undefined;
  const missingCount =
    candidate?.missing_count ?? health?.missing_per_column?.[column] ?? 0;
  const totalRows = health?.rows ?? 0;
  const missingPct = totalRows > 0 ? (missingCount / totalRows) * 100 : 0;

  const [selectedMethod, setSelectedMethod] = useState<string | null>(
    candidate?.recommended_method ?? null
  );

  if (!candidate && missingCount === 0) {
    return (
      <Card className={cn('border-success/30 bg-success/5', className)}>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-6 w-6 text-success shrink-0" />
          <div>
            <p className="font-semibold text-text">No missing values</p>
            <p className="text-sm text-text-muted mt-0.5">
              <strong>{column}</strong> is complete — 0 missing rows.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const methodScores = (candidate?.method_scores as Record<string, number> | undefined) ?? {};

  return (
    <Card title="Missing Values" className={className}>
      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="rounded-lg border border-border bg-surface p-3">
          <div className="flex items-center gap-2">
            <Minus className="h-5 w-5 text-warning" />
            <div>
              <p className="text-xl font-bold text-text">{missingCount.toLocaleString()}</p>
              <p className="text-xs text-text-muted">Missing rows</p>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-3">
          <div className="flex items-center gap-2">
            <BarChart2 className="h-5 w-5 text-primary" />
            <div>
              <p className="text-xl font-bold text-text">{missingPct.toFixed(1)}%</p>
              <p className="text-xs text-text-muted">Missing ratio</p>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-3">
          <div>
            <p className="text-xl font-bold text-text">
              {candidate?.confidence != null ? `${(candidate.confidence * 100).toFixed(0)}%` : '—'}
            </p>
            <p className="text-xs text-text-muted">Rec. confidence</p>
          </div>
        </div>
      </div>

      {/* Missing bar */}
      <div className="mb-6">
        <div className="flex justify-between text-xs text-text-muted mb-1">
          <span>Completeness</span>
          <span>{(100 - missingPct).toFixed(1)}% present</span>
        </div>
        <div className="h-3 rounded-full bg-border overflow-hidden">
          <div
            className={cn(
              'h-full rounded-full transition-all',
              missingPct > 30 ? 'bg-danger' : missingPct > 10 ? 'bg-warning' : 'bg-success'
            )}
            style={{ width: `${100 - missingPct}%` }}
          />
        </div>
      </div>

      {/* Imputation method selection */}
      <div className="space-y-3 mb-4">
        <p className="text-sm font-semibold text-text">
          Select imputation method
          {candidate?.recommended_method && (
            <span className="ml-2 text-xs font-normal text-text-muted">
              (pipeline recommends:{' '}
              <strong className="text-primary">{candidate.recommended_method}</strong>)
            </span>
          )}
        </p>

        <div className="space-y-2">
          {/* Show all available methods: from method_scores or a default set */}
          {(Object.keys(methodScores).length > 0
            ? Object.entries(methodScores).sort(([, a], [, b]) => b - a)
            : (['mean', 'median', 'mode', 'knn'] as const).map((m) => [m, 0] as [string, number])
          ).map(([method, score]) => {
            const isRecommended = method === candidate?.recommended_method;
            const isSelected = selectedMethod === method;
            const pctScore = typeof score === 'number' ? score * 100 : 0;

            return (
              <button
                key={method}
                type="button"
                onClick={() => setSelectedMethod(method)}
                className={cn(
                  'w-full text-left rounded-xl border p-3 transition-all',
                  isSelected
                    ? 'border-accent bg-accent/10'
                    : 'border-border bg-surface hover:bg-border/40'
                )}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className={cn('text-sm font-semibold capitalize', isSelected && 'text-primary')}>
                      {method}
                    </span>
                    {isRecommended && (
                      <Badge variant="success" className="text-[10px]">
                        Recommended
                      </Badge>
                    )}
                    {isSelected && (
                      <Badge variant="default" className="text-[10px]">
                        ✓ Selected
                      </Badge>
                    )}
                  </div>
                  {pctScore > 0 && (
                    <Badge variant={confidenceVariant(score as number)}>
                      {pctScore.toFixed(0)}%
                    </Badge>
                  )}
                </div>
                {/* Score bar */}
                {pctScore > 0 && (
                  <div className="w-full h-1.5 rounded-full bg-border overflow-hidden mb-1.5">
                    <div
                      className={cn(
                        'h-full rounded-full',
                        (score as number) >= 0.8 ? 'bg-success' : (score as number) >= 0.5 ? 'bg-warning' : 'bg-danger'
                      )}
                      style={{ width: `${pctScore}%` }}
                    />
                  </div>
                )}
                <p className="text-xs text-text-muted">
                  {METHOD_DESCRIPTIONS[method] ?? 'Imputation method.'}
                </p>
              </button>
            );
          })}
        </div>
      </div>

      {/* Guidance note */}
      {missingPct > 30 && (
        <div className="flex items-start gap-2 rounded-lg bg-warning/10 border border-warning/30 p-3 text-sm">
          <Info className="h-4 w-4 text-warning shrink-0 mt-0.5" />
          <p className="text-text-muted">
            Over 30% of values are missing. Consider whether to impute or exclude this column
            during normalisation.
          </p>
        </div>
      )}

      {/* Apply */}
      <div className="mt-4 flex items-center gap-3">
        <Button
          disabled={!selectedMethod}
          variant="primary"
          className="flex items-center gap-1.5"
          onClick={() => {
            /* Decisions are stored upstream; this button is a visual confirm. */
          }}
        >
          <CheckCircle2 className="h-4 w-4" />
          Confirm: {selectedMethod ?? 'choose a method'}
        </Button>
        {selectedMethod && (
          <p className="text-xs text-text-muted">
            Method recorded — will be applied when you export or apply decisions.
          </p>
        )}
      </div>
    </Card>
  );
}
