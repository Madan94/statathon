'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { datasetsApi, analysisApi, Dataset } from '@/lib/api';
import { toast } from '@/lib/toast';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import { StatCard } from '@/components/ui/StatCard';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Alert } from '@/components/ui/Alert';
import { Skeleton, SkeletonCard } from '@/components/ui/Skeleton';
import { Rows3, Columns3, Activity, Calendar } from 'lucide-react';

export default function DatasetPage() {
  const params = useParams();
  const router = useRouter();
  const id = Number(params.id);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    datasetsApi
      .get(id)
      .then(setDataset)
      .catch(() => setError('Dataset not found'))
      .finally(() => setLoading(false));
  }, [id]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    setProgress('Starting analysis…');
    try {
      const started = await analysisApi.runAsync(id);
      const analysisId = started.id ?? started.analysis_id;
      if (!analysisId) throw new Error('No analysis id returned');

      const final = await analysisApi.pollUntilComplete(analysisId, (st) => {
        setProgress(`Status: ${st.status}${st.error_message ? ` — ${st.error_message}` : ''}`);
      });

      if (final.status === 'failed') {
        throw new Error(final.error_message || 'Analysis failed');
      }

      toast.success('Analysis complete');
      router.push(`/analysis/${analysisId}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Analysis failed';
      setError(msg);
      toast.error(msg);
      setProgress(null);
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <SkeletonCard />
      </div>
    );
  }

  if (!dataset) {
    return (
      <Alert variant="error" title="Dataset not found">
        {error || 'This dataset could not be loaded.'}
      </Alert>
    );
  }

  const statusVariant =
    dataset.status === 'ingested' ? 'success' : dataset.status === 'pending' ? 'warning' : 'muted';

  return (
    <div>
      <WorkflowStepper currentStep={analyzing ? 2 : 1} className="mb-8" />
      <PageHeader
        title={dataset.filename}
        description="Review dataset profile, then run the full intelligence pipeline."
        actions={
          <Badge variant={statusVariant}>{dataset.status}</Badge>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Rows" value={dataset.row_count || '—'} icon={Rows3} />
        <StatCard label="Columns" value={dataset.column_count || '—'} icon={Columns3} />
        <StatCard label="Status" value={dataset.status} icon={Activity} />
        <StatCard
          label="Created"
          value={new Date(dataset.created_at).toLocaleDateString()}
          icon={Calendar}
        />
      </div>

      {dataset.row_count === 0 && (
        <Alert variant="info" className="mb-6">
          Row and column counts will populate after analysis completes.
        </Alert>
      )}

      <Card>
        <h2 className="text-lg font-semibold text-text mb-2">Run analysis</h2>
        <p className="text-sm text-text-muted mb-6">
          Executes semantic mapping, validation, outlier detection, imputation scoring, and report
          generation. First run may download the ML model (~1–3 minutes).
        </p>
        <Button onClick={handleAnalyze} disabled={analyzing} size="lg" className="w-full sm:w-auto">
          {analyzing ? 'Analyzing…' : 'Run analysis'}
        </Button>
        {analyzing && (
          <div className="mt-6 p-4 rounded-lg bg-accent-muted/50 border border-border" role="status">
            <div className="flex items-center gap-3">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent" />
              <p className="text-sm text-text">{progress}</p>
            </div>
            <p className="text-xs text-text-muted mt-2">
              Downloading ML model on first run can take 1–3 minutes. Please keep this tab open.
            </p>
          </div>
        )}
        {error && !analyzing && (
          <Alert variant="error" className="mt-4" onRetry={handleAnalyze}>
            {error}
          </Alert>
        )}
      </Card>
    </div>
  );
}
