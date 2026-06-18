'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AnalysisResult } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import { resolveAnomalyBlock, resolveOriginalColumnName } from '@/lib/outlierColumnUtils';
import AnomalyReviewTable from '@/components/analysis/AnomalyReviewTable';
import ColumnNormalizedCard from '@/components/analysis/columns/ColumnNormalizedCard';
import type { AnomalyCandidate } from '@/lib/api';

interface Props {
  column: string;
  analysisId: number;
  results: AnalysisResult;
  className?: string;
  onDecisionsComplete?: () => void;
  onProgress?: (reviewed: number, total: number) => void;
}

export default function AnomalyPanel({
  column,
  analysisId,
  results,
  className,
  onDecisionsComplete,
  onProgress,
}: Props) {
  const completedRef = useRef(false);
  const autoStartedRef = useRef(false);
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [summary, setSummary] = useState<Record<string, unknown> | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);

  const block = resolveAnomalyBlock(column, results);
  const phase3 = results.phase3 as { anomaly_candidates?: AnomalyCandidate[] } | undefined;
  const original = resolveOriginalColumnName(column, results);

  const candidates = useMemo(
    () => (phase3?.anomaly_candidates ?? []).filter(
      (c) => c.column === column || c.column === block?.column || c.column === original,
    ),
    [phase3?.anomaly_candidates, column, block?.column, original],
  );

  const domain = results.semantic_mapping?.find((r) => r.column === column)?.domain;

  const runAutoNormalize = useCallback(async () => {
    if (!block?.detection_run) return;
    setStatus('loading');
    setError(null);
    try {
      const res = await analysisApi.autoNormalizeColumn(analysisId, column, ['anomaly']);
      const anomaly = res.anomaly;
      if (anomaly?.applied === false && anomaly.reason === 'detection_not_run') {
        setStatus('idle');
        return;
      }
      setSummary(anomaly);
      setStatus('done');
      if (!completedRef.current) {
        completedRef.current = true;
        onDecisionsComplete?.();
      }
      onProgress?.(candidates.length, candidates.length);
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Auto-normalize failed');
    }
  }, [analysisId, block?.detection_run, column, candidates.length, onDecisionsComplete, onProgress]);

  useEffect(() => {
    autoStartedRef.current = false;
    completedRef.current = false;
    setShowManual(false);
    setStatus('idle');
    setSummary(undefined);
    setError(null);
  }, [column]);

  useEffect(() => {
    if (!block?.detection_run) return;
    if (candidates.length === 0) {
      if (!completedRef.current) {
        completedRef.current = true;
        onDecisionsComplete?.();
      }
      onProgress?.(0, 0);
      return;
    }
    if (showManual || autoStartedRef.current) return;
    autoStartedRef.current = true;
    void runAutoNormalize();
  }, [block?.detection_run, candidates.length, showManual, runAutoNormalize, onDecisionsComplete, onProgress]);

  if (!block?.detection_run) {
    return null;
  }

  if (showManual && candidates.length > 0) {
    return (
      <div className={className}>
        <AnomalyReviewTable
          column={column}
          analysisId={analysisId}
          results={results}
          block={block}
          candidates={candidates}
          domain={domain}
          onSaved={() => {
            if (!completedRef.current) {
              completedRef.current = true;
            }
            onDecisionsComplete?.();
          }}
          onProgress={onProgress}
        />
      </div>
    );
  }

  if (candidates.length === 0) {
    return (
      <ColumnNormalizedCard
        className={className}
        column={column}
        phase="anomaly"
        status="done"
        uiOnly
        summary={{ candidate_count: 0, decision: 'KEEP', normalized: true }}
      />
    );
  }

  return (
    <ColumnNormalizedCard
      className={className}
      column={column}
      phase="anomaly"
      status={status === 'idle' ? 'loading' : status}
      summary={summary as { saved?: number; candidate_count?: number; method?: string; decision?: string; already_applied?: boolean }}
      error={error}
      onRetry={() => void runAutoNormalize()}
      onReviewManually={() => setShowManual(true)}
    />
  );
}
