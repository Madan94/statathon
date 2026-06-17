'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Calculator, Check, ChevronDown, Database, Edit3, Filter, Scale, Table2 } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { cn } from '@/lib/cn';
import type { DatasetColumnProfile } from '@/lib/api';
import type { AggregationKind, ReportSectionConfig, SectionMeasure } from '@/lib/reportSection';
import {
  applyPredicates,
  predicateToText,
  reportSectionDatasetStore,
  type DataRow,
  type ReportSectionRequest,
  type SectionExecutionResult,
} from '@/lib/report-section';
import type { AcceptedPreviewMetadata } from '@/lib/report-section/canvasHandoff';

type PreviewAggregation = 'sum' | 'mean' | 'weighted_mean' | 'count' | 'median' | 'min' | 'max';
type PreviewTab = 'data' | 'weight';
type PreviewColumnLimit = 10 | 25 | 50 | 100 | 'all';

const WEIGHT_SCALE = 100;
const ROW_PREVIEW_LIMIT = 100;
const SAMPLE_ROW_LIMIT = 12;
const COLUMN_LIMITS: PreviewColumnLimit[] = [10, 25, 50, 100, 'all'];

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

interface MeasureStats {
  measure: SectionMeasure;
  aggregation: PreviewAggregation;
  rowsUsed: number;
  rowsSkipped: number;
  rawValues: number[];
  unweightedSum: number;
  unweightedMean: number | null;
  weightSum: number;
  weightedTotal: number;
  weightedMean: number | null;
  selectedValue: number | null;
  valid: boolean;
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

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
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

function computeMeasureStats(rows: DataRow[], measure: SectionMeasure, weightCol: string | null): MeasureStats {
  const aggregation = effectiveAggregation(measure);
  const stats: MeasureStats = {
    measure,
    aggregation,
    rowsUsed: 0,
    rowsSkipped: 0,
    rawValues: [],
    unweightedSum: 0,
    unweightedMean: null,
    weightSum: 0,
    weightedTotal: 0,
    weightedMean: null,
    selectedValue: null,
    valid: false,
  };

  for (const row of rows) {
    const value = aggregation === 'count' ? 1 : toNumber(row[measure.col]);
    const weight = weightCol ? toNumber(row[weightCol]) : null;
    if (aggregation !== 'count' && value == null) {
      stats.rowsSkipped += 1;
      continue;
    }
    stats.rowsUsed += 1;
    if (aggregation !== 'count' && value != null) {
      stats.rawValues.push(value);
      stats.unweightedSum += value;
    }
    if (value != null && weight != null && weight > 0) {
      const scaledWeight = weight / WEIGHT_SCALE;
      stats.weightSum += scaledWeight;
      stats.weightedTotal += value * scaledWeight;
    } else if (aggregation === 'weighted_mean' || measure.weighted) {
      stats.rowsSkipped += 1;
    }
  }

  stats.unweightedMean = stats.rawValues.length ? stats.unweightedSum / stats.rawValues.length : null;
  stats.weightedMean = stats.weightSum > 0 ? stats.weightedTotal / stats.weightSum : null;
  switch (aggregation) {
    case 'count':
      stats.selectedValue = stats.rowsUsed;
      break;
    case 'sum':
      stats.selectedValue = stats.rawValues.length ? stats.unweightedSum : null;
      break;
    case 'mean':
      stats.selectedValue = stats.unweightedMean;
      break;
    case 'weighted_mean':
      stats.selectedValue = stats.weightedMean;
      break;
    case 'median':
      stats.selectedValue = median(stats.rawValues);
      break;
    case 'min':
      stats.selectedValue = stats.rawValues.length ? Math.min(...stats.rawValues) : null;
      break;
    case 'max':
      stats.selectedValue = stats.rawValues.length ? Math.max(...stats.rawValues) : null;
      break;
    default:
      stats.selectedValue = null;
  }
  stats.valid = stats.selectedValue != null && Number.isFinite(stats.selectedValue);
  return stats;
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
  const [editingMeasureId, setEditingMeasureId] = useState<string | null>(null);

  const headers = useMemo(() => columns.map((column) => column.name), [columns]);
  const numericColumns = useMemo(() => new Set(columns.filter(isNumericColumn).map((column) => column.name)), [columns]);
  const sampleRows = useMemo(() => buildSampleRows(columns), [columns]);
  const cachedRows = useMemo(() => reportSectionDatasetStore.getRows(request.datasetId), [request.datasetId]);
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
  const selectedCols = useMemo(() => {
    const pinned = uniqueList([
      ...config.filters.map((filter) => filter.col),
      ...config.dimensions,
      config.timeCol,
      weightCol,
      ...config.measures.map((measure) => measure.col),
      ...request.scope.columns.include,
    ]);
    const ordered = uniqueList([...pinned.filter((column) => headers.includes(column)), ...headers]);
    return columnLimit === 'all' ? ordered : ordered.slice(0, columnLimit);
  }, [columnLimit, config.dimensions, config.filters, config.measures, config.timeCol, headers, request.scope.columns.include, weightCol]);
  const visibleRows = filteredRows.slice(0, ROW_PREVIEW_LIMIT);
  const measureStats = useMemo(
    () => config.measures.map((measure) => computeMeasureStats(filteredRows, measure, weightCol)),
    [config.measures, filteredRows, weightCol],
  );
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
          <p className="mt-1 text-lg font-semibold text-text">{visibleRows.length.toLocaleString('en-IN')}</p>
          <p className="text-[10px] text-text-muted">from {filteredRows.length.toLocaleString('en-IN')} available row(s)</p>
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
        <label className="flex items-center gap-2 text-xs text-text-muted">
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
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)]">
            <div className="rounded-xl border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-text">Multiplier and measure aggregation</p>
                  <p className="mt-1 text-xs text-text-muted">Apply survey weighting at column level and set the final aggregation per measure.</p>
                </div>
                <label className="flex min-w-[14rem] items-center gap-2 text-xs text-text-muted">
                  <Scale className="h-3.5 w-3.5" />
                  <select
                    value={weightCol || ''}
                    onChange={(event) => onConfigChange({ ...config, weightCol: event.target.value || null })}
                    className="w-full rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none"
                  >
                    <option value="">No multiplier</option>
                    {headers.filter((header) => numericColumns.has(header)).map((header) => <option key={header} value={header}>{header}</option>)}
                  </select>
                </label>
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

            <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
              <div className="flex items-center gap-2">
                <Calculator className="h-4 w-4 text-primary" />
                <p className="text-sm font-semibold text-text">Formula</p>
              </div>
              <div className="mt-3 rounded-lg border border-border bg-surface-card p-3 font-mono text-xs text-text">
                <p>weighted_value = x_i * w_i / {WEIGHT_SCALE}</p>
                <p className="mt-1">weighted_total = sum(x_i * w_i / {WEIGHT_SCALE})</p>
                <p className="mt-1">weighted_mean = weighted_total / sum(w_i / {WEIGHT_SCALE})</p>
              </div>
              <details className="mt-3 rounded-lg border border-border bg-surface-card p-3 text-xs text-text-muted">
                <summary className="flex cursor-pointer items-center gap-2 font-semibold text-text">
                  <ChevronDown className="h-3.5 w-3.5" /> MOSPI walkthrough
                </summary>
                <div className="mt-3 space-y-2 leading-relaxed">
                  <p>1. Start with the accepted filtered slice, not the full dataset.</p>
                  <p>2. Read x_i from the selected measure column and w_i from the multiplier column.</p>
                  <p>3. Use scale 100 for NSS-style multipliers so every row contributes x_i * w_i / 100.</p>
                  <p>4. Compare weighted and unweighted values before moving to report language.</p>
                  <p>5. Treat skipped rows as a method warning when values or multipliers are missing or non-positive.</p>
                </div>
              </details>
            </div>
          </div>

          <div className="overflow-auto rounded-xl border border-border bg-surface-card">
            <table className="w-full min-w-[860px] text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[10px] uppercase text-text-muted">
                  <th className="px-3 py-2">Measure</th>
                  <th className="px-3 py-2">Aggregation</th>
                  <th className="px-3 py-2 text-right">Rows used</th>
                  <th className="px-3 py-2 text-right">Skipped</th>
                  <th className="px-3 py-2 text-right">sum(w_i/100)</th>
                  <th className="px-3 py-2 text-right">Weighted total</th>
                  <th className="px-3 py-2 text-right">Weighted mean</th>
                  <th className="px-3 py-2 text-right">Selected result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {measureStats.map((stats) => (
                  <tr key={stats.measure.id}>
                    <td className="px-3 py-2 font-medium text-text">{stats.measure.label || stats.measure.col}</td>
                    <td className="px-3 py-2 text-text-muted">{stats.aggregation.replace('_', ' ')}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{stats.rowsUsed.toLocaleString('en-IN')}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-text-muted">{stats.rowsSkipped.toLocaleString('en-IN')}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmtNum(stats.weightSum, 3)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-primary">{fmtNum(stats.weightedTotal, 3)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-text">{fmtNum(stats.weightedMean, 3)}</td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums text-text">{fmtNum(stats.selectedValue, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {measureStats.some((stats) => !stats.valid) && (
            <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
              <AlertTriangle className="h-3.5 w-3.5" /> Some selected results could not be computed from the cached/sample preview rows.
            </div>
          )}
        </div>
      )}

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