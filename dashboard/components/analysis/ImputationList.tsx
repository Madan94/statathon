'use client';

import { Wand2 } from 'lucide-react';
import Card from '@/components/ui/Card';
import ConfidenceScore from '@/components/ConfidenceScore';
import EmptyState from '@/components/ui/EmptyState';
import { ImputationCandidate } from '@/lib/api';

interface ImputationListProps {
  candidates: ImputationCandidate[];
}

export default function ImputationList({ candidates }: ImputationListProps) {
  if (!candidates.length) {
    return (
      <EmptyState
        icon={Wand2}
        title="No imputation needed"
        description="No missing-value columns require imputation guidance."
      />
    );
  }

  return (
    <div className="space-y-4">
      {candidates.map((c) => {
        const confidence = typeof c.confidence === 'number' ? c.confidence : 0.5;
        return (
          <Card key={c.column}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h3 className="font-semibold text-text font-mono">{c.column}</h3>
                <p className="text-sm text-text-muted mt-1">
                  Missing: {c.missing_count ?? '—'} · Recommended:{' '}
                  <span className="font-medium text-primary">{c.recommended_method || '—'}</span>
                  {c.confidence_band ? ` (${c.confidence_band})` : ''}
                </p>
                {c.method_scores && (
                  <p className="text-xs text-text-muted mt-2">
                    mean {c.method_scores.mean?.toFixed(2)} · median{' '}
                    {c.method_scores.median?.toFixed(2)} · knn {c.method_scores.knn?.toFixed(2)}
                  </p>
                )}
              </div>
              <div className="w-32">
                <ConfidenceScore score={confidence} label="fit" size="sm" />
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
