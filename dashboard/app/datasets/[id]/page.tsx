'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { datasetsApi, analysisApi, Dataset, DatasetProfile } from '@/lib/api';
import { toast } from '@/lib/toast';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import Card from '@/components/ui/Card';
import StatCard from '@/components/ui/StatCard';
import { Alert } from '@/components/ui/Alert';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { formatIndiaTime } from '@/lib/datetime';
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
  HeartPulse,
} from 'lucide-react';

function fmt(n: number | null | undefined, suffix = '') {
  if (n == null || Number.isNaN(n)) return '—';
  return `${n.toLocaleString()}${suffix}`;
}

function fmtPct(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return '—';
  return `${n}%`;
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
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      datasetsApi.get(id),
      datasetsApi.getProfile(id).catch(() => null),
    ])
      .then(([ds, prof]) => {
        setDataset(ds);
        setProfile(prof);
      })
      .catch(() => setError('Dataset not found'))
      .finally(() => setLoading(false));
  }, [id]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    setProgress('Starting analysis…');
    let analysisId: number | undefined;
    const startedAt = Date.now();
    try {
      const started = await analysisApi.runAsync(id);
      analysisId = started.id ?? started.analysis_id;
      if (!analysisId) throw new Error('No analysis ID returned');

      const final = await analysisApi.pollUntilComplete(analysisId, (st) => {
        const elapsedMin = Math.floor((Date.now() - startedAt) / 60000);
        const suffix =
          st.status === 'running' || st.status === 'pending'
            ? ' — first run can take 10–20 min while models load'
            : '';
        setProgress(
          `Status: ${st.status}${st.error_message ? ` — ${st.error_message}` : ''} (${elapsedMin}m)${suffix}`
        );
      });

      if (final.status === 'failed') {
        throw new Error(final.error_message || 'Analysis failed');
      }

      toast.success('Analysis complete — entering pipeline wizard');
      router.push(`/analysis/${analysisId}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Analysis failed';
      if (analysisId && msg.includes('timed out')) {
        try {
          const st = await analysisApi.getStatus(analysisId);
          if (st.status === 'running' || st.status === 'pending') {
            toast.info(
              `Analysis #${analysisId} is still running on the server. Check back in a few minutes or open the analysis page.`
            );
            setProgress(`Analysis #${analysisId} still running on server…`);
            setError(null);
            return;
          }
        } catch {
          /* fall through to generic error */
        }
      }
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

  const rowCount = profile?.row_count ?? dataset.row_count;
  const columnCount = profile?.column_count ?? dataset.column_count;
  const fileSizeMb = profile?.file_size_mb ?? dataset.file_size_mb;
  const memoryUsageMb = profile?.memory_usage_mb ?? dataset.memory_usage_mb;
  const numericColumns = profile?.numeric_columns ?? dataset.numeric_columns;
  const categoricalColumns = profile?.categorical_columns ?? dataset.categorical_columns;
  const missingCells = profile?.missing_cells ?? dataset.missing_cells;
  const duplicateRows = profile?.duplicate_rows ?? dataset.duplicate_rows;
  const completenessScore = profile?.completeness_score ?? dataset.completeness_pct;
  const consistencyScore = profile?.consistency_score ?? dataset.consistency_pct;
  const healthScore = profile?.health_score;

  const previewRows = profile?.preview_rows ?? dataset.preview_rows ?? [];
  const columnList = profile?.column_list ?? dataset.column_list ?? [];
  const previewColumns =
    columnList.length > 0
      ? columnList
      : previewRows.length > 0
      ? Object.keys(previewRows[0])
      : [];

  const fileSizeLabel =
    fileSizeMb != null && fileSizeMb > 0 ? `${fileSizeMb} MB` : '—';

  const statusVariant =
    dataset.status === 'ingested'
      ? 'success'
      : dataset.status === 'pending'
      ? 'warning'
      : dataset.status === 'failed'
      ? 'danger'
      : 'muted';

  const metaItems = [
    { icon: Rows3, label: 'Rows', value: fmt(rowCount) },
    { icon: Columns3, label: 'Columns', value: fmt(columnCount) },
    { icon: HardDrive, label: 'File size', value: fileSizeLabel },
    {
      icon: Calendar,
      label: 'Uploaded (IST)',
      value: formatIndiaTime(dataset.created_at),
    },
  ];

  const objectKeyDisplay =
    dataset.object_key ??
    (dataset.storage_path ? `local:${dataset.storage_path.split(/[/\\]/).pop()}` : '—');

  return (
    <div>
      <WorkflowStepper currentStep={analyzing ? 2 : 1} className="mb-8" />

      <PageHeader
        title={dataset.filename}
        description="Review dataset metadata, then run the full intelligence pipeline to begin analysis."
        actions={<Badge variant={statusVariant}>{dataset.status}</Badge>}
      />

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

      <Card title="Dataset summary" className="mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatCard label="Rows" value={fmt(rowCount)} icon={Rows3} />
          <StatCard label="Columns" value={fmt(columnCount)} icon={Columns3} />
          <StatCard label="File size" value={fileSizeLabel} icon={HardDrive} />
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

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <StatCard label="Completeness" value={fmtPct(completenessScore)} icon={CheckCircle2} />
        <StatCard label="Consistency" value={fmtPct(consistencyScore)} icon={ShieldCheck} />
        <StatCard label="Health score" value={fmtPct(healthScore)} icon={HeartPulse} />
        <StatCard label="Duplicates" value={fmt(duplicateRows)} icon={Copy} />
        <StatCard label="Missing values" value={fmt(missingCells)} icon={AlertTriangle} />
      </div>

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

      <Card title="File details" className="mb-6">
        <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
          {[
            { label: 'Status', value: dataset.status },
            { label: 'Storage provider', value: dataset.storage_provider ?? 'local' },
            { label: 'Upload status', value: dataset.upload_status ?? 'UPLOADED' },
            {
              label: 'Profile version',
              value: profile?.profile_version != null ? String(profile.profile_version) : '—',
            },
            { label: 'Object key', value: objectKeyDisplay, mono: true },
            ...(dataset.storage_path && !dataset.object_key
              ? [{ label: 'Storage path', value: dataset.storage_path, mono: true }]
              : []),
          ].map(({ label, value, mono }) => (
            <div key={label} className={label === 'Storage path' ? 'sm:col-span-2' : undefined}>
              <dt className="text-xs text-text-muted uppercase tracking-wide">{label}</dt>
              <dd
                className={cn(
                  'mt-1 font-medium text-text',
                  mono ? 'font-mono text-xs break-all' : 'truncate'
                )}
              >
                {value}
              </dd>
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
              take 10–20 minutes while ML models download.
            </p>
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
            {(rowCount === 0 || columnCount === 0) && !analyzing && (
              <p className="text-xs text-warning">
                Row/column counts are missing — re-upload the file or check that .xls has xlrd
                installed on the API server.
              </p>
            )}
          </div>
        </div>

        {analyzing && (
          <div className="mt-6 p-4 rounded-xl bg-accent/5 border border-accent/20" role="status">
            <div className="flex items-center gap-3 mb-2">
              <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />
              <p className="text-sm font-medium text-text">{progress}</p>
            </div>
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
