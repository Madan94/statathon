'use client';

import { useEffect, useMemo, useRef } from 'react';
import type { AnalysisResult } from '@/lib/api';
import { resolveAnomalyBlock, resolveOriginalColumnName } from '@/lib/outlierColumnUtils';
import Card from '@/components/ui/Card';
import { CheckCircle2 } from 'lucide-react';
import AnomalyReviewTable, { type AnomalyReviewTableHandle } from '@/components/analysis/AnomalyReviewTable';
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
  const tableRef = useRef<AnomalyReviewTableHandle>(null);
  const completedRef = useRef(false);
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

  useEffect(() => {
    if (!block?.detection_run || candidates.length > 0 || completedRef.current) return;
    completedRef.current = true;
    onDecisionsComplete?.();
  }, [block?.detection_run, candidates.length, onDecisionsComplete]);

  if (!block?.detection_run) {
    return null;
  }

  if (candidates.length === 0) {
    return (
      <Card className={className}>
        <div className="flex items-center gap-3 border-success/30 bg-success/5 rounded-lg p-4">
          <CheckCircle2 className="h-6 w-6 text-success shrink-0" />
          <div>
            <p className="font-semibold text-text">✓ No anomalies detected</p>
            <p className="text-sm text-text-muted mt-0.5">
              Column automatically approved for <strong>{column}</strong>.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <div className={className}>
      <AnomalyReviewTable
        ref={tableRef}
        column={column}
        analysisId={analysisId}
        results={results}
        block={block}
        candidates={candidates}
        domain={domain}
        onSaved={onDecisionsComplete}
        onProgress={onProgress}
      />
    </div>
  );
}

export type { AnomalyReviewTableHandle };
