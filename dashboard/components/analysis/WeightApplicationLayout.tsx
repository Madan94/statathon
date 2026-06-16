'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { analysisApi } from '@/lib/api';
import { analysisRoutes } from '@/lib/analysisPipeline';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { cn } from '@/lib/cn';
import { toast } from '@/lib/toast';
import {
  Scale,
  CheckCircle2,
  Loader2,
  ArrowRight,
  ArrowLeft,
  Download,
  BarChart3,
  RefreshCw,
} from 'lucide-react';

type WeightPayload = Awaited<ReturnType<typeof analysisApi.getWeightApplication>>;
type ColumnValidation = WeightPayload['validations'][string];

interface Props {
  analysisId: number;
  onBack: () => void;
}

function formatMetric(value: number | null | undefined, type?: string) {
  if (value == null || !Number.isFinite(value)) return '—';
  if (type === 'rate') return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

const CHECK_LABELS: Record<string, string> = {
  positive_values: 'Positive values',
  no_negative_weights: 'No negative weights',
  missing_below_threshold: 'Missing below threshold',
  reasonable_variance: 'Reasonable variance',
  no_extreme_inflation: 'No extreme inflation',
};

export default function WeightApplicationLayout({ analysisId, onBack }: Props) {
  const router = useRouter();
  const routes = analysisRoutes(analysisId);
  const [payload, setPayload] = useState<WeightPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [detecting, setDetecting] = useState(false);
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null);
  const [compareColumn, setCompareColumn] = useState<string | null>(null);
  const [manualValidation, setManualValidation] = useState<ColumnValidation | null>(null);
  const [actionPhase, setActionPhase] = useState<'idle' | 'applying' | 'ignoring'>('idle');
  const compareTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (runDetect = false) => {
    setLoading(true);
    try {
      const data = runDetect
        ? await analysisApi.detectWeights(analysisId)
        : await analysisApi.getWeightApplication(analysisId);
      setPayload(data);
      const rec = data.recommendation?.recommended;
      const applied = data.application?.weight_column;
      setSelectedColumn(applied ?? rec ?? data.detected_columns[0]?.column ?? null);
      setCompareColumn(applied ?? rec ?? data.detected_columns[0]?.column ?? null);
      if (!runDetect && data.detected_columns.length === 0 && !data.application?.applied) {
        await analysisApi.detectWeights(analysisId).then((detected) => {
          setPayload(detected);
          const dRec = detected.recommendation?.recommended;
          setSelectedColumn(dRec ?? detected.detected_columns[0]?.column ?? null);
          setCompareColumn(dRec ?? detected.detected_columns[0]?.column ?? null);
        });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load weight application');
    } finally {
      setLoading(false);
    }
  }, [analysisId]);

  useEffect(() => {
    void load(false);
  }, [load]);

  const detectedSet = useMemo(
    () => new Set((payload?.detected_columns ?? []).map((d) => d.column)),
    [payload],
  );

  const selectedValidation = useMemo(() => {
    if (!selectedColumn) return undefined;
    return payload?.validations?.[selectedColumn] ?? manualValidation ?? undefined;
  }, [selectedColumn, payload?.validations, manualValidation]);

  const handleCompare = useCallback(async (col: string) => {
    setCompareColumn(col);
    try {
      const comparison = await analysisApi.compareWeightMetrics(analysisId, col);
      setPayload((prev) => (prev ? { ...prev, comparison } : prev));
      if (comparison.validation) {
        setManualValidation(comparison.validation as ColumnValidation);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Comparison failed');
    }
  }, [analysisId]);

  useEffect(() => {
    if (!selectedColumn) return;
    if (payload?.validations?.[selectedColumn]) {
      setManualValidation(null);
      return;
    }
    if (compareTimer.current) clearTimeout(compareTimer.current);
    compareTimer.current = setTimeout(() => {
      void handleCompare(selectedColumn);
    }, 400);
    return () => {
      if (compareTimer.current) clearTimeout(compareTimer.current);
    };
  }, [selectedColumn, payload?.validations, handleCompare]);

  const handleDetect = async () => {
    setDetecting(true);
    try {
      const data = await analysisApi.detectWeights(analysisId);
      setPayload(data);
      toast.success(`Detected ${data.detected_columns.length} weight column(s)`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Detection failed');
    } finally {
      setDetecting(false);
    }
  };

  const handleApply = async (column?: string) => {
    const target = column ?? selectedColumn;
    if (!target) return;
    setActionPhase('applying');
    try {
      await analysisApi.applySurveyWeight(analysisId, target);
      toast.success(`Applied weight column: ${target}`);
      await load(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to apply weight');
    } finally {
      setActionPhase('idle');
    }
  };

  const handleIgnore = async () => {
    setActionPhase('ignoring');
    try {
      await analysisApi.ignoreSurveyWeight(analysisId);
      toast.success('Continuing without survey weights');
      router.push(routes.review);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to skip weights');
    } finally {
      setActionPhase('idle');
    }
  };

  const handleProceed = () => {
    if (!payload?.weight_application_completed) {
      toast.error('Apply a weight or choose Ignore Weight before proceeding');
      return;
    }
    router.push(routes.review);
  };

  const downloadLabel = payload?.application?.applied
    ? 'Download weighted dataset (v6)'
    : 'Download imputed dataset (v5)';

  const downloadUrl = analysisApi.datasetReviewDownloadUrl(analysisId, 'processed_csv');

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-24">
      <WorkflowStepper currentStep={3} className="mb-4" />
      <AnalysisStepper analysisId={analysisId} currentStep={8} className="mb-4" />
      <PageHeader
        title="Weight application"
        description="Detect, validate, and apply survey sampling weights before dataset review."
      />

      {payload?.stale && (
        <Alert variant="warning" title="Weight application is stale">
          <p className="text-sm">
            Upstream imputation changed since weights were last applied. Re-run detection and apply again.
          </p>
        </Alert>
      )}

      {!payload?.detected_columns?.length && (
        <Alert variant="warning" title="No weight columns auto-detected">
          <p className="text-sm">
            Select a weight column manually from the sidebar, or refresh detection after semantic mapping.
          </p>
        </Alert>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[220px_1fr_280px] gap-4 min-h-[560px]">
        <Card className="p-3 overflow-y-auto">
          <p className="text-xs font-semibold uppercase text-text-muted mb-3">Columns</p>
          <ul className="space-y-1">
            {(payload?.columns ?? []).map((col) => {
              const isWeight = detectedSet.has(col);
              const active = col === selectedColumn;
              return (
                <li key={col}>
                  <button
                    type="button"
                    onClick={() => setSelectedColumn(col)}
                    className={cn(
                      'w-full text-left px-2 py-1.5 rounded-lg text-xs font-mono transition-colors',
                      active ? 'bg-accent/15 text-accent' : 'hover:bg-border/40',
                      isWeight && 'border-l-2 border-accent pl-2',
                    )}
                  >
                    {col}
                    {isWeight && <span className="ml-1 text-[10px] text-accent">weight</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        <div className="space-y-4">
          <Card title="Weight detection">
            <div className="flex justify-end mb-2">
              <Button size="sm" variant="ghost" onClick={() => void handleDetect()} disabled={detecting}>
                {detecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Refresh detection
              </Button>
            </div>
            {(payload?.detected_columns ?? []).length === 0 ? (
              <p className="text-sm text-text-muted">No candidate weight columns detected.</p>
            ) : (
              <ul className="space-y-2">
                {payload?.detected_columns.map((d) => (
                  <li
                    key={d.column}
                    className={cn(
                      'rounded-lg border px-3 py-2',
                      selectedColumn === d.column ? 'border-accent bg-accent/5' : 'border-border',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <p className="font-medium text-sm flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4 text-success" />
                          {d.column}
                        </p>
                        <p className="text-xs text-text-muted mt-0.5">
                          Confidence: {(d.confidence * 100).toFixed(0)}%
                        </p>
                      </div>
                      <Button size="sm" variant="ghost" onClick={() => void handleCompare(d.column)}>
                        Compare
                      </Button>
                    </div>
                    {d.signals && (
                      <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-text-muted">
                        <span>name: {((d.signals.name ?? 0) * 100).toFixed(0)}%</span>
                        <span>semantic: {((d.signals.semantic ?? 0) * 100).toFixed(0)}%</span>
                        <span>statistics: {((d.signals.statistics ?? 0) * 100).toFixed(0)}%</span>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {selectedColumn && selectedValidation && (
            <Card title="Weight validation">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div>
                  <p className="text-xs text-text-muted">Coverage</p>
                  <p className="font-mono font-semibold">
                    {((selectedValidation.coverage ?? 0) * 100).toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-xs text-text-muted">Missing</p>
                  <p className="font-mono font-semibold">
                    {((selectedValidation.missing_pct ?? 0) * 100).toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-xs text-text-muted">Variance</p>
                  <p className="font-mono font-semibold">{selectedValidation.variance ?? '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-text-muted">Quality score</p>
                  <p className="font-mono font-semibold">
                    {((selectedValidation.quality_score ?? 0) * 100).toFixed(0)}%
                  </p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant={selectedValidation.valid ? 'success' : 'warning'}>
                  {selectedValidation.valid ? 'Valid weight column' : 'Validation issues'}
                </Badge>
              </div>
              {selectedValidation.checks && (
                <ul className="mt-3 space-y-1 text-xs">
                  {Object.entries(selectedValidation.checks).map(([key, passed]) => (
                    <li key={key} className={passed ? 'text-success' : 'text-warning'}>
                      {passed ? '✓' : '✗'} {CHECK_LABELS[key] ?? key}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          <Card title="Weight comparison">
            <p className="text-xs text-text-muted mb-3">
              Unweighted vs weighted descriptive metrics
              {compareColumn ? ` for ${compareColumn}` : ''}
            </p>
            {(payload?.comparison?.metrics ?? []).length === 0 ? (
              <p className="text-sm text-text-muted">Select a weight column to compare metrics.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase text-text-muted">
                      <th className="pb-2 pr-3">Metric</th>
                      <th className="pb-2 pr-3">Unweighted</th>
                      <th className="pb-2 pr-3">Weighted</th>
                      <th className="pb-2">Delta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payload?.comparison?.metrics.map((m) => (
                      <tr key={m.column} className="border-b border-border/40">
                        <td className="py-2 pr-3 font-medium">{m.label}</td>
                        <td className="py-2 pr-3 font-mono">{formatMetric(m.unweighted, m.type)}</td>
                        <td className="py-2 pr-3 font-mono">{formatMetric(m.weighted, m.type)}</td>
                        <td className="py-2 font-mono">{formatMetric(m.delta, m.type)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <Card className="p-4 space-y-4">
          <div className="flex items-center gap-2">
            <Scale className="h-5 w-5 text-accent" />
            <p className="font-semibold">Recommendation</p>
          </div>
          {payload?.recommendation ? (
            <div className="rounded-lg border border-accent/30 bg-accent/5 p-3">
              <p className="text-sm font-medium">{payload.recommendation.recommended}</p>
              <p className="text-xs text-text-muted mt-1">
                Confidence: {((payload.recommendation.confidence ?? 0) * 100).toFixed(0)}%
              </p>
              <p className="text-xs mt-2">{payload.recommendation.reason}</p>
            </div>
          ) : (
            <p className="text-sm text-text-muted">No recommendation available.</p>
          )}

          {payload?.application?.applied && (
            <Alert variant="success" title="Weight applied">
              <p className="text-sm">
                Column <strong>{payload.application.weight_column}</strong> is active for weighted statistics.
              </p>
            </Alert>
          )}

          <div className="space-y-2 pt-2">
            {payload?.recommendation?.recommended && (
              <Button
                variant="secondary"
                className="w-full"
                onClick={() => void handleApply(payload.recommendation!.recommended)}
                disabled={actionPhase !== 'idle'}
              >
                Apply recommendation
              </Button>
            )}
            <Button
              className="w-full gap-2"
              onClick={() => void handleApply()}
              disabled={!selectedColumn || !selectedValidation?.valid || actionPhase !== 'idle'}
            >
              {actionPhase === 'applying' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Scale className="h-4 w-4" />
              )}
              Use weight
            </Button>
            <Button
              variant="outline"
              className="w-full"
              onClick={handleIgnore}
              disabled={actionPhase !== 'idle'}
            >
              {actionPhase === 'ignoring' ? 'Skipping…' : 'Ignore weight'}
            </Button>
            <Button
              variant="secondary"
              className="w-full gap-2"
              onClick={() => compareColumn && void handleCompare(compareColumn)}
              disabled={!compareColumn}
            >
              <BarChart3 className="h-4 w-4" />
              Compare metrics
            </Button>
            <a
              href={downloadUrl}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-border/30"
            >
              <Download className="h-4 w-4" />
              {downloadLabel}
            </a>
          </div>
        </Card>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button variant="ghost" onClick={onBack} className="gap-2">
          <ArrowLeft className="h-4 w-4" />
          Back to column analysis
        </Button>
        <Button onClick={handleProceed} size="lg" className="gap-2">
          Proceed to dataset review
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
