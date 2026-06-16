'use client';

import { useParams, useRouter } from 'next/navigation';
import ColumnAnalysisLayout from '@/components/analysis/ColumnAnalysisLayout';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { Alert } from '@/components/ui/Alert';
import { useAnalysisResults } from '@/hooks/useAnalysisResults';
import { analysisRoutes } from '@/lib/analysisPipeline';

export default function ColumnsPage() {
  const params = useParams();
  const router = useRouter();
  const analysisId = Number(params.id);
  const routes = analysisRoutes(analysisId);

  const { results, loading, error } = useAnalysisResults(analysisId, {
    includePhase3: true,
  });

  if (loading) {
    return (
      <div className="space-y-6">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (!results) {
    return (
      <Alert variant="error" title="Analysis not found" onRetry={() => window.location.reload()}>
        {error ?? 'Unable to load this analysis.'}
      </Alert>
    );
  }

  return (
    <ColumnAnalysisLayout
      results={results}
      analysisId={analysisId}
      onBack={() => router.push(routes.validation)}
      onProceedToDatasetReview={() => router.push(routes.weights)}
    />
  );
}
