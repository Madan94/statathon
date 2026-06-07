'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { analysisApi, AnalysisResult } from '@/lib/api';
import { toast } from '@/lib/toast';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import PageHeader from '@/components/layout/PageHeader';
import Step1Summary from '@/components/analysis/pipeline/Step1Summary';
import Step2Normalize from '@/components/analysis/pipeline/Step2Normalize';
import Step3Semantic from '@/components/analysis/pipeline/Step3Semantic';
import Step4Cluster from '@/components/analysis/pipeline/Step4Cluster';
import Step5SchemaKG from '@/components/analysis/pipeline/Step5SchemaKG';
import Step6RuleValidation from '@/components/analysis/pipeline/Step6RuleValidation';
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
      'Full relational schema graph and knowledge-graph output. Download or verify before rule validation.',
  },
  6: {
    title: 'Rule validation',
    description:
      'Single- and multi-column rule violations from domains, statistics, and the knowledge graph. Review before anomaly detection.',
  },
};

function decisionsFromSaved(
  columns: Array<{
    original_name: string;
    normalized_name: string;
    is_deleted: boolean;
    is_excluded: boolean;
    is_active?: boolean;
  }>
): Record<string, ColumnDecision> {
  const out: Record<string, ColumnDecision> = {};
  for (const c of columns) {
    out[c.original_name] = {
      originalName: c.original_name,
      displayName: c.normalized_name,
      suggestedName: c.normalized_name,
      normalizedName: c.normalized_name,
      included: Boolean(c.is_active ?? (!c.is_deleted && !c.is_excluded)),
      isDeleted: c.is_deleted,
    };
  }
  return out;
}

export default function AnalysisPage() {
  const params = useParams();
  const analysisId = Number(params.id);

  const [step, setStep] = useState(1);
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingNormalization, setSavingNormalization] = useState(false);

  const [columnDecisions, setColumnDecisions] = useState<Record<string, ColumnDecision>>({});
  const [semanticOverrides, setSemanticOverrides] = useState<Record<string, string>>({});

  useEffect(() => {
    Promise.all([
      analysisApi.getResults(analysisId, { includePhase3: false }),
      analysisApi.getNormalization(analysisId),
    ])
      .then(([res, norm]) => {
        setResults(res);
        if (norm.normalization_version && norm.columns.length > 0) {
          setColumnDecisions(decisionsFromSaved(norm.columns));
        }
      })
      .catch(() =>
        setLoadError('Failed to load analysis results. Check that the analysis has completed.')
      )
      .finally(() => setLoading(false));
  }, [analysisId]);

  const [phase3Loading, setPhase3Loading] = useState(false);
  const [phase3Error, setPhase3Error] = useState<string | null>(null);

  useEffect(() => {
    if (step < 6) return;
    setPhase3Loading(true);
    setPhase3Error(null);
    analysisApi
      .getResults(analysisId, { includePhase3: true })
      .then(setResults)
      .catch(() => setPhase3Error('Failed to load rule validation results'))
      .finally(() => setPhase3Loading(false));
  }, [step, analysisId]);

  const handleSaveNormalization = async (decisions: Record<string, ColumnDecision>) => {
    setSavingNormalization(true);
    try {
      const columns = Object.values(decisions).map((c) => ({
        original_name: c.originalName,
        normalized_name: c.displayName.trim() || c.originalName,
        is_deleted: c.isDeleted,
        is_excluded: !c.included && !c.isDeleted,
      }));
      await analysisApi.saveNormalization(analysisId, columns);
      const refreshed = await analysisApi.getResults(analysisId, { includePhase3: false });
      setResults(refreshed);
      setColumnDecisions(decisions);
      toast.success('Normalisation saved — semantic mapping uses approved schema');
      setStep(3);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to save normalisation';
      toast.error(msg);
    } finally {
      setSavingNormalization(false);
    }
  };

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

  if (step === 7) {
    return <ColumnAnalysisLayout results={results} analysisId={analysisId} onBack={() => setStep(6)} />;
  }

  if (step === 6) {
    return (
      <div className="pb-12">
        <WorkflowStepper currentStep={3} className="mb-5" />
        <AnalysisStepper currentStep={6} className="mb-8" />
        <PageHeader title={STEP_HEADERS[6].title} description={STEP_HEADERS[6].description} />
        <Step6RuleValidation
          results={results}
          analysisId={analysisId}
          loadState={phase3Loading ? 'loading' : phase3Error ? 'error' : 'loaded'}
          loadError={phase3Error}
          onProceed={() => setStep(7)}
          onBack={() => setStep(5)}
        />
      </div>
    );
  }

  const header = STEP_HEADERS[step];

  return (
    <div className="pb-12">
      <WorkflowStepper currentStep={3} className="mb-5" />
      <AnalysisStepper currentStep={step} className="mb-8" />

      <PageHeader title={header.title} description={header.description} />

      {step === 1 && <Step1Summary results={results} onProceed={() => setStep(2)} />}

      {step === 2 && (
        <Step2Normalize
          results={results}
          decisions={columnDecisions}
          onProceed={handleSaveNormalization}
          onBack={() => setStep(1)}
          saving={savingNormalization}
        />
      )}

      {step === 3 && (
        <Step3Semantic
          results={results}
          analysisId={analysisId}
          overrides={semanticOverrides}
          effectiveSchema={results.effective_schema}
          normalizationVersion={results.normalization_version}
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
