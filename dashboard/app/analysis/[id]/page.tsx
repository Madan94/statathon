'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { analysisApi, AnalysisResult } from '@/lib/api';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import PageHeader from '@/components/layout/PageHeader';
import Step1Summary from '@/components/analysis/pipeline/Step1Summary';
import Step2Normalize from '@/components/analysis/pipeline/Step2Normalize';
import Step3Semantic from '@/components/analysis/pipeline/Step3Semantic';
import Step4Cluster from '@/components/analysis/pipeline/Step4Cluster';
import Step5SchemaKG from '@/components/analysis/pipeline/Step5SchemaKG';
import ColumnAnalysisLayout from '@/components/analysis/ColumnAnalysisLayout';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { Alert } from '@/components/ui/Alert';
import type { ColumnDecision } from '@/components/analysis/pipeline/Step2Normalize';

const STEP_HEADERS: Record<number, { title: string; description: string }> = {
  1: {
    title: 'Dataset summary',
    description: 'In-depth profile of every column — completeness, types and semantic domains.',
  },
  2: {
    title: 'Column normalisation',
    description: 'Rename, exclude or re-type columns before semantic mapping begins.',
  },
  3: {
    title: 'Semantic mapping',
    description:
      'Review how columns are mapped to statistical domains. Override any assignment and confirm before clustering.',
  },
  4: {
    title: 'Column clustering',
    description:
      'Columns grouped by embedding similarity into domain clusters. Verify groupings before reviewing the schema.',
  },
  5: {
    title: 'Schema & knowledge graph',
    description:
      'Full relational schema graph and knowledge-graph output. Download or verify before column-level analysis.',
  },
};

export default function AnalysisPage() {
  const params = useParams();
  const analysisId = Number(params.id);

  const [step, setStep] = useState(1);
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // User state carried between steps
  const [columnDecisions, setColumnDecisions] = useState<Record<string, ColumnDecision>>({});
  const [semanticOverrides, setSemanticOverrides] = useState<Record<string, string>>({});

  useEffect(() => {
    analysisApi
      .getResults(analysisId)
      .then(setResults)
      .catch(() => setLoadError('Failed to load analysis results. Check that the analysis has completed.'))
      .finally(() => setLoading(false));
  }, [analysisId]);

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
        {loadError ?? 'Unable to load this analysis.'}
      </Alert>
    );
  }

  // Column analysis is a full-screen mode (step 6)
  if (step === 6) {
    return <ColumnAnalysisLayout results={results} onBack={() => setStep(5)} />;
  }

  const header = STEP_HEADERS[step];

  return (
    <div className="pb-12">
      <WorkflowStepper currentStep={3} className="mb-5" />
      <AnalysisStepper currentStep={step} className="mb-8" />

      <PageHeader
        title={header.title}
        description={header.description}
      />

      {step === 1 && (
        <Step1Summary results={results} onProceed={() => setStep(2)} />
      )}

      {step === 2 && (
        <Step2Normalize
          results={results}
          decisions={columnDecisions}
          onProceed={(d) => {
            setColumnDecisions(d);
            setStep(3);
          }}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && (
        <Step3Semantic
          results={results}
          analysisId={analysisId}
          overrides={semanticOverrides}
          onProceed={(o) => {
            setSemanticOverrides(o);
            setStep(4);
          }}
          onBack={() => setStep(2)}
        />
      )}

      {step === 4 && (
        <Step4Cluster
          results={results}
          analysisId={analysisId}
          onProceed={() => setStep(5)}
          onBack={() => setStep(3)}
        />
      )}

      {step === 5 && (
        <Step5SchemaKG
          results={results}
          analysisId={analysisId}
          onProceed={() => setStep(6)}
          onBack={() => setStep(4)}
        />
      )}
    </div>
  );
}
