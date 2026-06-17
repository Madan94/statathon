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
    let isMounted = true;
    analysisApi
      .getResults(analysisId, { includePhase3 })
      .then(data => {
        if (isMounted) {
          setResults(data);
          setError(null);
          setLoading(false);
        }
      })
      .catch(() => {
        if (isMounted) {
          setError('Failed to load analysis results.');
          setLoading(false);
        }
      });
    return () => { isMounted = false; };
  }, [analysisId, includePhase3, enabled]);

  return { results, setResults, loading, error, reload: () => {
    return analysisApi.getResults(analysisId, { includePhase3 }).then(setResults);
  }};
}
