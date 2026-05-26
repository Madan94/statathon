'use client';

import { useState, useMemo } from 'react';
import type { AnalysisResult, AnomalyCandidate } from '@/lib/api';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Accordion } from '@/components/ui/Accordion';
import { cn } from '@/lib/cn';
import { Zap, TrendingUp, GitCompare, CheckCircle2, AlertCircle, Info } from 'lucide-react';

interface Props {
  column: string;
  results: AnalysisResult;
  className?: string;
}

type MethodChoice = 'zscore' | 'iqr' | 'compare';

function severityVariant(s: string): 'danger' | 'warning' | 'muted' {
  const lc = s.toLowerCase();
  if (lc === 'high' || lc === 'critical') return 'danger';
  if (lc === 'medium') return 'warning';
  return 'muted';
}

function AnomalyRowContent({ candidate }: { candidate: AnomalyCandidate }) {
  return (
    <div className="space-y-2 text-sm">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <p className="text-xs text-text-muted">Row index</p>
          <p className="font-mono font-semibold text-text">{candidate.row}</p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Value</p>
          <p className="font-mono font-semibold text-text">
            {candidate.value != null ? String(candidate.value) : 'null'}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Confidence</p>
          <div className="flex items-center gap-1.5 mt-0.5">
            <div className="w-14 h-1.5 rounded-full bg-border overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full',
                  candidate.confidence >= 0.8 ? 'bg-danger' : candidate.confidence >= 0.5 ? 'bg-warning' : 'bg-text-muted'
                )}
                style={{ width: `${candidate.confidence * 100}%` }}
              />
            </div>
            <span className="text-xs font-mono">{(candidate.confidence * 100).toFixed(0)}%</span>
          </div>
        </div>
        <div>
          <p className="text-xs text-text-muted">Suggested action</p>
          <Badge variant={candidate.candidate_action === 'DELETE' ? 'danger' : 'warning'}>
            {candidate.candidate_action}
          </Badge>
        </div>
      </div>
      {candidate.explain && (
        <div className="flex items-start gap-2 rounded-lg bg-surface border border-border p-3">
          <Info className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <p className="text-xs text-text-muted">{candidate.explain}</p>
        </div>
      )}
      {candidate.alternate_actions && candidate.alternate_actions.length > 0 && (
        <p className="text-xs text-text-muted">
          Alternatives:{' '}
          {candidate.alternate_actions.map((a) => (
            <Badge key={a} variant="muted" className="mr-1">
              {a}
            </Badge>
          ))}
        </p>
      )}
    </div>
  );
}

export default function AnomalyPanel({ column, results, className }: Props) {
  const [method, setMethod] = useState<MethodChoice>('compare');
  const [selectedMethod, setSelectedMethod] = useState<'zscore' | 'iqr' | null>(null);

  // Raw anomaly candidates for this column
  const allCandidates = (
    (results.phase3 as { anomaly_candidates?: AnomalyCandidate[] } | undefined)
      ?.anomaly_candidates ?? []
  ).filter((c) => c.column === column);

  const zscoreCandidates = allCandidates.filter((c) => c.method === 'zscore');
  const iqrCandidates = allCandidates.filter((c) => c.method === 'iqr');

  // Enriched outlier result from the /results endpoint
  const outlierResult = (results.outliers as Record<string, { zscore: number[]; iqr: number[]; confidence: number; risk: string }> | undefined)?.[column];

  const avgZConf =
    zscoreCandidates.length > 0
      ? zscoreCandidates.reduce((a, c) => a + c.confidence, 0) / zscoreCandidates.length
      : null;
  const avgIqrConf =
    iqrCandidates.length > 0
      ? iqrCandidates.reduce((a, c) => a + c.confidence, 0) / iqrCandidates.length
      : null;

  const activeCandidates = useMemo(() => {
    if (selectedMethod === 'zscore') return zscoreCandidates;
    if (selectedMethod === 'iqr') return iqrCandidates;
    return allCandidates;
  }, [selectedMethod, allCandidates, zscoreCandidates, iqrCandidates]);

  const handlerItems = activeCandidates.map((c, i) => ({
    id: `${c.row}-${i}`,
    variant: severityVariant(c.severity),
    trigger: (
      <span className="font-mono text-xs">
        Row {c.row} — value: <strong>{String(c.value ?? 'null')}</strong>
      </span>
    ),
    badge: (
      <Badge variant={severityVariant(c.severity)} className="text-[10px]">
        {c.severity}
      </Badge>
    ),
    content: <AnomalyRowContent candidate={c} />,
  }));

  const noData = allCandidates.length === 0 && !outlierResult;

  if (noData) {
    return (
      <Card className={cn('border-success/30 bg-success/5', className)}>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-6 w-6 text-success shrink-0" />
          <div>
            <p className="font-semibold text-text">No anomalies detected</p>
            <p className="text-sm text-text-muted mt-0.5">
              Z-score and IQR analysis found no outliers in <strong>{column}</strong>.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card title="Anomaly Detection" className={className}>
      {/* Method selector */}
      <div className="flex flex-wrap gap-2 mb-6">
        {[
          { key: 'compare' as MethodChoice, label: 'Compare both', icon: GitCompare },
          { key: 'zscore' as MethodChoice, label: 'Z-Score', icon: TrendingUp },
          { key: 'iqr' as MethodChoice, label: 'IQR', icon: Zap },
        ].map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setMethod(key)}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium border transition-all',
              method === key
                ? 'border-accent bg-accent/10 text-primary'
                : 'border-border bg-surface hover:bg-border/40 text-text-muted'
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {label}
          </button>
        ))}
      </div>

      {/* Side-by-side comparison */}
      {method === 'compare' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
          {/* Z-Score */}
          <div className="rounded-xl border border-border p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="font-semibold text-text flex items-center gap-1.5">
                <TrendingUp className="h-4 w-4" /> Z-Score
              </p>
              {avgZConf != null && (
                <Badge variant={avgZConf >= 0.8 ? 'danger' : avgZConf >= 0.5 ? 'warning' : 'muted'}>
                  avg conf {(avgZConf * 100).toFixed(0)}%
                </Badge>
              )}
            </div>
            <div className="space-y-2 text-sm text-text-muted">
              <p>
                Flags values whose standardised score (z = (x − μ) / σ) exceeds a threshold
                (typically |z| &gt; 3).
              </p>
              <div className="flex justify-between">
                <span>Anomalies found</span>
                <strong className="text-text">{zscoreCandidates.length}</strong>
              </div>
              {outlierResult?.zscore?.length ? (
                <div className="flex justify-between">
                  <span>Unique rows</span>
                  <strong className="text-text">{outlierResult.zscore.length}</strong>
                </div>
              ) : null}
            </div>
            <Button
              size="sm"
              variant={selectedMethod === 'zscore' ? 'primary' : 'outline'}
              onClick={() => setSelectedMethod('zscore')}
              disabled={zscoreCandidates.length === 0}
            >
              {selectedMethod === 'zscore' ? '✓ Selected' : 'Select Z-Score'}
            </Button>
          </div>

          {/* IQR */}
          <div className="rounded-xl border border-border p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="font-semibold text-text flex items-center gap-1.5">
                <Zap className="h-4 w-4" /> IQR
              </p>
              {avgIqrConf != null && (
                <Badge variant={avgIqrConf >= 0.8 ? 'danger' : avgIqrConf >= 0.5 ? 'warning' : 'muted'}>
                  avg conf {(avgIqrConf * 100).toFixed(0)}%
                </Badge>
              )}
            </div>
            <div className="space-y-2 text-sm text-text-muted">
              <p>
                Flags values outside [Q1 − 1.5 × IQR, Q3 + 1.5 × IQR]. More robust to
                heavy-tailed distributions.
              </p>
              <div className="flex justify-between">
                <span>Anomalies found</span>
                <strong className="text-text">{iqrCandidates.length}</strong>
              </div>
              {outlierResult?.iqr?.length ? (
                <div className="flex justify-between">
                  <span>Unique rows</span>
                  <strong className="text-text">{outlierResult.iqr.length}</strong>
                </div>
              ) : null}
            </div>
            <Button
              size="sm"
              variant={selectedMethod === 'iqr' ? 'primary' : 'outline'}
              onClick={() => setSelectedMethod('iqr')}
              disabled={iqrCandidates.length === 0}
            >
              {selectedMethod === 'iqr' ? '✓ Selected' : 'Select IQR'}
            </Button>
          </div>
        </div>
      )}

      {/* Single method stats */}
      {method !== 'compare' && (
        <div className="mb-4 p-3 rounded-lg bg-surface border border-border text-sm text-text-muted">
          Showing <strong className="text-text">{method === 'zscore' ? 'Z-Score' : 'IQR'}</strong>{' '}
          results — {method === 'zscore' ? zscoreCandidates.length : iqrCandidates.length} anomalies.
        </div>
      )}

      {/* Selection prompt */}
      {!selectedMethod && method === 'compare' && allCandidates.length > 0 && (
        <div className="mb-4 flex items-center gap-2 text-sm text-text-muted">
          <AlertCircle className="h-4 w-4 text-warning shrink-0" />
          Select a method above to load handlers for individual rows.
        </div>
      )}

      {/* Anomaly handlers */}
      {handlerItems.length > 0 && (
        <div>
          <p className="text-sm font-semibold text-text mb-3">
            {handlerItems.length} anomal{handlerItems.length === 1 ? 'y' : 'ies'} —{' '}
            <span className="font-normal text-text-muted">
              expand each row to see why it was flagged and decide an action
            </span>
          </p>
          <Accordion items={handlerItems} allowMultiple />
        </div>
      )}
    </Card>
  );
}
