'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { analysisApi, AnalysisResult, AnalysisSummaryPayload } from '@/lib/api';
import { toast } from '@/lib/toast';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import PageHeader from '@/components/layout/PageHeader';
import Step1Summary from '@/components/analysis/pipeline/Step1Summary';
import Step2Normalize from '@/components/analysis/pipeline/Step2Normalize';
import Step3Semantic from '@/components/analysis/pipeline/Step3Semantic';
import Step4Cluster from '@/components/analysis/pipeline/Step4Cluster';
import Step5SchemaKG from '@/components/analysis/pipeline/Step5SchemaKG';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { Alert } from '@/components/ui/Alert';
import type { ColumnDecision } from '@/components/analysis/pipeline/Step2Normalize';
import {
  analysisRoutes,
  loadHubStep,
  saveHubStep,
} from '@/lib/analysisPipeline';

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
    title: 'Schema graph',
    description:
      'Relational schema graph from semantic analysis. Verify before rule validation.',
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

function mergeSummaryIntoResults(
  results: AnalysisResult,
  summary: AnalysisSummaryPayload
): AnalysisResult {
  const prof = summary.profiling_summary ?? {};
  const healthFromSummary = prof.health;
  const schemaFromSummary = prof.schema;
  const profilesFromSummary =
    summary.column_profiles ?? prof.column_profiles ?? {};
  const mergedProfiles =
    Object.keys(profilesFromSummary).length > 0
      ? profilesFromSummary
      : (results.column_profiles ?? {});
  return {
    ...results,
    health: {
      ...(typeof results.health === 'object' && results.health ? results.health : {}),
      ...(healthFromSummary ?? {}),
    },
    schema: {
      ...(results.schema ?? {}),
      ...(schemaFromSummary ?? {}),
    },
    column_profiles: mergedProfiles,
    profiling_summary: {
      ...(typeof results.profiling_summary === 'object' && results.profiling_summary
        ? results.profiling_summary
        : {}),
      ...prof,
      column_profiles: mergedProfiles,
      health: {
        ...(typeof results.health === 'object' && results.health ? results.health : {}),
        ...(healthFromSummary ?? {}),
      },
      schema: {
        ...(results.schema ?? {}),
        ...(schemaFromSummary ?? {}),
      },
    },
    dataset_context: {
      ...(results.dataset_context ?? {}),
      ...(summary.dataset_context ?? {}),
    },
    dataset_profile: summary.dataset_profile ?? results.dataset_profile,
  };
}

export default function AnalysisPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const analysisId = Number(params.id);
  const routes = analysisRoutes(analysisId);

  const [step, setStep] = useState(1);
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingNormalization, setSavingNormalization] = useState(false);

  const [columnDecisions, setColumnDecisions] = useState<Record<string, ColumnDecision>>({});
  const [semanticOverrides, setSemanticOverrides] = useState<Record<string, string>>({});

  useEffect(() => {
    const fromUrl = searchParams.get('step');
    const parsed = fromUrl ? parseInt(fromUrl, 10) : NaN;
    if (parsed >= 1 && parsed <= 5) {
      setStep(parsed);
    } else {
      setStep(loadHubStep(analysisId));
    }
  }, [analysisId, searchParams]);

  useEffect(() => {
    saveHubStep(analysisId, step);
  }, [analysisId, step]);

  useEffect(() => {
    Promise.all([
      analysisApi.getResults(analysisId, { includePhase3: false }),
      analysisApi.getSummary(analysisId),
      analysisApi.getNormalization(analysisId),
    ])
      .then(([res, summary, norm]) => {
        setResults(mergeSummaryIntoResults(res, summary));
        if (norm.normalization_version && norm.columns.length > 0) {
          setColumnDecisions(decisionsFromSaved(norm.columns));
        } else if (norm.columns.length > 0) {
          setColumnDecisions(decisionsFromSaved(norm.columns));
        }
      })
      .catch(() =>
        setLoadError('Failed to load analysis results. Check that the analysis has completed.')
      )
      .finally(() => setLoading(false));
  }, [analysisId]);

  const goToStep = (next: number) => {
    setStep(next);
    if (next >= 1 && next <= 5) {
      router.replace(routes.hubStep(next));
    }
  };

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
      const [refreshed, norm] = await Promise.all([
        analysisApi.getResults(analysisId, { includePhase3: false }),
        analysisApi.getNormalization(analysisId),
      ]);
      setResults(refreshed);
      if (norm.columns.length > 0) {
        setColumnDecisions(decisionsFromSaved(norm.columns));
      } else {
        setColumnDecisions(decisions);
      }
      toast.success('Normalisation saved — semantic mapping uses approved schema');
      goToStep(3);
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

  const header = STEP_HEADERS[step];

  return (
    <div className="pb-12">
      <WorkflowStepper currentStep={3} className="mb-5" />
      <AnalysisStepper analysisId={analysisId} currentStep={step} className="mb-8" />

      <PageHeader title={header.title} description={header.description} />

      {step === 1 && <Step1Summary results={results} onProceed={() => goToStep(2)} />}

      {step === 2 && (
        <Step2Normalize
          results={results}
          analysisId={analysisId}
          decisions={columnDecisions}
          onProceed={handleSaveNormalization}
          onBack={() => goToStep(1)}
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
            goToStep(4);
          }}
          onBack={() => goToStep(2)}
        />
      )}

      {step === 4 && (
        <Step4Cluster
          results={results}
          analysisId={analysisId}
          onProceed={() => goToStep(5)}
          onBack={() => goToStep(3)}
        />
      )}

      {step === 5 && (
        <Step5SchemaKG
          results={results}
          analysisId={analysisId}
          onProceed={() => router.push(routes.validation)}
          onBack={() => goToStep(4)}
        />
      )}
    </div>
  );
}
