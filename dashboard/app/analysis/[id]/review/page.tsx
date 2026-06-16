'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Step8DatasetReview from '@/components/analysis/pipeline/Step8DatasetReview';
import AnalysisPipelineShell from '@/components/analysis/AnalysisPipelineShell';
import { Alert } from '@/components/ui/Alert';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { analysisApi } from '@/lib/api';
import { analysisRoutes } from '@/lib/analysisPipeline';

export default function ReviewPage() {
  const params = useParams();
  const router = useRouter();
  const analysisId = Number(params.id);
  const routes = analysisRoutes(analysisId);

  const [gateLoading, setGateLoading] = useState(true);
  const [blocked, setBlocked] = useState<string | null>(null);

  useEffect(() => {
    analysisApi
      .getPhaseStatus(analysisId)
      .then((status) => {
        if (
          !status.rule_validation_completed ||
          !status.anomaly_completed ||
          !status.missing_value_completed
        ) {
          setBlocked(
            'Complete rule validation, anomaly review, and missing-value imputation before dataset review.',
          );
        } else if (!status.weight_application_completed) {
          setBlocked('Complete weight application (apply or ignore) before dataset review.');
        }
      })
      .catch(() => setBlocked('Could not verify phase status.'))
      .finally(() => setGateLoading(false));
  }, [analysisId]);

  if (gateLoading) {
    return (
      <div className="space-y-6">
        <SkeletonCard />
      </div>
    );
  }

  if (blocked) {
    return (
      <AnalysisPipelineShell
        analysisId={analysisId}
        currentStep={9}
        title="Dataset review"
        description="Compare original and processed datasets before approval."
      >
        <Alert variant="warning" title="Previous phases incomplete">
          <p className="text-sm">{blocked}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="text-sm text-primary underline"
              onClick={() => router.push(routes.validation)}
            >
              Go to rule validation
            </button>
            <button
              type="button"
              className="text-sm text-primary underline"
              onClick={() => router.push(routes.columns)}
            >
              Go to column analysis
            </button>
            <button
              type="button"
              className="text-sm text-primary underline"
              onClick={() => router.push(routes.weights)}
            >
              Go to weight application
            </button>
          </div>
        </Alert>
      </AnalysisPipelineShell>
    );
  }

  return (
    <Step8DatasetReview
      analysisId={analysisId}
      onBack={() => router.push(routes.weights)}
    />
  );
}
