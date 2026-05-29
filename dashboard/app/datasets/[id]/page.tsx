'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { datasetsApi, analysisApi, Dataset } from '@/lib/api';
import { toast } from '@/lib/toast';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import Card from '@/components/ui/Card';
import StatCard from '@/components/ui/StatCard';
import { Alert } from '@/components/ui/Alert';
import { Skeleton } from '@/components/ui/Skeleton';
import {
  Rows3,
  Columns3,
  Calendar,
  HardDrive,
  Fingerprint,
  Play,
  Loader2,
  Hash,
  Tags,
  AlertTriangle,
  Copy,
  Database,
  CheckCircle2,
  ShieldCheck,
} from 'lucide-react';

function fmt(n: number | null | undefined, suffix = '') {
  if (n == null || Number.isNaN(n)) return '—';
  return `${n.toLocaleString()}${suffix}`;
}

function fmtBytes(b: number | null | undefined) {
  if (b == null || b <= 0) return '—';
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(2)} MB`;
}

function fmtFileSize(dataset: Dataset) {
  if (dataset.file_size_mb != null) return `${dataset.file_size_mb} MB`;
  return fmtBytes(dataset.file_size ?? dataset.file_size_bytes);
}

function cellValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

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
      .then((d) => setDataset(d))
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
      if (!analysisId) throw new Error('No analysis ID returned');

      const final = await analysisApi.pollUntilComplete(analysisId, (st) => {
        setProgress(`Status: ${st.status}${st.error_message ? ` — ${st.error_message}` : ''}`);
      });

      if (final.status === 'failed') {
        throw new Error(final.error_message || 'Analysis failed');
      }

      toast.success('Analysis complete — entering pipeline wizard');
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
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (!dataset) {
    return (
      <Alert variant="error" title="Dataset not found">
        {error ?? 'This dataset could not be loaded.'}
      </Alert>
    );
  }

  const health = dataset.health_summary ?? {};
  const previewRows =
    dataset.preview_rows ??
    (Array.isArray(health.preview_rows) ? health.preview_rows : []);
  const columnList =
    dataset.column_list ??
    (Array.isArray(health.column_list) ? health.column_list : []);
  const previewColumns =
    columnList.length > 0
      ? columnList
      : previewRows.length > 0
      ? Object.keys(previewRows[0])
      : [];

  const missingCells = dataset.missing_cells ?? health.missing_cells;
  const duplicateRows = dataset.duplicate_rows ?? health.duplicate_rows;
  const numericColumns = dataset.numeric_columns ?? health.numeric_columns;
  const categoricalColumns = dataset.categorical_columns ?? health.categorical_columns;
  const memoryUsageMb = dataset.memory_usage_mb ?? health.memory_usage_mb;
  const completenessPct = dataset.completeness_pct ?? health.completeness_pct;
  const consistencyPct = dataset.consistency_pct ?? health.consistency_pct;

  const statusVariant =
    dataset.status === 'ingested'
      ? 'success'
      : dataset.status === 'pending'
      ? 'warning'
      : dataset.status === 'failed'
      ? 'danger'
      : 'muted';

  const metaItems = [
    { icon: Rows3, label: 'Rows', value: fmt(dataset.row_count) },
    { icon: Columns3, label: 'Columns', value: fmt(dataset.column_count) },
    { icon: HardDrive, label: 'File size', value: fmtFileSize(dataset) },
    {
      icon: Calendar,
      label: 'Uploaded',
      value: dataset.created_at
        ? new Date(dataset.created_at).toLocaleString()
        : '—',
    },
  ];

  return (
    <div>
      <WorkflowStepper currentStep={analyzing ? 2 : 1} className="mb-8" />

      <PageHeader
        title={dataset.filename}
        description="Review dataset metadata, then run the full intelligence pipeline to begin analysis."
        actions={<Badge variant={statusVariant}>{dataset.status}</Badge>}
      />

      {/* Meta stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {metaItems.map(({ icon: Icon, label, value }) => (
          <Card key={label} className="!p-4">
            <div className="flex items-center gap-3">
              <Icon className="h-8 w-8 text-primary shrink-0" />
              <div>
                <p className="text-xl font-bold text-text">{value}</p>
                <p className="text-xs text-text-muted">{label}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Dataset summary */}
      <Card title="Dataset summary" className="mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatCard label="Rows" value={fmt(dataset.row_count)} icon={Rows3} />
          <StatCard label="Columns" value={fmt(dataset.column_count)} icon={Columns3} />
          <StatCard label="File size" value={fmtFileSize(dataset)} icon={HardDrive} />
          <StatCard
            label="Memory usage"
            value={memoryUsageMb != null ? `${memoryUsageMb} MB` : '—'}
            icon={Database}
          />
        </div>

        <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 text-sm border-t border-border pt-4">
          {[
            { label: 'Numeric columns', value: fmt(numericColumns), icon: Hash },
            { label: 'Categorical columns', value: fmt(categoricalColumns), icon: Tags },
            { label: 'Missing cells', value: fmt(missingCells), icon: AlertTriangle },
            { label: 'Duplicate rows', value: fmt(duplicateRows), icon: Copy },
          ].map(({ label, value, icon: Icon }) => (
            <div key={label} className="flex items-start gap-2">
              <Icon className="h-4 w-4 text-text-muted mt-0.5 shrink-0" />
              <div>
                <dt className="text-xs text-text-muted uppercase tracking-wide">{label}</dt>
                <dd className="mt-0.5 font-semibold text-text">{value}</dd>
              </div>
            </div>
          ))}
        </dl>
      </Card>

      {/* Dataset health summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          label="Completeness"
          value={completenessPct != null ? `${completenessPct}%` : '—'}
          icon={CheckCircle2}
        />
        <StatCard
          label="Consistency"
          value={consistencyPct != null ? `${consistencyPct}%` : '—'}
          icon={ShieldCheck}
        />
        <StatCard label="Duplicates" value={fmt(duplicateRows)} icon={Copy} />
        <StatCard label="Missing values" value={fmt(missingCells)} icon={AlertTriangle} />
      </div>

      {/* Column preview */}
      {previewColumns.length > 0 && previewRows.length > 0 && (
        <Card title="Column preview (first 10 rows)" className="mb-6">
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="min-w-full text-sm">
              <thead className="bg-surface border-b border-border">
                <tr>
                  {previewColumns.map((col) => (
                    <th
                      key={col}
                      className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-text-muted whitespace-nowrap"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, rowIdx) => (
                  <tr key={rowIdx} className="border-b border-border last:border-0">
                    {previewColumns.map((col) => (
                      <td key={col} className="px-3 py-2 text-text whitespace-nowrap">
                        {cellValue(row[col])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* File details */}
      <Card title="File details" className="mb-6">
        <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
          {[
            { label: 'Status', value: dataset.status },
            { label: 'Storage provider', value: dataset.storage_provider ?? 'local' },
            { label: 'Upload status', value: dataset.upload_status ?? '—' },
            { label: 'Object key', value: dataset.object_key ?? '—' },
          ].map(({ label, value }) => (
            <div key={label}>
              <dt className="text-xs text-text-muted uppercase tracking-wide">{label}</dt>
              <dd className="mt-1 font-medium text-text truncate">{value}</dd>
            </div>
          ))}
          {dataset.checksum && (
            <div className="sm:col-span-2 lg:col-span-3">
              <dt className="flex items-center gap-1 text-xs text-text-muted uppercase tracking-wide">
                <Fingerprint className="h-3 w-3" /> Checksum
              </dt>
              <dd className="mt-1 font-mono text-xs text-text-muted break-all">
                {dataset.checksum}
              </dd>
            </div>
          )}
        </dl>
      </Card>

      {/* Analysis launcher */}
      <Card>
        <div className="flex flex-col sm:flex-row sm:items-start gap-6">
          <div className="flex-1">
            <h2 className="text-lg font-semibold text-text mb-1 flex items-center gap-2">
              <Play className="h-5 w-5 text-primary" aria-hidden />
              Run analysis pipeline
            </h2>
            <p className="text-sm text-text-muted">
              Runs semantic mapping, column clustering, schema graph construction, validation,
              outlier detection, imputation scoring and PDF report generation. The first run may
              download the ML model (~1–3 min).
            </p>

            <ul className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs text-text-muted">
              {[
                'Semantic domain mapping',
                'Column clustering',
                'Schema graph',
                'Knowledge graph',
                'Outlier detection (Z-score + IQR)',
                'Missing value scoring',
                'Validation rules',
                'PDF audit report',
              ].map((step) => (
                <li key={step} className="flex items-center gap-1.5">
                  <span className="h-1 w-1 rounded-full bg-accent shrink-0" />
                  {step}
                </li>
              ))}
            </ul>
          </div>

          <div className="sm:pt-1 flex flex-col items-start gap-3">
            <Button
              onClick={handleAnalyze}
              disabled={analyzing}
              size="lg"
              className="w-full sm:w-auto flex items-center gap-2"
            >
              {analyzing ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Analysing…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Run analysis
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Progress */}
        {analyzing && (
          <div
            className="mt-6 p-4 rounded-xl bg-accent/5 border border-accent/20"
            role="status"
            aria-live="polite"
          >
            <div className="flex items-center gap-3 mb-2">
              <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />
              <p className="text-sm font-medium text-text">{progress}</p>
            </div>
            <div className="w-full h-1.5 rounded-full bg-border overflow-hidden">
              <div className="h-full bg-accent rounded-full animate-pulse w-3/5" />
            </div>
            <p className="text-xs text-text-muted mt-2">
              Downloading the ML model on first run takes 1–3 minutes. Keep this tab open.
            </p>
          </div>
        )}

        {/* Error */}
        {error && !analyzing && (
          <Alert variant="error" className="mt-4" onRetry={handleAnalyze}>
            {error}
          </Alert>
        )}
      </Card>
    </div>
  );
}
