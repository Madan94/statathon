'use client';

import { useParams, useRouter } from 'next/navigation';
import AnalysisPipelineShell from '@/components/analysis/AnalysisPipelineShell';
import Step6RuleValidation from '@/components/analysis/pipeline/Step6RuleValidation';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { Alert } from '@/components/ui/Alert';
import { useAnalysisResults } from '@/hooks/useAnalysisResults';
import { analysisRoutes } from '@/lib/analysisPipeline';

export default function ValidationPage() {
  const params = useParams();
  const router = useRouter();
  const analysisId = Number(params.id);
  const routes = analysisRoutes(analysisId);

  const { results, loading, error, reload } = useAnalysisResults(analysisId, {
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
    <AnalysisPipelineShell
      analysisId={analysisId}
      currentStep={6}
      title="Rule validation"
      description="Single- and multi-column rule violations from domains, statistics, and rulebooks. Review before column analysis."
    >
      <Step6RuleValidation
        results={results}
        analysisId={analysisId}
        loadState="loaded"
        onRefresh={reload}
        onProceed={() => router.push(routes.columns)}
        onBack={() => router.push(routes.hubStep(5))}
      />
    </AnalysisPipelineShell>
  );
}
