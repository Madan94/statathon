'use client';

import ConfidenceScore from '@/components/ConfidenceScore';

export interface ImputationCandidate {
  column: string;
  missing_count?: number;
  recommended_method?: string;
  confidence?: number;
  confidence_band?: string;
  method_scores?: Record<string, number>;
}

interface ImputationPanelProps {
  candidates: ImputationCandidate[];
}

export default function ImputationPanel({ candidates }: ImputationPanelProps) {
  if (!candidates.length) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-2">Imputation recommendations</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">No missing-value imputation needed.</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Imputation recommendations ({candidates.length})
      </h2>
      <div className="space-y-3">
        {candidates.map((c) => (
          <div
            key={c.column}
            className="p-3 bg-gray-50 dark:bg-gray-900 rounded flex flex-wrap items-center justify-between gap-3"
          >
            <div>
              <p className="font-medium text-gray-900 dark:text-gray-100">{c.column}</p>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Missing: {c.missing_count ?? '—'} · Recommended:{' '}
                <span className="font-semibold">{c.recommended_method || '—'}</span>
                {c.confidence_band ? ` (${c.confidence_band})` : ''}
              </p>
              {c.method_scores && (
                <p className="text-xs text-gray-500 mt-1">
                  scores — mean {c.method_scores.mean?.toFixed(2)} · median {c.method_scores.median?.toFixed(2)} ·
                  knn {c.method_scores.knn?.toFixed(2)}
                </p>
              )}
            </div>
            {typeof c.confidence === 'number' && (
              <ConfidenceScore score={c.confidence} label="fit" size="sm" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
