'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  analysisApi,
  AnalysisResult,
  ImputationCandidate,
  OutlierResult,
  SemanticMappingRow,
  ValidationCandidate,
} from '@/lib/api';
import { toast } from '@/lib/toast';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import PipelineStageSummary from '@/components/PipelineStageSummary';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/Tabs';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { SkeletonCard } from '@/components/ui/Skeleton';
import HealthSummary from '@/components/analysis/HealthSummary';
import SemanticTable from '@/components/analysis/SemanticTable';
import ValidationTable from '@/components/analysis/ValidationTable';
import ImputationList from '@/components/analysis/ImputationList';
import OutlierGrid from '@/components/analysis/OutlierGrid';

function semanticRows(results: AnalysisResult): SemanticMappingRow[] {
  if (Array.isArray(results.semantic_mapping) && results.semantic_mapping.length > 0) {
    return results.semantic_mapping;
  }
  return Object.entries(results.semantic || {}).map(([column, domain]) => ({
    column,
    domain: String(domain),
  }));
}

export default function AnalysisPage() {
  const params = useParams();
  const id = Number(params.id);
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Record<string, 'keep' | 'delete' | 'normalize'>>({});
  const [applying, setApplying] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadResults = () => {
    setLoading(true);
    analysisApi
      .getResults(id)
      .then(setResults)
      .catch(() => setLoadError('Failed to load analysis results'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleDecision = (column: string, decision: 'keep' | 'delete' | 'normalize') => {
    setDecisions((prev) => ({ ...prev, [column]: decision }));
  };

  const handleSubmit = async () => {
    if (Object.keys(decisions).length === 0) {
      toast.info('Select outlier decisions before submitting');
      return;
    }
    setSubmitting(true);
    try {
      await analysisApi.submitDecisions(id, decisions);
      toast.success('Decisions submitted successfully');
    } catch {
      toast.error('Failed to submit decisions');
    } finally {
      setSubmitting(false);
    }
  };

  const handleApply = async () => {
    setApplying(true);
    try {
      const summary = await analysisApi.applyDecisions(id);
      toast.success(`Derived dataset saved (${summary.rows_after} rows)`);
      const refreshed = await analysisApi.getResults(id);
      setResults(refreshed);
    } catch {
      toast.error('Failed to apply decisions');
    } finally {
      setApplying(false);
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
      <Alert variant="error" title="Analysis not found" onRetry={loadResults}>
        {loadError || 'Unable to load this analysis.'}
      </Alert>
    );
  }

  const rows = semanticRows(results);
  const phase3 = results.phase3 || {};
  const validationCandidates = (phase3.validation_candidates || []) as ValidationCandidate[];
  const imputationCandidates = (phase3.imputation_candidates || []) as ImputationCandidate[];
  const outlierEntries = Object.entries(results.outliers || {}) as [string, OutlierResult][];
  const outliersMap = Object.fromEntries(outlierEntries);
  const clusters = results.clusters || [];
  const graphEdges = (results.schema_graph?.edges || []) as Array<{
    source?: string;
    target?: string;
    weight?: number;
  }>;
  const datasetType = (results.dataset_context as { dataset_type?: string })?.dataset_type;
  const weighted = results.weighted_profile;

  return (
    <div className="pb-24">
      <WorkflowStepper currentStep={3} className="mb-8" />
      <PageHeader
        title={`Analysis #${id}`}
        description="Review pipeline outputs, record outlier decisions, and generate your audit report."
      />

      <Tabs defaultValue="overview" className="mb-6">
        <TabsList className="mb-2">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="semantic">Semantic</TabsTrigger>
          <TabsTrigger value="validation">Validation</TabsTrigger>
          <TabsTrigger value="outliers">Outliers</TabsTrigger>
          <TabsTrigger value="imputation">Imputation</TabsTrigger>
          <TabsTrigger value="report">Weights & report</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="space-y-6">
            <PipelineStageSummary auditLogs={results.audit_logs} phase3={phase3 as Record<string, unknown>} />
            {datasetType && (
              <Card>
                <p className="text-xs uppercase tracking-wide text-text-muted">Dataset archetype</p>
                <p className="text-lg font-semibold text-text mt-1">{datasetType}</p>
              </Card>
            )}
            {results.health && <HealthSummary health={results.health} />}
          </div>
        </TabsContent>

        <TabsContent value="semantic">
          <SemanticTable rows={rows} clusters={clusters} graphEdges={graphEdges} />
        </TabsContent>

        <TabsContent value="validation">
          <ValidationTable candidates={validationCandidates} />
        </TabsContent>

        <TabsContent value="outliers">
          <OutlierGrid outliers={outliersMap} onDecision={handleDecision} />
        </TabsContent>

        <TabsContent value="imputation">
          <ImputationList candidates={imputationCandidates} />
        </TabsContent>

        <TabsContent value="report">
          <div className="space-y-6">
            {weighted?.applied ? (
              <Card title="Survey weights">
                <p className="text-sm text-text-muted mb-2">
                  Column:{' '}
                  <span className="font-mono text-text">{weighted.weight_column}</span>
                  {weighted.effective_sample_size != null &&
                    ` · effective n ≈ ${weighted.effective_sample_size.toFixed(1)}`}
                </p>
                {weighted.weighted_numeric_means && (
                  <details className="text-sm">
                    <summary className="cursor-pointer text-primary hover:underline">
                      Weighted means (JSON)
                    </summary>
                    <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-surface p-3 text-xs font-mono border border-border">
                      {JSON.stringify(weighted.weighted_numeric_means, null, 2)}
                    </pre>
                  </details>
                )}
              </Card>
            ) : (
              <Card>
                <p className="text-sm text-text-muted">
                  {weighted?.reason || 'Survey weights were not applied for this dataset.'}
                </p>
              </Card>
            )}

            {results.derived_dataset && (
              <Card title="Derived dataset">
                <pre className="text-xs font-mono text-text-muted overflow-auto max-h-32">
                  {JSON.stringify(results.derived_dataset, null, 2)}
                </pre>
              </Card>
            )}

            {results.content_hash && (
              <Card title="Report integrity">
                <p className="text-xs uppercase tracking-wide text-text-muted mb-2">SHA-256 content hash</p>
                <p className="font-mono text-sm text-text break-all">{results.content_hash}</p>
              </Card>
            )}

            <Card title="Audit report">
              <p className="text-sm text-text-muted mb-4">
                Download the tamper-proof PDF report for this analysis.
              </p>
              <Link href={`/reports/${id}`}>
                <Button variant="secondary">View PDF report</Button>
              </Link>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      <div
        className="fixed bottom-0 left-0 right-0 md:left-64 z-20 border-t border-border bg-surface-card/95 backdrop-blur px-4 md:px-8 py-4"
        role="toolbar"
        aria-label="Analysis actions"
      >
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm text-text-muted">
            {Object.keys(decisions).length > 0 && (
              <Badge variant="default">{Object.keys(decisions).length} decisions pending</Badge>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={handleSubmit}
              disabled={submitting || outlierEntries.length === 0}
            >
              {submitting ? 'Submitting…' : 'Submit decisions'}
            </Button>
            <Button variant="outline" onClick={handleApply} disabled={applying}>
              {applying ? 'Applying…' : 'Apply to derived dataset'}
            </Button>
            <Link href={`/reports/${id}`}>
              <Button>Download PDF report</Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
