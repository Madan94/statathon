'use client';

import { useEffect, useState } from 'react';
import { analysisApi, AnalysisResult } from '@/lib/api';

export function useAnalysisResults(
  analysisId: number,
  options?: { includePhase3?: boolean; enabled?: boolean },
) {
  const includePhase3 = options?.includePhase3 ?? false;
  const enabled = options?.enabled ?? true;
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !analysisId) return;
    setLoading(true);
    setError(null);
    analysisApi
      .getResults(analysisId, { includePhase3 })
      .then(setResults)
      .catch(() => setError('Failed to load analysis results.'))
      .finally(() => setLoading(false));
  }, [analysisId, includePhase3, enabled]);

  return { results, setResults, loading, error, reload: () => {
    return analysisApi.getResults(analysisId, { includePhase3 }).then(setResults);
  }};
}
