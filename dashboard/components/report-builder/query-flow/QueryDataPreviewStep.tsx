'use client';

import { useEffect, useMemo, useState } from 'react';
import { Calculator, Check, Database, Edit3, Filter, Scale, Table2 } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { cn } from '@/lib/cn';
import { DatasetWeightTabs } from '@/components/report-builder/binding/DatasetWeightTabs';
import { bindingPhaseApi, type DatasetColumnProfile } from '@/lib/api';
import type { AggregationKind, ReportSectionConfig, SectionMeasure } from '@/lib/reportSection';
import {
  applyPredicates,
  predicateToText,
  reportSectionDatasetStore,
  type DataRow,
  type ReportSectionRequest,
  type SectionExecutionResult,
} from '@/lib/report-section';
import type { AcceptedPreviewMetadata, WeightInsights, WeightMeasureInsight } from '@/lib/report-section/canvasHandoff';

type PreviewAggregation = 'sum' | 'mean' | 'weighted_mean' | 'count' | 'median' | 'min' | 'max';
type PreviewTab = 'data' | 'weight';
type PreviewColumnLimit = 10 | 25 | 50 | 100 | 'all';
type PreviewRowLimit = 5 | 10 | 25 | 50 | 100;

const WEIGHT_SCALE = 100;
const ROW_PREVIEW_CAP = 100; // hard upper bound on rendered preview rows
const ROW_FETCH_LIMIT = 1000; // real rows pulled from the backend stash for the preview
const SAMPLE_ROW_LIMIT = 100;
const COLUMN_LIMITS: PreviewColumnLimit[] = [10, 25, 50, 100, 'all'];
const ROW_LIMITS: PreviewRowLimit[] = [5, 10, 25, 50, 100];

const AGGREGATION_OPTIONS: Array<{ value: PreviewAggregation; label: string }> = [
  { value: 'sum', label: 'Sum' },
  { value: 'mean', label: 'Mean' },
  { value: 'weighted_mean', label: 'Weighted mean' },
  { value: 'count', label: 'Count' },
  { value: 'median', label: 'Median' },
  { value: 'min', label: 'Min' },
  { value: 'max', label: 'Max' },
];

const MULTIPLIER_PATTERNS: RegExp[] = [
  /^multiplier$/i,
  /^mult(iplier)?$/i,
  /multiplier/i,
  /^mlt$/i,
  /^wt$/i,
  /^wgt$/i,
  /^weight$/i,
  /weight/i,
];

interface QueryDataPreviewStepProps {
  columns: DatasetColumnProfile[];
  config: ReportSectionConfig;
  request: ReportSectionRequest;
  execution: SectionExecutionResult;
  acceptanceKey: string;
  acceptedPreview: AcceptedPreviewMetadata | null;
  onConfigChange: (next: ReportSectionConfig) => void;
  onAccept: (metadata: AcceptedPreviewMetadata) => void;
  onBack: () => void;
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const numberValue = Number(value.replace(/,/g, ''));
    if (Number.isFinite(numberValue)) return numberValue;
  }
  return null;
}

function fmtNum(value: number | null | undefined, maxFrac = 2): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return value.toLocaleString('en-IN', { maximumFractionDigits: maxFrac });
}

function cellText(value: unknown): string {
  if (value == null || value === '') return '-';
  if (typeof value === 'number') return fmtNum(value, 3);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function isNumericColumn(column: DatasetColumnProfile): boolean {
  return column.role === 'measure'
    || column.role === 'time'
    || /^int|float|double|decimal|number|numeric/i.test(column.dtype || '')
    || column.minValue != null
    || column.maxValue != null;
}

function detectMultiplierColumn(headers: string[], numericColumns: Set<string>): string | null {
  for (const pattern of MULTIPLIER_PATTERNS) {
    const hit = headers.find((header) => numericColumns.has(header) && pattern.test(header.trim()));
    if (hit) return hit;
  }
  return null;
}

function buildSampleRows(columns: DatasetColumnProfile[]): DataRow[] {
  const maxSamples = Math.min(
    SAMPLE_ROW_LIMIT,
    Math.max(0, ...columns.map((column) => column.sampleValues?.length ?? 0)),
  );
  if (!maxSamples) return [];
  return Array.from({ length: maxSamples }, (_, index) => {
    const row: DataRow = {};
    columns.forEach((column) => {
      row[column.name] = column.sampleValues?.[index] ?? null;
    });
    return row;
  });
}

function uniqueList(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  values.forEach((value) => {
    const clean = (value || '').trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    out.push(clean);
  });
  return out;
}

function effectiveAggregation(measure: SectionMeasure): PreviewAggregation {
  if (measure.agg && AGGREGATION_OPTIONS.some((option) => option.value === measure.agg)) {
    return measure.agg as PreviewAggregation;
  }
  return measure.weighted ? 'weighted_mean' : 'mean';
}

/**
 * Compute weighted vs unweighted aggregates per measure from the accepted
 * filtered slice. Produces the `weight.insights.v1` JSON that travels with the
 * accepted preview into description / components / preview and grounds the
 * report synthesizer. Weighted figures use fᵢ = wᵢ / scale (NSS multiplier).
 */
function buildWeightInsights(
  rows: DataRow[],
  measures: SectionMeasure[],
  weightCol: string | null,
  scale: number,
  filters: AcceptedPreviewMetadata['filters'],
  rowCounts: { rowsScanned?: number; rowsAfterFilter?: number },
): WeightInsights {
  const weightingApplied = measures.some((m) => m.weighted || m.agg === 'weighted_mean');
  let nonPositiveWeightRows = 0;
  if (weightCol) {
    for (const row of rows) {
      const w = toNumber(row[weightCol]);
      if (w == null || w <= 0) nonPositiveWeightRows += 1;
    }
  }

  const measureInsights: WeightMeasureInsight[] = measures.map((measure) => {
    const aggregation = effectiveAggregation(measure);
    const isWeighted = measure.weighted || aggregation === 'weighted_mean';
    let rowsUsed = 0;
    let rowsSkipped = 0;
    let unweightedTotal = 0;
    let weightSum = 0;
    let weightedTotal = 0;
    for (const row of rows) {
      const x = toNumber(row[measure.col]);
      if (x == null) { rowsSkipped += 1; continue; }
      unweightedTotal += x;
      rowsUsed += 1;
      if (weightCol) {
        const w = toNumber(row[weightCol]);
        if (w != null && w > 0) {
          const f = w / scale;
          weightSum += f;
          weightedTotal += x * f;
        }
      }
    }
    const unweightedMean = rowsUsed > 0 ? unweightedTotal / rowsUsed : null;
    const weightedMean = weightSum > 0 ? weightedTotal / weightSum : null;
    const selectedValue =
      aggregation === 'sum' ? unweightedTotal
      : aggregation === 'count' ? rowsUsed
      : aggregation === 'weighted_mean' ? weightedMean
      : unweightedMean;
    return {
      col: measure.col,
      label: measure.label || measure.col,
      aggregation,
      weighted: isWeighted,
      rowsUsed,
      rowsSkipped,
      weightSum: weightCol ? Number(weightSum.toFixed(6)) : null,
      weightedTotal: weightCol ? Number(weightedTotal.toFixed(6)) : null,
      weightedMean: weightedMean != null ? Number(weightedMean.toFixed(6)) : null,
      unweightedTotal: Number(unweightedTotal.toFixed(6)),
      unweightedMean: unweightedMean != null ? Number(unweightedMean.toFixed(6)) : null,
      selectedValue: selectedValue != null ? Number(selectedValue.toFixed(6)) : null,
      delta: weightedMean != null && unweightedMean != null ? Number((weightedMean - unweightedMean).toFixed(6)) : null,
    };
  });

  const notes: string[] = [];
  if (!weightCol) notes.push('No multiplier column selected — all figures are unweighted.');
  else if (!weightingApplied) notes.push(`Multiplier '${weightCol}' is available but no measure is weighted; figures shown are unweighted.`);
  else notes.push(`Survey weighting applied with multiplier '${weightCol}' at scale ${scale} (fᵢ = wᵢ/${scale}).`);
  if (nonPositiveWeightRows > 0) notes.push(`${nonPositiveWeightRows} row(s) had missing/zero/negative weights and were excluded from weighted sums.`);

  return {
    version: 'weight.insights.v1',
    weightColumn: weightCol,
    weightScale: scale,
    weightingApplied,
    rowsScanned: rowCounts.rowsScanned,
    rowsAfterFilter: rowCounts.rowsAfterFilter,
    nonPositiveWeightRows,
    filters,
    measures: measureInsights,
    formula: {
      weightedValue: `xᵢ × wᵢ / ${scale}`,
      weightedTotal: `Σ(xᵢ × wᵢ / ${scale})`,
      weightedMean: `Σ(xᵢ × wᵢ / ${scale}) ÷ Σ(wᵢ / ${scale})`,
    },
    notes,
  };
}

function roleVariant(role: DatasetColumnProfile['role']): 'default' | 'success' | 'warning' | 'muted' {
  if (role === 'measure') return 'success';
  if (role === 'time') return 'warning';
  if (role === 'dimension') return 'default';
  return 'muted';
}

function roleForColumn(columns: DatasetColumnProfile[], columnName: string): DatasetColumnProfile['role'] | 'unknown' {
  return columns.find((column) => column.name === columnName)?.role ?? 'unknown';
}

function warningText(warnings: Array<{ message?: string }>): string[] {
  return warnings.map((warning) => warning.message || '').filter(Boolean);
}

export function QueryDataPreviewStep({
  columns,
  config,
  request,
  execution,
  acceptanceKey,
  acceptedPreview,
  onConfigChange,
  onAccept,
  onBack,
}: QueryDataPreviewStepProps) {
  const [tab, setTab] = useState<PreviewTab>('data');
  const [columnLimit, setColumnLimit] = useState<PreviewColumnLimit>(25);
  const [rowLimit, setRowLimit] = useState<PreviewRowLimit>(25);
  const [editingMeasureId, setEditingMeasureId] = useState<string | null>(null);
  // Real rows pulled from the backend stash (query-flow has no client-side CSV).
  const [fetchedRows, setFetchedRows] = useState<DataRow[] | null>(null);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  const headers = useMemo(() => columns.map((column) => column.name), [columns]);
  const numericColumns = useMemo(() => new Set(columns.filter(isNumericColumn).map((column) => column.name)), [columns]);
  const sampleRows = useMemo(() => buildSampleRows(columns), [columns]);
  // Fetch up to ROW_FETCH_LIMIT real rows from the stashed dataset CSV once per
  // dataset/session, registering them in the shared store. On failure the preview
  // falls back to schema-only sample rows and surfaces a retry-able error.
  useEffect(() => {
    const { templateId, signature } = request.target;
    if (!templateId || !signature) return;
    if (reportSectionDatasetStore.getRows(request.datasetId).length) {
      setFetchedRows(reportSectionDatasetStore.getRows(request.datasetId));
      return;
    }
    let cancelled = false;
    setRowsLoading(true);
    setRowsError(null);
    bindingPhaseApi
      .previewRows(templateId, signature, ROW_FETCH_LIMIT)
      .then((preview) => {
        if (cancelled) return;
        if (!preview.rows?.length) {
          setRowsError('The backend returned no rows for this dataset slice.');
          return;
        }
        const rows = preview.rows as DataRow[];
        reportSectionDatasetStore.registerRows(request.datasetId, rows);
        setFetchedRows(rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
        setRowsError(
          status === 404
            ? 'Preview-rows API not found — restart the FastAPI backend to load the new route.'
            : status
              ? `Could not load dataset rows (HTTP ${status}). Showing sample preview only.`
              : 'Could not reach the backend for dataset rows. Showing sample preview only.',
        );
      })
      .finally(() => { if (!cancelled) setRowsLoading(false); });
    return () => { cancelled = true; };
  }, [request.datasetId, request.target, retryTick]);

  const cachedRows = useMemo(() => {
    if (fetchedRows && fetchedRows.length) return fetchedRows;
    return reportSectionDatasetStore.getRows(request.datasetId);
  }, [fetchedRows, request.datasetId]);
  const sourceRows = cachedRows.length ? cachedRows : sampleRows;
  const previewMode: AcceptedPreviewMetadata['previewMode'] = cachedRows.length ? 'frontend_rows' : 'schema_only';
  const predicateResult = useMemo(
    () => applyPredicates(sourceRows, request.scope.filters || [], request.scope.filterCombinator || 'AND'),
    [sourceRows, request.scope.filters, request.scope.filterCombinator],
  );
  const filteredRows = useMemo(() => predicateResult.indexes.map((index) => sourceRows[index]), [predicateResult.indexes, sourceRows]);
  const autoMultiplier = useMemo(() => detectMultiplierColumn(headers, numericColumns), [headers, numericColumns]);
  const weightCol = config.weightCol || autoMultiplier;
  useEffect(() => {
    let changed = false;
    const normalizedMeasures = config.measures.map((measure) => {
      if (AGGREGATION_OPTIONS.some((option) => option.value === measure.agg)) return measure;
      changed = true;
      const nextAgg: PreviewAggregation = (config.weightCol || measure.weighted) ? 'weighted_mean' : 'mean';
      return { ...measure, agg: nextAgg as AggregationKind, weighted: nextAgg === 'weighted_mean' };
    });
    if (changed) onConfigChange({ ...config, measures: normalizedMeasures });
  }, [config, onConfigChange]);
  // Columns relevant to this query (filters, dimensions, time, multiplier,
  // measures and any explicit scope includes) — the "filtered" column set. The
  // data and weight tables show only these, never the whole dataset.
  const scopedCols = useMemo(() => {
    const pinned = uniqueList([
      ...config.filters.map((filter) => filter.col),
      ...config.dimensions,
      config.timeCol,
      weightCol,
      ...config.measures.map((measure) => measure.col),
      ...request.scope.columns.include,
    ]);
    const scoped = pinned.filter((column) => headers.includes(column));
    return scoped.length ? scoped : headers;
  }, [config.dimensions, config.filters, config.measures, config.timeCol, headers, request.scope.columns.include, weightCol]);
  const selectedCols = useMemo(
    () => (columnLimit === 'all' ? scopedCols : scopedCols.slice(0, columnLimit)),
    [columnLimit, scopedCols],
  );
  // Column profiles for the scoped columns, preserving scope order — fed to the
  // embedded weight table so it only sees the filtered columns.
  const scopedColumnProfiles = useMemo(
    () => scopedCols
      .map((name) => columns.find((column) => column.name === name))
      .filter((column): column is DatasetColumnProfile => Boolean(column)),
    [scopedCols, columns],
  );
  const visibleRows = filteredRows.slice(0, Math.min(rowLimit, ROW_PREVIEW_CAP));
  const missingWeightForWeightedMeasure = config.measures.some((measure) => (measure.weighted || measure.agg === 'weighted_mean') && !weightCol);
  const nonPositiveWeightCount = useMemo(() => {
    if (!weightCol || previewMode !== 'frontend_rows') return 0;
    return filteredRows.reduce((count, row) => {
      const weight = toNumber(row[weightCol]);
      return weight == null || weight <= 0 ? count + 1 : count;
    }, 0);
  }, [filteredRows, previewMode, weightCol]);
  const warningMessages = useMemo(() => {
    const messages = warningText([...execution.warnings, ...predicateResult.warnings]);
    if (previewMode === 'schema_only') messages.push('Full rows are not cached in the browser. Showing schema/sample preview while backend execution counts remain authoritative.');
    if (missingWeightForWeightedMeasure) messages.push('A weighted measure needs a multiplier column before acceptance.');
    if (nonPositiveWeightCount > 0) messages.push(`${nonPositiveWeightCount.toLocaleString('en-IN')} filtered row(s) have missing, zero, or negative multiplier values.`);
    return messages;
  }, [execution.warnings, missingWeightForWeightedMeasure, nonPositiveWeightCount, predicateResult.warnings, previewMode]);
  const accepted = acceptedPreview?.acceptanceKey === acceptanceKey;

  // Live weight-insights JSON for this slice — shown for review and attached on
  // accept so description / components / preview and the synthesizer all share it.
  const liveWeightInsights = useMemo(
    () => buildWeightInsights(
      filteredRows,
      config.measures,
      weightCol,
      WEIGHT_SCALE,
      request.scope.filters.map((filter) => ({ col: filter.col, op: filter.op, value: filter.value, connector: filter.connector })),
      { rowsScanned: execution.rowsScanned, rowsAfterFilter: execution.rowsAfterFilter },
    ),
    [filteredRows, config.measures, weightCol, request.scope.filters, execution.rowsScanned, execution.rowsAfterFilter],
  );

  const updateMeasure = (measureId: string, patch: Partial<SectionMeasure>) => {
    onConfigChange({
      ...config,
      measures: config.measures.map((measure) => measure.id === measureId ? { ...measure, ...patch } : measure),
    });
  };

  const toggleWeight = (measure: SectionMeasure) => {
    const nextWeighted = !(measure.weighted || measure.agg === 'weighted_mean');
    onConfigChange({
      ...config,
      weightCol: config.weightCol || autoMultiplier,
      measures: config.measures.map((item) => item.id === measure.id
        ? { ...item, weighted: nextWeighted, agg: nextWeighted ? 'weighted_mean' : 'mean' }
        : item),
    });
  };

  const setAggregation = (measure: SectionMeasure, aggregation: PreviewAggregation) => {
    updateMeasure(measure.id, {
      agg: aggregation as AggregationKind,
      weighted: aggregation === 'weighted_mean',
    });
  };

  const acceptPreview = () => {
    const weightInsights = buildWeightInsights(
      filteredRows,
      config.measures,
      weightCol,
      WEIGHT_SCALE,
      request.scope.filters.map((filter) => ({
        col: filter.col,
        op: filter.op,
        value: filter.value,
        connector: filter.connector,
      })),
      { rowsScanned: execution.rowsScanned, rowsAfterFilter: execution.rowsAfterFilter },
    );
    const metadata: AcceptedPreviewMetadata = {
      acceptedAt: new Date().toISOString(),
      acceptanceKey,
      previewMode,
      rowCounts: {
        rowsScanned: execution.rowsScanned,
        rowsAfterFilter: execution.rowsAfterFilter,
        rowsVisible: filteredRows.length,
        rowsRendered: visibleRows.length,
        cachedRowsAvailable: previewMode === 'frontend_rows',
      },
      filters: request.scope.filters.map((filter) => ({
        col: filter.col,
        op: filter.op,
        value: filter.value,
        connector: filter.connector,
      })),
      weightPolicy: {
        scale: WEIGHT_SCALE,
        multiplierColumn: weightCol,
        formula: 'nss_multiplier_100',
      },
      measures: config.measures.map((measure) => ({
        col: measure.col,
        label: measure.label || measure.col,
        agg: effectiveAggregation(measure),
        weighted: measure.weighted || measure.agg === 'weighted_mean',
        weightCol: measure.weighted || measure.agg === 'weighted_mean' ? weightCol : null,
      })),
      weightInsights,
      warnings: warningMessages,
    };
    onAccept(metadata);
  };

  return (
    <Card className="space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-text">Data and weight preview</h2>
          <p className="mt-1 text-xs text-text-muted">
            Verify the filtered slice and the multiplier logic before the description is written.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={accepted ? 'success' : 'warning'} className="text-[10px] uppercase">
            {accepted ? 'accepted' : 'accept required'}
          </Badge>
          <Badge variant={previewMode === 'frontend_rows' ? 'success' : 'muted'} className="text-[10px] uppercase">
            {previewMode.replace('_', ' ')}
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-4">
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">Backend matched</p>
          <p className="mt-1 text-lg font-semibold text-text">{execution.rowsAfterFilter.toLocaleString('en-IN')}</p>
          <p className="text-[10px] text-text-muted">of {execution.rowsScanned.toLocaleString('en-IN')} scanned</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">Visible preview</p>
          <p className="mt-1 text-lg font-semibold text-text">{rowsLoading ? '…' : visibleRows.length.toLocaleString('en-IN')}</p>
          <p className="text-[10px] text-text-muted">
            {rowsLoading
              ? 'loading rows…'
              : `showing ${Math.min(rowLimit, filteredRows.length)} of ${filteredRows.length.toLocaleString('en-IN')} available row(s)`}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">Measures</p>
          <p className="mt-1 text-lg font-semibold text-text">{config.measures.length}</p>
          <p className="text-[10px] text-text-muted">per-measure aggregation</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">Multiplier</p>
          <p className="mt-1 truncate text-sm font-semibold text-text">{weightCol || 'Not selected'}</p>
          <p className="text-[10px] text-text-muted">scale {WEIGHT_SCALE}</p>
        </div>
      </div>

      {rowsError && (
        <Alert variant="warning" title="Dataset rows unavailable">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{rowsError}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => setRetryTick((t) => t + 1)} disabled={rowsLoading}>
              {rowsLoading ? 'Retrying…' : 'Retry'}
            </Button>
          </div>
        </Alert>
      )}

      {warningMessages.length > 0 && (
        <Alert variant={missingWeightForWeightedMeasure ? 'error' : 'warning'} title="Preview checks">
          <div className="space-y-1">
            {warningMessages.slice(0, 4).map((message) => <p key={message}>{message}</p>)}
          </div>
        </Alert>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border">
        <div className="flex gap-1">
          {([
            ['data', Table2, 'Data table'],
            ['weight', Scale, 'Weight table'],
          ] as const).map(([value, Icon, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setTab(value)}
              className={cn(
                'inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold transition-colors',
                tab === value ? 'border-primary text-primary' : 'border-transparent text-text-muted hover:text-text',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs text-text-muted" hidden={tab !== 'data'}>
          Rows
          <select
            value={rowLimit}
            onChange={(event) => setRowLimit(Number(event.target.value) as PreviewRowLimit)}
            className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-text outline-none"
          >
            {ROW_LIMITS.map((limit) => <option key={limit} value={limit}>{limit}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-text-muted" hidden={tab !== 'data'}>
          Columns
          <select
            value={columnLimit}
            onChange={(event) => setColumnLimit(event.target.value === 'all' ? 'all' : Number(event.target.value) as PreviewColumnLimit)}
            className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-text outline-none"
          >
            {COLUMN_LIMITS.map((limit) => <option key={limit} value={limit}>{limit === 'all' ? 'All' : limit}</option>)}
          </select>
        </label>
      </div>

      {tab === 'data' && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {request.scope.filters.length ? request.scope.filters.map((filter) => (
              <Badge key={`${filter.col}:${filter.op}:${String(filter.value)}`} variant="muted" className="text-[10px]">
                <Filter className="mr-1 h-3 w-3" /> {predicateToText(filter)}
              </Badge>
            )) : <Badge variant="muted" className="text-[10px]">All rows in scope</Badge>}
          </div>
          <div className="max-h-[420px] overflow-auto rounded-xl border border-border bg-surface-card">
            <table className="w-full min-w-[760px] text-xs">
              <thead className="sticky top-0 z-10 bg-surface-card">
                <tr className="border-b border-border text-left text-[10px] uppercase text-text-muted">
                  <th className="w-12 px-3 py-2">#</th>
                  {selectedCols.map((columnName) => {
                    const role = roleForColumn(columns, columnName);
                    return (
                      <th key={columnName} className="px-3 py-2">
                        <span className="flex items-center gap-1.5 whitespace-nowrap">
                          {columnName}
                          {role !== 'unknown' && <Badge variant={roleVariant(role)} className="px-1.5 py-0 text-[9px]">{role}</Badge>}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {visibleRows.length ? visibleRows.map((row, index) => (
                  <tr key={index} className="hover:bg-primary/5">
                    <td className="px-3 py-2 text-text-muted">{index + 1}</td>
                    {selectedCols.map((columnName) => <td key={columnName} className="max-w-[220px] truncate px-3 py-2 text-text">{cellText(row[columnName])}</td>)}
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={selectedCols.length + 1} className="px-3 py-8 text-center text-sm text-text-muted">
                      No cached/sample rows match the current filters. Backend execution matched {execution.rowsAfterFilter.toLocaleString('en-IN')} row(s).
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'weight' && (
        <div className="space-y-4">
          {/* Column-level survey weighting — identical to the data-profiling weight
              table. Runs on the accepted filtered slice and only the query-scoped
              columns; the multiplier chosen here also drives the per-measure
              aggregation below. */}
          <DatasetWeightTabs
            embedded
            rows={filteredRows}
            headers={scopedCols}
            columns={scopedColumnProfiles}
            datasetName={request.datasetId}
            rowCount={filteredRows.length}
            onMultiplierColumnChange={(col) => onConfigChange({ ...config, weightCol: col })}
          />

          {/* Final aggregation per measure — drives the generated report blocks. */}
          <div className="rounded-xl border border-border bg-surface p-4">
            <div>
              <p className="text-sm font-semibold text-text">Final aggregation per measure</p>
              <p className="mt-1 text-xs text-text-muted">Set the aggregation each measure uses in the generated report. Weighted mean applies the multiplier selected above at scale {WEIGHT_SCALE}.</p>
            </div>
            <div className="mt-4 grid gap-2">
              {config.measures.map((measure) => {
                const aggregation = effectiveAggregation(measure);
                const weighted = measure.weighted || measure.agg === 'weighted_mean';
                return (
                  <div key={measure.id} className="rounded-lg border border-border bg-surface-card p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => toggleWeight(measure)}
                        aria-pressed={weighted}
                        className={cn(
                          'inline-flex h-8 w-8 items-center justify-center rounded-full border text-xs font-bold transition-colors',
                          weighted ? 'border-primary bg-primary text-white' : 'border-border bg-surface text-text-muted hover:text-primary',
                        )}
                        title={weighted ? 'Weighted measure' : 'Apply multiplier'}
                      >
                        W
                      </button>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-text">{measure.label || measure.col}</p>
                        <p className="truncate text-[11px] text-text-muted">{measure.col}</p>
                      </div>
                      <Badge variant={weighted ? 'success' : 'muted'} className="text-[10px]">{aggregation.replace('_', ' ')}</Badge>
                      <button
                        type="button"
                        onClick={() => setEditingMeasureId((current) => current === measure.id ? null : measure.id)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-text-muted hover:text-primary"
                        title="Edit aggregation"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    {editingMeasureId === measure.id && (
                      <div className="mt-3 flex flex-wrap items-center gap-2 pl-10">
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Aggregation</span>
                        <select
                          value={aggregation}
                          onChange={(event) => setAggregation(measure, event.target.value as PreviewAggregation)}
                          className="rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none"
                        >
                          {AGGREGATION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Weight insights — the weight.insights.v1 JSON that travels into the
          description / components / preview steps and grounds the synthesizer.
          Weighted and unweighted measures are shown together; weighted carries
          the extra Σw / weighted-total / weighted-mean figures. */}
      <details className="rounded-xl border border-border bg-surface">
        <summary className="flex cursor-pointer items-center justify-between gap-2 px-4 py-3 text-sm font-semibold text-text">
          <span className="flex items-center gap-2">
            <Calculator className="h-4 w-4 text-primary" /> Weight insights (passed to description, components &amp; report)
          </span>
          <Badge variant={liveWeightInsights.weightingApplied ? 'success' : 'muted'} className="text-[10px] uppercase">
            {liveWeightInsights.weightingApplied ? 'weighted' : 'unweighted'}
          </Badge>
        </summary>
        <div className="space-y-3 border-t border-border px-4 py-3">
          <div className="overflow-auto rounded-lg border border-border bg-surface-card">
            <table className="w-full min-w-[680px] text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[10px] uppercase text-text-muted">
                  <th className="px-3 py-2">Measure</th>
                  <th className="px-3 py-2">Aggregation</th>
                  <th className="px-3 py-2 text-right">Unweighted mean</th>
                  <th className="px-3 py-2 text-right">Weighted mean</th>
                  <th className="px-3 py-2 text-right">Δ (w − unw)</th>
                  <th className="px-3 py-2 text-right">Reported</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {liveWeightInsights.measures.map((m) => (
                  <tr key={m.col}>
                    <td className="px-3 py-2 font-medium text-text">{m.label}</td>
                    <td className="px-3 py-2 text-text-muted">{m.aggregation.replace('_', ' ')}{m.weighted ? ' · weighted' : ''}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-text-muted">{fmtNum(m.unweightedMean, 3)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-primary">{m.weightedMean != null ? fmtNum(m.weightedMean, 3) : '—'}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-text-muted">{m.delta != null ? fmtNum(m.delta, 3) : '—'}</td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums text-text">{fmtNum(m.selectedValue, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {liveWeightInsights.notes.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-text-muted">
              {liveWeightInsights.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          )}
          <details className="rounded-lg border border-border bg-surface-card">
            <summary className="cursor-pointer px-3 py-2 text-[11px] font-medium text-text-muted">Raw weight.insights.v1 JSON</summary>
            <pre className="max-h-72 overflow-auto px-3 py-2 text-[10px] leading-relaxed text-text">{JSON.stringify(liveWeightInsights, null, 2)}</pre>
          </details>
        </div>
      </details>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4">
        <Button type="button" variant="outline" onClick={onBack}>Back to scope</Button>
        <div className="flex flex-wrap items-center gap-2">
          {accepted && <span className="inline-flex items-center gap-1 text-xs font-medium text-success"><Check className="h-3.5 w-3.5" /> Slice accepted</span>}
          <Button type="button" onClick={acceptPreview} disabled={missingWeightForWeightedMeasure}>
            <Database className="h-4 w-4" /> Accept slice and continue
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default QueryDataPreviewStep;