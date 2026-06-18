'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AnalysisResult } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import { resolveMissingCount } from '@/lib/outlierColumnUtils';
import ImputationReviewTable from '@/components/analysis/ImputationReviewTable';
import ColumnNormalizedCard from '@/components/analysis/columns/ColumnNormalizedCard';

interface Props {
  column: string;
  analysisId: number;
  results: AnalysisResult;
  className?: string;
  onSaved?: () => void;
}

/** Missing value review — backend imputation only when missing values exist. */
export default function MissingPanel({
  column,
  analysisId,
  results,
  className,
  onSaved,
}: Props) {
  const savedRef = useRef(false);
  const autoStartedRef = useRef(false);
  const missingCount = resolveMissingCount(column, results);
  const hasMissing = missingCount > 0;
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [summary, setSummary] = useState<Record<string, unknown> | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);

  const runAutoNormalize = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      const res = await analysisApi.autoNormalizeColumn(analysisId, column, ['imputation']);
      const imputation = res.imputation;
      const appliedMissing = Number(imputation?.missing_count ?? 0);
      if (appliedMissing === 0) {
        setStatus('error');
        setError('Imputation did not apply for this column. Try reviewing manually.');
        return;
      }
      setSummary(imputation);
      setStatus('done');
      if (!savedRef.current) {
        savedRef.current = true;
        onSaved?.();
      }
    } catch (err) {
      setStatus('error');
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(
        typeof detail === 'string' && detail
          ? detail
          : err instanceof Error
            ? err.message
            : 'Auto-normalize failed',
      );
    }
  }, [analysisId, column, onSaved]);

  useEffect(() => {
    autoStartedRef.current = false;
    savedRef.current = false;
    setShowManual(false);
    setStatus('idle');
    setSummary(undefined);
    setError(null);
  }, [column]);

  // No missing values — UI acknowledgment only; skip backend.
  useEffect(() => {
    if (hasMissing || savedRef.current) return;
    savedRef.current = true;
    onSaved?.();
  }, [column, hasMissing, onSaved]);

  // Missing values present — apply imputation in the backend.
  useEffect(() => {
    if (!hasMissing || showManual || autoStartedRef.current) return;
    autoStartedRef.current = true;
    void runAutoNormalize();
  }, [hasMissing, showManual, runAutoNormalize]);

  if (showManual) {
    return (
      <ImputationReviewTable
        column={column}
        analysisId={analysisId}
        results={results}
        className={className}
        onSaved={onSaved}
      />
    );
  }

  if (!hasMissing) {
    return (
      <ColumnNormalizedCard
        className={className}
        column={column}
        phase="imputation"
        status="done"
        uiOnly
        summary={{ missing_count: 0, normalized: true }}
      />
    );
  }

  return (
    <ColumnNormalizedCard
      className={className}
      column={column}
      phase="imputation"
      status={status === 'idle' ? 'loading' : status}
      summary={summary as {
        saved?: number;
        missing_count?: number;
        method?: string | null;
        decision?: string;
        already_applied?: boolean;
      }}
      error={error}
      onRetry={() => void runAutoNormalize()}
      onReviewManually={() => setShowManual(true)}
    />
  );
}
