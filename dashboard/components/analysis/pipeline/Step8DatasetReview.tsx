'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { analysisApi } from '@/lib/api';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { toast } from '@/lib/toast';
import {
  CheckCircle2, Download, Loader2, Search, FileText, ArrowLeft,
} from 'lucide-react';

type ReviewPayload = Awaited<ReturnType<typeof analysisApi.getDatasetReview>>;
type RowsPayload = Awaited<ReturnType<typeof analysisApi.getDatasetReviewRows>>;

interface Props {
  analysisId: number;
  onBack: () => void;
}

const DOWNLOADS = [
  { kind: 'original_csv', label: 'Original CSV' },
  { kind: 'original_xlsx', label: 'Original Excel' },
  { kind: 'processed_csv', label: 'Processed CSV' },
  { kind: 'processed_xlsx', label: 'Processed Excel' },
  { kind: 'audit_summary', label: 'Audit Summary' },
  { kind: 'transformation_summary', label: 'Transformation Summary' },
] as const;

function formatNum(n: number | undefined) {
  return (n ?? 0).toLocaleString();
}

function DatasetTable({
  title,
  side,
  analysisId,
  columns,
  search,
  columnFilter,
}: {
  title: string;
  side: 'original' | 'processed';
  analysisId: number;
  columns: string[];
  search: string;
  columnFilter: string;
}) {
  const [rows, setRows] = useState<RowsPayload | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const limit = 50;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await analysisApi.getDatasetReviewRows(analysisId, side, {
        offset,
        limit,
        search: search || undefined,
        columnFilter: columnFilter || undefined,
        columns: columnFilter ? [columnFilter] : undefined,
      });
      setRows(payload);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load rows');
    } finally {
      setLoading(false);
    }
  }, [analysisId, side, offset, search, columnFilter]);

  useEffect(() => {
    setOffset(0);
  }, [search, columnFilter, side]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleCols = rows?.columns?.length
    ? rows.columns
    : columns.slice(0, 8);

  return (
    <Card title={title} className="min-h-[320px]">
      {loading && !rows ? (
        <p className="text-sm text-text-muted flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </p>
      ) : (
        <>
          <div className="overflow-auto max-h-[420px] border rounded-lg">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-card z-10">
                <tr className="border-b border-border text-left text-text-muted uppercase">
                  <th className="p-2">Row</th>
                  {visibleCols.map((col) => (
                    <th key={col} className="p-2 whitespace-nowrap">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(rows?.rows ?? []).map((row) => (
                  <tr key={String(row._row_index)} className="border-b border-border/50 hover:bg-border/20">
                    <td className="p-2 font-mono">{String(row._row_index)}</td>
                    {visibleCols.map((col) => (
                      <td key={col} className="p-2 font-mono max-w-[140px] truncate">
                        {row[col] == null ? 'NULL' : String(row[col])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between mt-3 text-xs text-text-muted">
            <span>
              Showing {offset + 1}–{Math.min(offset + limit, rows?.total_rows ?? 0)} of {formatNum(rows?.total_rows)}
            </span>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" disabled={offset === 0 || loading} onClick={() => setOffset((o) => Math.max(0, o - limit))}>
                Previous
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={loading || !rows || offset + limit >= (rows.total_rows ?? 0)}
                onClick={() => setOffset((o) => o + limit)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

export default function Step8DatasetReview({ analysisId, onBack }: Props) {
  const router = useRouter();
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [search, setSearch] = useState('');
  const [columnFilter, setColumnFilter] = useState('');
  const [rowIndex, setRowIndex] = useState('');
  const [rowDetail, setRowDetail] = useState<Awaited<ReturnType<typeof analysisApi.getDatasetReviewRow>> | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await analysisApi.getDatasetReview(analysisId);
      setReview(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dataset review');
    } finally {
      setLoading(false);
    }
  }, [analysisId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const summaryCards = useMemo(() => {
    if (!review) return [];
    const s = review.summary;
    return [
      { label: 'Rows Before', value: s.rows_before },
      { label: 'Rows After', value: s.rows_after },
      { label: 'Rows Removed', value: s.rows_removed },
      { label: 'Columns Before', value: s.columns_before },
      { label: 'Columns After', value: s.columns_after },
      { label: 'Columns Renamed', value: s.columns_renamed ?? 0 },
      { label: 'Columns Removed', value: s.columns_removed },
      { label: 'Columns Excluded', value: s.columns_excluded ?? 0 },
      { label: 'Missing Before', value: s.missing_values_before },
      { label: 'Missing After', value: s.missing_values_after },
    ];
  }, [review]);

  const handleApprove = async () => {
    setApproving(true);
    try {
      const res = await analysisApi.approveDatasetReview(analysisId);
      if (!res.success) throw new Error('Approval failed');
      toast.success('Dataset approved — you can proceed to Report');
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to approve dataset');
    } finally {
      setApproving(false);
    }
  };

  const handleDownload = async (kind: string) => {
    try {
      const res = await fetch(analysisApi.datasetReviewDownloadUrl(analysisId, kind), {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const disposition = res.headers.get('Content-Disposition') ?? '';
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match?.[1] ?? `analysis_${analysisId}_${kind}`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Download failed');
    }
  };

  const inspectRow = async () => {
    const idx = parseInt(rowIndex, 10);
    if (Number.isNaN(idx)) return;
    try {
      const detail = await analysisApi.getDatasetReviewRow(analysisId, idx);
      setRowDetail(detail);
    } catch {
      setRowDetail(null);
    }
  };

  if (loading && !review) {
    return (
      <div className="pb-24">
        <WorkflowStepper currentStep={3} className="mb-5" />
        <AnalysisStepper currentStep={8} className="mb-8" />
        <p className="text-sm text-text-muted flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading dataset review…
        </p>
      </div>
    );
  }

  if (error || !review) {
    return (
      <div className="pb-24">
        <WorkflowStepper currentStep={3} className="mb-5" />
        <AnalysisStepper currentStep={8} className="mb-8" />
        <Alert variant="error" title="Dataset review unavailable">{error ?? 'Unknown error'}</Alert>
        <Button variant="ghost" className="mt-4" onClick={onBack}>← Back to column analysis</Button>
      </div>
    );
  }

  const allColumns = review.processed_dataset.columns.length
    ? review.processed_dataset.columns
    : review.original_dataset.columns;

  return (
    <div className="pb-28">
      <WorkflowStepper currentStep={3} className="mb-5" />
      <AnalysisStepper currentStep={8} className="mb-8" />
      <PageHeader
        title="Dataset review & approval"
        description="Inspect the final transformed dataset after all review phases before entering Report."
      />

      {!review.missing_value_completed && (
        <Alert variant="warning" title="Missing value review incomplete" className="mb-6">
          Complete Missing Value Intelligence before reviewing the final dataset.
        </Alert>
      )}

      {review.dataset_review_completed && (
        <Alert variant="success" title="Dataset approved" className="mb-6">
          This dataset has been approved. You may proceed to the Report phase.
        </Alert>
      )}

      <section className="mb-8">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-text-muted mb-3">Dataset overview</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {summaryCards.map((c) => (
            <div key={c.label} className="rounded-xl border border-border p-4">
              <p className="text-xs text-text-muted">{c.label}</p>
              <p className="text-2xl font-bold mt-1">{formatNum(c.value)}</p>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3 mt-3 text-sm">
          <div className="rounded-lg border p-3">Rule violations fixed: <strong>{formatNum(review.summary.rule_violations_fixed)}</strong></div>
          <div className="rounded-lg border p-3">Anomalies processed: <strong>{formatNum(review.summary.anomalies_processed)}</strong></div>
          <div className="rounded-lg border p-3">Values imputed: <strong>{formatNum(review.summary.values_imputed)}</strong></div>
        </div>
      </section>

      <section className="mb-8">
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search rows…"
              className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-surface-card text-sm"
            />
          </div>
          <select
            value={columnFilter}
            onChange={(e) => setColumnFilter(e.target.value)}
            className="rounded-lg border border-border px-3 py-2 text-sm bg-surface-card min-w-[160px]"
          >
            <option value="">All columns</option>
            {allColumns.map((col) => (
              <option key={col} value={col}>{col}</option>
            ))}
          </select>
        </div>
        <div className="grid lg:grid-cols-2 gap-4">
          <DatasetTable
            title="Original dataset"
            side="original"
            analysisId={analysisId}
            columns={review.original_dataset.columns}
            search={search}
            columnFilter={columnFilter}
          />
          <DatasetTable
            title="Processed dataset"
            side="processed"
            analysisId={analysisId}
            columns={review.processed_dataset.columns}
            search={search}
            columnFilter={columnFilter}
          />
        </div>
      </section>

      <section className="mb-8">
        <Card title="Row-level inspection">
          <div className="flex gap-2 mb-3">
            <input
              value={rowIndex}
              onChange={(e) => setRowIndex(e.target.value)}
              placeholder="Row index"
              className="flex-1 rounded border px-2 py-1 text-sm bg-surface-card"
            />
            <Button variant="secondary" size="sm" onClick={() => void inspectRow()}>Inspect</Button>
          </div>
          {rowDetail ? (
            <div className="text-xs space-y-3 max-h-64 overflow-auto">
              <div>
                <p className="font-semibold mb-1">Original row</p>
                <pre className="bg-border/20 p-2 rounded overflow-auto">{JSON.stringify(rowDetail.original_row, null, 2)}</pre>
              </div>
              <div>
                <p className="font-semibold mb-1">Processed row</p>
                <pre className="bg-border/20 p-2 rounded overflow-auto">{JSON.stringify(rowDetail.processed_row, null, 2)}</pre>
              </div>
              {rowDetail.changed_cells.length > 0 && (
                <div>
                  <p className="font-semibold mb-1">Changed cells</p>
                  <ul className="space-y-1">
                    {rowDetail.changed_cells.map((c, i) => (
                      <li key={i}>{c.column}: {String(c.before)} → {String(c.after)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-text-muted">Enter a row index to compare original vs processed.</p>
          )}
        </Card>
      </section>

      <section className="mb-8">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-text-muted mb-3">Downloads</h3>
        <div className="flex flex-wrap gap-2">
          {DOWNLOADS.map((d) => (
            <Button key={d.kind} variant="outline" size="sm" className="gap-1" onClick={() => handleDownload(d.kind)}>
              <Download className="h-3.5 w-3.5" /> {d.label}
            </Button>
          ))}
        </div>
      </section>

      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface-card/95 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" onClick={onBack} className="gap-1">
            <ArrowLeft className="h-4 w-4" /> Back to column analysis
          </Button>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={!review.can_approve || approving}
              onClick={() => void handleApprove()}
              className="gap-2"
            >
              {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Approve dataset
            </Button>
            <Button
              disabled={!review.can_proceed_to_report}
              onClick={() => router.push(`/report-builder?analysisId=${analysisId}`)}
              className="gap-2"
            >
              <FileText className="h-4 w-4" />
              Proceed to Report →
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
