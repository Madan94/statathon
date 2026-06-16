'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import AnalysisPipelineShell from '@/components/analysis/AnalysisPipelineShell';
import WeightApplicationLayout from '@/components/analysis/WeightApplicationLayout';
import { Alert } from '@/components/ui/Alert';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { analysisApi } from '@/lib/api';
import { analysisRoutes } from '@/lib/analysisPipeline';

export default function WeightApplicationPage() {
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
            'Complete rule validation, anomaly review, and missing-value imputation before weight application.',
          );
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
        currentStep={8}
        title="Weight application"
        description="Detect and apply survey sampling weights."
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
          </div>
        </Alert>
      </AnalysisPipelineShell>
    );
  }

  return (
    <WeightApplicationLayout
      analysisId={analysisId}
      onBack={() => router.push(routes.columns)}
    />
  );
}
