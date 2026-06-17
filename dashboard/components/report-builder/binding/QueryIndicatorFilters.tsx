'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import {
  BarChart3,
  Check,
  ChevronDown,
  Code2,
  Copy,
  Download,
  Filter,
  Layers,
  Loader2,
  Play,
  Plus,
  Ruler,
  Scale,
  Sigma,
  Sparkles,
  Table2,
  Tag,
  Trash2,
  X,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { parseCsv, detectNumericColumns, type ParsedCsv } from '@/lib/csv';
import { SectionBlockView } from '@/components/report-builder/binding/SectionBlockView';
import {
  buildReportSectionSpec,
  newId,
  validateSectionConfig,
  type AggregationKind,
  type AnalysisType,
  type ChartType,
  type FilterOp,
  type ReportSectionConfig,
  type ReportSectionRequest,
  type SectionComponentType,
  type SectionFilterRule,
  type SectionMeasure,
} from '@/lib/reportSection';
import {
  applyPredicates,
  buildDatasetSnapshot,
  buildSectionBlocks,
  executeWithSliceCache,
  reportSectionDatasetStore,
  validateSectionRequest,
  type DataRow,
  type DatasetSnapshot,
  type GeneratedSectionBlock,
  type SectionExecutionResult,
  type SectionIssue,
} from '@/lib/report-section';
import type { DatasetColumnProfile } from '@/lib/api';
import { generatePhaseApi } from '@/lib/api';

// ─────────────────────────────────────────────────────────────────────────────

const COMPUTE_CAP = 100_000;
const MAX_DISTINCT = 40;
const SLICE_PREVIEW_ROWS = 50;

const OPERATORS: Array<{ value: FilterOp; label: string; symbol: string; numeric?: boolean; noValue?: boolean }> = [
  { value: 'eq',       label: 'equals',        symbol: '='   },
  { value: 'ne',       label: 'not equals',    symbol: '≠'   },
  { value: 'gt',       label: 'greater than',  symbol: '>',   numeric: true },
  { value: 'ge',       label: 'at least',      symbol: '≥',   numeric: true },
  { value: 'lt',       label: 'less than',     symbol: '<',   numeric: true },
  { value: 'le',       label: 'at most',       symbol: '≤',   numeric: true },
  { value: 'in',       label: 'in list',       symbol: '∈'   },
  { value: 'not_in',   label: 'not in list',   symbol: '∉'   },
  { value: 'between',  label: 'between',       symbol: '↔',   numeric: true },
  { value: 'contains', label: 'contains',      symbol: '⊇'   },
  { value: 'is_null',  label: 'is empty',      symbol: '∅',   noValue: true },
  { value: 'not_null', label: 'is not empty',  symbol: '≠∅',  noValue: true },
];

const AGG_OPTIONS: Array<{ value: AggregationKind; label: string }> = [
  { value: 'reported_value', label: 'Reported value' },
  { value: 'sum',            label: 'Sum'            },
  { value: 'mean',           label: 'Mean'           },
  { value: 'weighted_mean',  label: 'Weighted mean'  },
  { value: 'count',          label: 'Count'          },
  { value: 'median',         label: 'Median'         },
  { value: 'min',            label: 'Min'            },
  { value: 'max',            label: 'Max'            },
];

const COMPONENT_OPTIONS: Array<{ value: SectionComponentType; label: string; icon: string }> = [
  { value: 'narrative',   label: 'Narrative',    icon: '' },
  { value: 'table',       label: 'Table',        icon: '' },
  { value: 'chart',       label: 'Chart',        icon: '' },
  { value: 'metric',      label: 'Metric',       icon: '' },
  { value: 'key_finding', label: 'Key Finding',  icon: '' },
];

const CHART_TYPES: Array<{ value: ChartType; label: string }> = [
  { value: 'bar',   label: 'Bar chart'    },
  { value: 'hbar',  label: 'Horizontal bar' },
  { value: 'line',  label: 'Line chart'   },
  { value: 'donut', label: 'Donut chart'  },
  { value: 'pie',   label: 'Pie chart'    },
];

const ANALYSIS_TYPES: Array<{ value: AnalysisType; label: string; desc: string }> = [
  { value: 'comparison',   label: 'Comparison',   desc: 'Compare values across groups'     },
  { value: 'trend',        label: 'Trend',        desc: 'Change over time'                 },
  { value: 'ranking',      label: 'Ranking',      desc: 'Top / bottom N items'             },
  { value: 'distribution', label: 'Distribution', desc: 'Spread of values'                 },
  { value: 'summary',      label: 'Summary',      desc: 'High-level aggregate overview'    },
  { value: 'metric',       label: 'Metric',       desc: 'Single headline figure'           },
];

const MULTIPLIER_PATTERNS = [/^multiplier$/i, /^mult$/i, /multiplier/i, /^mlt$/i, /^wt$/i, /^wgt$/i, /^weight$/i, /weight/i];

function detectMultiplierColumn(headers: string[], numeric: Set<string>): string | null {
  for (const pat of MULTIPLIER_PATTERNS) {
    const hit = headers.find((h) => numeric.has(h) && pat.test(h.trim()));
    if (hit) return hit;
  }
  return null;
}

function coerceCell(raw: string | undefined): unknown {
  const v = (raw ?? '').trim();
  if (v === '') return null;
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  if (/^(true|false)$/i.test(v)) return /^true$/i.test(v);
  return v;
}

// ── Section header helper ────────────────────────────────────────────────────
function SectionHeader({ icon, title, hint, badge }: { icon: ReactNode; title: string; hint?: string; badge?: string }) {
  return (
    <div className="flex items-center gap-3 border-b border-gray-100 pb-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#0a1f44]/8 text-[#0a1f44]">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold text-[#0a1f44]">{title}</h4>
          {badge && (
            <span className="rounded-full bg-[#f5c518]/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#b8940e]">
              {badge}
            </span>
          )}
        </div>
        {hint && <p className="text-[11px] text-gray-500">{hint}</p>}
      </div>
    </div>
  );
}

// ── Form field wrappers ──────────────────────────────────────────────────────
const fieldCls = 'w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm outline-none transition focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20';

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">{children}</span>;
}

function dtypeToSnapshotType(dtype: string): DatasetSnapshot['columnTypes'][string] {
  if (/int|float|double|decimal|number|numeric/i.test(dtype)) return 'number';
  if (/bool/i.test(dtype)) return 'boolean';
  if (/date|time|year|period/i.test(dtype)) return 'date';
  if (dtype) return 'string';
  return 'unknown';
}

function buildSchemaSnapshot(datasetId: string, columns: DatasetColumnProfile[]): DatasetSnapshot | null {
  if (!columns.length) return null;
  const columnTypes: DatasetSnapshot['columnTypes'] = {};
  const distinctValues: DatasetSnapshot['distinctValues'] = {};
  columns.forEach((column) => {
    columnTypes[column.name] = dtypeToSnapshotType(column.dtype);
    distinctValues[column.name] = column.sampleValues || [];
  });
  return {
    datasetId,
    rows: [],
    columns: columns.map((column) => column.name),
    columnTypes,
    distinctValues,
    signature: `schema:${datasetId}:${columns.length}`,
    rowCount: 0,
  };
}

// ────────────────────────────────────────────────────────────────────────────

interface QueryIndicatorFiltersProps {
  file: File | null;
  columns: DatasetColumnProfile[];
  config: ReportSectionConfig;
  onChange: (config: ReportSectionConfig) => void;
  templateId: string;
  signature: string;
  datasetId: string;
  onGenerate?: (blocks: GeneratedSectionBlock[], request: ReportSectionRequest, execution: SectionExecutionResult) => void;
  hidePreview?: boolean;
  hideTarget?: boolean;
  hideOutputComponents?: boolean;
  hideGenerateControls?: boolean;
  requireMeasure?: boolean;
  generateLabel?: string;
  className?: string;
}

export function QueryIndicatorFilters({
  file,
  columns,
  config,
  onChange,
  templateId,
  signature,
  datasetId,
  onGenerate,
  hidePreview = false,
  hideTarget = false,
  hideOutputComponents = false,
  hideGenerateControls = false,
  requireMeasure = true,
  generateLabel = 'Generate Report Section',
  className,
}: QueryIndicatorFiltersProps) {
  const [parsed, setParsed] = useState<ParsedCsv | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [blocks, setBlocks] = useState<GeneratedSectionBlock[]>([]);
  const [genIssues, setGenIssues] = useState<SectionIssue[]>([]);
  const [execution, setExecution] = useState<SectionExecutionResult | null>(null);
  const [ackWarnings, setAckWarnings] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [engineUsed, setEngineUsed] = useState<'server' | 'local' | null>(null);
  const [dimSearch, setDimSearch] = useState('');

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    file.text().then((text) => {
      if (cancelled) return;
      const result = parseCsv(text, COMPUTE_CAP);
      if (!result.headers.length) {
        setError('Could not read any columns from this file.');
        setParsed(null);
      } else {
        setError(null);
        setParsed(result);
      }
    }).catch((err: unknown) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : 'Failed to read the CSV file.');
      setParsed(null);
    });
    return () => { cancelled = true; };
  }, [file]);

  const headerNames = useMemo(() => (parsed ? parsed.headers : columns.map((c) => c.name)), [parsed, columns]);
  const numericSet = useMemo(() => {
    if (parsed) return detectNumericColumns(parsed);
    return new Set(
      columns
        .filter((c) => c.role === 'measure' || c.role === 'time' || /^int|float|double|decimal|number|numeric/i.test(c.dtype || '') || c.minValue !== undefined || c.maxValue !== undefined)
        .map((c) => c.name),
    );
  }, [parsed, columns]);
  const numericHeaders = headerNames.filter((h) => numericSet.has(h));
  const roleByName = useMemo(() => {
    const map = new Map<string, DatasetColumnProfile['role']>();
    columns.forEach((c) => map.set(c.name, c.role));
    return map;
  }, [columns]);

  const dataRows = useMemo<DataRow[]>(() => {
    if (!parsed) return [];
    return parsed.rows.map((r) => {
      const obj: DataRow = {};
      parsed.headers.forEach((h, i) => { obj[h] = coerceCell(r[i]); });
      return obj;
    });
  }, [parsed]);

  const distinctByColumn = useMemo(() => {
    const map = new Map<string, string[]>();
    if (!parsed) {
      columns.forEach((column) => {
        map.set(column.name, (column.sampleValues || []).map(String).filter(Boolean).slice(0, MAX_DISTINCT));
      });
      return map;
    }
    parsed.headers.forEach((h, idx) => {
      const seen = new Set<string>();
      for (const row of parsed.rows) {
        const v = (row[idx] ?? '').trim();
        if (v) seen.add(v);
        if (seen.size > MAX_DISTINCT) break;
      }
      map.set(h, Array.from(seen));
    });
    return map;
  }, [parsed]);

  useEffect(() => {
    if (!parsed || config.dimensions.length || config.measures.length) return;
    const numeric = detectNumericColumns(parsed);
    const weightCol = detectMultiplierColumn(parsed.headers, numeric);
    const measureCol = parsed.headers.find((h) => numeric.has(h) && h !== weightCol);
    const dimensionCol = parsed.headers.find((h) => !numeric.has(h)) ?? parsed.headers.find((h) => h !== measureCol);
    onChange({
      ...config,
      weightCol: weightCol ?? config.weightCol,
      dimensions: dimensionCol ? [dimensionCol] : [],
      measures: measureCol
        ? [{ id: newId('msr'), col: measureCol, label: measureCol, agg: 'reported_value', unit: '', weighted: false }]
        : [],
      sortBy: measureCol ?? null,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed]);

  useEffect(() => {
    if (parsed || config.dimensions.length || config.measures.length || !columns.length) return;
    const numeric = new Set(columns.filter((c) => numericSet.has(c.name)).map((c) => c.name));
    const weightCol = detectMultiplierColumn(columns.map((c) => c.name), numeric);
    const measureCol = columns.find((c) => c.role === 'measure' && c.name !== weightCol)?.name
      ?? columns.find((c) => numeric.has(c.name) && c.name !== weightCol)?.name
      ?? columns[0]?.name;
    const dimensionCol = columns.find((c) => c.role === 'dimension')?.name
      ?? columns.find((c) => c.role !== 'measure' && c.name !== measureCol)?.name
      ?? columns[0]?.name;
    const timeCol = columns.find((c) => c.role === 'time')?.name ?? config.timeCol;
    onChange({
      ...config,
      weightCol: weightCol ?? config.weightCol,
      timeCol: timeCol ?? null,
      dimensions: dimensionCol ? [dimensionCol] : [],
      measures: measureCol
        ? [{ id: newId('msr'), col: measureCol, label: measureCol, agg: 'reported_value', unit: columns.find((c) => c.name === measureCol)?.unit || '', weighted: false }]
        : [],
      sortBy: measureCol ?? null,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed, columns, numericSet]);

  const spec = useMemo(() => buildReportSectionSpec(config, { templateId, signature, datasetId }), [config, templateId, signature, datasetId]);
  const specJson = useMemo(() => JSON.stringify(spec, null, 2), [spec]);
  const configIssues = useMemo(() => validateSectionConfig(config, {
    requireMeasure,
    requireDimension: requireMeasure,
    requireComponents: !hideOutputComponents,
    requireChartAxis: !hideOutputComponents,
  }), [config, requireMeasure, hideOutputComponents]);
  const previewSnapshot = useMemo(
    () => (dataRows.length ? buildDatasetSnapshot(spec.datasetId, dataRows) : null),
    [dataRows, spec.datasetId],
  );
  const schemaSnapshot = useMemo(() => buildSchemaSnapshot(spec.datasetId, columns), [spec.datasetId, columns]);
  const validation = useMemo(() => validateSectionRequest(spec, previewSnapshot ?? schemaSnapshot), [spec, previewSnapshot, schemaSnapshot]);

  const match = useMemo(() => {
    if (!dataRows.length) return null;
    const { indexes } = applyPredicates(dataRows, spec.scope.filters);
    return { matched: indexes.length, total: dataRows.length };
  }, [dataRows, spec.scope.filters]);

  const slicePreview = useMemo(() => {
    if (!dataRows.length) return null;
    const { indexes } = applyPredicates(dataRows, spec.scope.filters);
    const include = spec.scope.columns.include.filter((c) => headerNames.includes(c));
    const cols = include.length ? include : headerNames;
    const rows = indexes.slice(0, SLICE_PREVIEW_ROWS).map((i) => dataRows[i]);
    return { cols, rows, total: indexes.length };
  }, [dataRows, spec.scope.filters, spec.scope.columns.include, headerNames]);

  const update = (patch: Partial<ReportSectionConfig>) => {
    onChange({ ...config, ...patch });
    setBlocks([]);
    setExecution(null);
    setGenIssues([]);
    setAckWarnings(false);
  };

  // ── Filters ─────────────────────────────────────────────────────────────────
  const addFilter = () => {
    const firstCol = headerNames[0] ?? '';
    update({ filters: [...config.filters, { id: newId('flt'), col: firstCol, op: 'eq', value: '', required: true, connector: 'AND' }] });
  };
  const updateFilter = (id: string, patch: Partial<SectionFilterRule>) =>
    update({ filters: config.filters.map((f) => (f.id === id ? { ...f, ...patch } : f)) });
  const removeFilter = (id: string) => update({ filters: config.filters.filter((f) => f.id !== id) });

  // ── Dimensions ──────────────────────────────────────────────────────────────
  const toggleDimension = (col: string) => {
    const has = config.dimensions.includes(col);
    update({ dimensions: has ? config.dimensions.filter((c) => c !== col) : [...config.dimensions, col] });
  };

  // ── Measures ────────────────────────────────────────────────────────────────
  const addMeasure = () => {
    const used = new Set(config.measures.map((m) => m.col));
    const firstNumeric = headerNames.find((h) => numericSet.has(h) && h !== config.weightCol && !used.has(h))
      ?? headerNames.find((h) => !used.has(h))
      ?? headerNames[0] ?? '';
    update({ measures: [...config.measures, { id: newId('msr'), col: firstNumeric, label: firstNumeric, agg: 'reported_value', unit: '', weighted: false }] });
  };
  const updateMeasure = (id: string, patch: Partial<SectionMeasure>) =>
    update({ measures: config.measures.map((m) => (m.id === id ? { ...m, ...patch } : m)) });
  const removeMeasure = (id: string) => update({ measures: config.measures.filter((m) => m.id !== id) });
  const toggleMeasureWeight = (id: string) => {
    const m = config.measures.find((x) => x.id === id);
    if (!m) return;
    const weighted = !m.weighted;
    updateMeasure(id, { weighted, agg: weighted ? 'weighted_mean' : (m.agg === 'weighted_mean' ? 'reported_value' : m.agg) });
  };

  // ── Components ──────────────────────────────────────────────────────────────
  const toggleComponent = (c: SectionComponentType) => {
    const has = config.components.includes(c);
    update({ components: has ? config.components.filter((x) => x !== c) : [...config.components, c] });
  };

  const sortOptions = useMemo(
    () => [...config.dimensions, ...config.measures.map((m) => m.col)].filter((v, i, a) => v && a.indexOf(v) === i),
    [config.dimensions, config.measures],
  );

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(specJson);
      toast.success('report.section.v1 JSON copied');
    } catch {
      toast.error('Could not copy to clipboard');
    }
  };
  const downloadJson = () => {
    const blob = new Blob([specJson], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${spec.requestId}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  const generate = async () => {
    if (configIssues.length) { toast.error(configIssues[0]); return; }
    setGenerating(true);
    try {
      const res = await generatePhaseApi.generateSection(templateId, signature, { request: spec as unknown as Record<string, unknown> });
      const built = res.blocks;
      const execLike: SectionExecutionResult = {
        requestId: spec.requestId, datasetId: spec.datasetId,
        rows: Array.from({ length: res.groups }, () => ({ key: {}, value: null, n: 0, rowIds: [] })),
        measure: spec.scope.columns.measures[0] ?? null,
        groupBy: spec.analysis.groupBy ?? [],
        filtersApplied: [], rowsScanned: res.rowsScanned, rowsAfterFilter: res.rowsAfterFilter,
        cacheHit: false, sliceSignature: '', warnings: res.warnings ?? [],
      };
      setExecution(execLike); setBlocks(built); setGenIssues(res.warnings ?? []);
      setAckWarnings(false); setEngineUsed('server');
      onGenerate?.(built, spec, execLike);
      toast.success(`Generated ${built.length} block(s) · ${res.rowsAfterFilter.toLocaleString('en-IN')} rows`);
      setGenerating(false); return;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 422) {
        const detail = (err as { response?: { data?: { detail?: { issues?: SectionIssue[] } } } })?.response?.data?.detail;
        setBlocks([]); setExecution(null);
        setGenIssues(detail?.issues ?? [{ severity: 'error', code: 'CANNOT_COMPUTE', message: 'Server could not compute this section.' }]);
        setEngineUsed('server'); setGenerating(false);
        toast.error('Cannot compute — resolve the errors below.'); return;
      }
    }
    if (!dataRows.length) { setGenerating(false); toast.error('No dataset rows and server unavailable.'); return; }
    reportSectionDatasetStore.registerRows(spec.datasetId, dataRows);
    const snapshot = reportSectionDatasetStore.getSnapshot(spec.datasetId);
    const validation = validateSectionRequest(spec, snapshot);
    if (validation.status === 'cannot_compute') {
      setBlocks([]); setExecution(null); setGenIssues(validation.issues);
      setEngineUsed('local'); setGenerating(false);
      toast.error('Cannot compute — resolve the errors below.'); return;
    }
    const result = executeWithSliceCache(spec, reportSectionDatasetStore.getRows(spec.datasetId));
    const built = buildSectionBlocks(spec, result);
    setExecution(result); setBlocks(built); setGenIssues([...validation.issues, ...result.warnings]);
    setAckWarnings(false); setEngineUsed('local'); setGenerating(false);
    onGenerate?.(built, spec, result);
    toast.success(`Generated ${built.length} block(s) locally · ${result.rowsAfterFilter.toLocaleString('en-IN')} rows`);
  };

  const genWarnings = genIssues.filter((i) => i.severity !== 'info');
  const pct = match && match.total > 0 ? Math.round((match.matched / match.total) * 100) : 0;
  // per-row connector toggle (last row connector is ignored)
  const toggleConnector = (id: string) =>
    update({ filters: config.filters.map((f) => f.id === id ? { ...f, connector: (f.connector ?? 'AND') === 'AND' ? 'OR' : 'AND' } : f) });

  return (
    <div className={cn('space-y-5 font-sans', className)}>

      {/* ── Header banner ─────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[#0a1f44]/15 bg-[#0a1f44] px-6 py-4 text-white shadow">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Filter className="h-5 w-5 text-[#f5c518]" />
            <h3 className="text-base font-bold tracking-tight">Query Indicator Builder</h3>
            <span className="rounded-full bg-[#f5c518]/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#f5c518]">
              loop template
            </span>
          </div>
          <p className="mt-0.5 text-xs text-white/70">
            Define filters, dimensions and measures, then generate the{' '}
            <span className="font-mono text-[#f5c518]">report.section.v1</span> section for BI analysis.
          </p>
        </div>
        {match && (
          <div className="rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-right backdrop-blur-sm">
            <p className="text-lg font-bold tabular-nums text-[#f5c518]">
              {match.matched.toLocaleString('en-IN')}
              <span className="ml-1 text-sm font-normal text-white/70">/ {match.total.toLocaleString('en-IN')} rows</span>
            </p>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/20">
              <div className="h-full rounded-full bg-[#f5c518] transition-all" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-0.5 text-[10px] text-white/60">{pct}% match scope</p>
          </div>
        )}
      </div>

      {error && <Alert variant="error" title="Could not read the dataset">{error}</Alert>}

      {/* ── 1. Section Target ─────────────────────────────────────────────── */}
      {!hideTarget && (
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="px-6 pt-5 pb-4">
          <SectionHeader
            icon={<Layers className="h-4 w-4" />}
            title="1. Section Target"
            hint="Where this section lands in the final report"
          />
        </div>
        <div className="grid gap-4 px-6 pb-4 sm:grid-cols-2">
          <label className="block">
            <FieldLabel>Chapter title</FieldLabel>
            <input value={config.chapterTitle} onChange={(e) => update({ chapterTitle: e.target.value })} className={fieldCls} />
          </label>
          <label className="block">
            <FieldLabel>Section title</FieldLabel>
            <input value={config.sectionTitle} onChange={(e) => update({ sectionTitle: e.target.value })} className={fieldCls} />
          </label>
        </div>
        <div className="px-6 pb-4">
          <label className="block">
            <FieldLabel>Description <span className="normal-case font-normal text-gray-400">(used as the AI generation prompt)</span></FieldLabel>
            <textarea
              value={config.descriptionText}
              onChange={(e) => update({ descriptionText: e.target.value })}
              rows={2}
              placeholder="e.g. Analyse employment rates across states for rural households"
              className={cn(fieldCls, 'resize-none')}
            />
          </label>
        </div>
        <div className="flex items-center gap-3 border-t border-gray-100 px-6 py-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Append mode</span>
          <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5">
            {(['append', 'insert_after'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => update({ mode: m })}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-semibold transition-colors',
                  config.mode === m ? 'bg-[#0a1f44] text-white shadow-sm' : 'text-gray-500 hover:text-gray-800',
                )}
              >
                {m === 'append' ? 'Append' : 'Insert After'}
              </button>
            ))}
          </div>
        </div>
      </div>
      )}

      {/* ── 2. Scope Filters ──────────────────────────────────────────────── */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="px-6 pt-5 pb-4">
          <SectionHeader
            icon={<Filter className="h-4 w-4" />}
            title="2. Scope Filters"
            hint="Restrict which rows are included in the analysis"
          />
        </div>


        <div className="space-y-2 px-6 pb-4">
          {config.filters.length === 0 ? (
            <div className="rounded-lg border-2 border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center">
              <Filter className="mx-auto h-8 w-8 text-gray-300" />
              <p className="mt-2 text-sm font-medium text-gray-500">No filters applied</p>
              <p className="text-xs text-gray-400">The entire dataset is in scope. Add a filter to restrict rows.</p>
              <button type="button" onClick={addFilter} className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-[#0a1f44] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0f2d52]">
                <Plus className="h-3.5 w-3.5" /> Add Filter
              </button>
            </div>
          ) : (
            <>
              {config.filters.map((rule, idx) => {
                const op = OPERATORS.find((o) => o.value === rule.op);
                const distinct = distinctByColumn.get(rule.col) ?? (columns.find((c) => c.name === rule.col)?.sampleValues ?? []).map(String);
                const chips = distinct.slice(0, 8).filter(Boolean);
                return (
                  <div key={rule.id}>
                    {/* Per-row AND/OR connector — belongs to the PREVIOUS rule */}
                    {idx > 0 && (
                      <div className="flex items-center gap-2 py-1">
                        <div className="flex-1 border-t border-dashed border-gray-200" />
                        <button
                          type="button"
                          onClick={() => toggleConnector(config.filters[idx - 1].id)}
                          title="Click to toggle AND / OR for this condition"
                          className={cn(
                            'inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[11px] font-bold transition-all',
                            (config.filters[idx - 1].connector ?? 'AND') === 'AND'
                              ? 'border-[#0a1f44]/30 bg-[#0a1f44]/8 text-[#0a1f44] hover:bg-[#0a1f44]/15'
                              : 'border-orange-300 bg-orange-50 text-orange-700 hover:bg-orange-100',
                          )}
                        >
                          {config.filters[idx - 1].connector ?? 'AND'}
                        </button>
                        <div className="flex-1 border-t border-dashed border-gray-200" />
                      </div>
                    )}

                    {/* Filter row */}
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        {/* Row number */}
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#0a1f44]/10 text-[10px] font-bold text-[#0a1f44]">
                          {idx + 1}
                        </span>

                        {/* Column selector */}
                        <select
                          value={rule.col}
                          onChange={(e) => updateFilter(rule.id, { col: e.target.value })}
                          className="min-w-[9rem] flex-1 rounded-md border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 shadow-sm outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
                        >
                          {headerNames.map((h) => <option key={h} value={h}>{h}</option>)}
                        </select>

                        {/* Operator */}
                        <select
                          value={rule.op}
                          onChange={(e) => updateFilter(rule.id, { op: e.target.value as FilterOp })}
                          className="rounded-md border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 shadow-sm outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
                        >
                          {OPERATORS.map((o) => <option key={o.value} value={o.value}>{o.symbol} {o.label}</option>)}
                        </select>

                        {/* Value input */}
                        {!op?.noValue && (
                          <input
                            value={rule.value}
                            onChange={(e) => updateFilter(rule.id, { value: e.target.value })}
                            placeholder={
                              rule.op === 'in' || rule.op === 'not_in' ? 'value1, value2, …'
                                : rule.op === 'between' ? 'low, high'
                                  : op?.numeric ? 'number' : 'value'
                            }
                            inputMode={op?.numeric ? 'decimal' : 'text'}
                            className="min-w-[8rem] flex-1 rounded-md border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 shadow-sm outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
                          />
                        )}

                        {/* Required toggle */}
                        <button
                          type="button"
                          onClick={() => updateFilter(rule.id, { required: !rule.required })}
                          className={cn(
                            'rounded-md border px-2.5 py-1.5 text-[11px] font-semibold transition-colors',
                            rule.required
                              ? 'border-[#0a1f44]/30 bg-[#0a1f44]/10 text-[#0a1f44]'
                              : 'border-gray-200 bg-white text-gray-400 hover:text-gray-700',
                          )}
                        >
                          {rule.required ? 'Required' : 'Optional'}
                        </button>

                        {/* Delete */}
                        <button
                          type="button"
                          onClick={() => removeFilter(rule.id)}
                          className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600"
                          title="Remove filter"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>

                      {/* Value chips */}
                      {!op?.noValue && chips.length > 0 && (
                        <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-8">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Sample values:</span>
                          {chips.map((s, i) => (
                            <button
                              key={i}
                              type="button"
                              onClick={() =>
                                updateFilter(rule.id, {
                                  value: (rule.op === 'in' || rule.op === 'not_in') && rule.value.trim()
                                    ? `${rule.value.trim().replace(/,\s*$/, '')}, ${s}` : s,
                                })
                              }
                              className="rounded-md border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-600 hover:border-[#0a1f44]/40 hover:text-[#0a1f44] transition-colors"
                              title={`Use "${s}"`}
                            >
                              {s}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}

              <button type="button" onClick={addFilter} className="mt-1 inline-flex items-center gap-1.5 rounded-lg border border-dashed border-[#0a1f44]/30 px-4 py-2 text-xs font-semibold text-[#0a1f44] hover:bg-[#0a1f44]/5 transition-colors">
                <Plus className="h-3.5 w-3.5" /> Add Filter
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── 3. Columns — Dimensions, Time, Weight, Measures ──────────────── */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="px-6 pt-5 pb-4">
          <SectionHeader icon={<Tag className="h-4 w-4" />} title="3. Columns" hint="Select dimensions (group by), time axis, weight, and measures" />
        </div>

        {/* Dimensions */}
        <div className="border-t border-gray-100 px-6 py-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Dimensions (Group By)
            </p>
            <span className="text-[11px] text-gray-400">
              {config.dimensions.length} selected of {headerNames.length}
            </span>
          </div>

          {/* Selected dimensions — removable tags */}
          {config.dimensions.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-1.5 rounded-lg border border-[#f5c518]/40 bg-[#f5c518]/5 px-3 py-2.5">
              <span className="mr-1 self-center text-[10px] font-semibold uppercase tracking-wide text-[#b8940e]">Selected:</span>
              {config.dimensions.map((h) => (
                <span
                  key={h}
                  className="inline-flex items-center gap-1 rounded-md border border-[#f5c518]/50 bg-white px-2 py-0.5 text-xs font-medium text-[#b8940e] shadow-sm"
                >
                  {h}
                  <button
                    type="button"
                    onClick={() => toggleDimension(h)}
                    className="ml-0.5 rounded-sm text-[#b8940e]/60 hover:text-red-500 transition-colors"
                    title={`Remove ${h}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* Search box */}
          <div className="relative mb-2">
            <svg className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
            </svg>
            <input
              value={dimSearch}
              onChange={(e) => setDimSearch(e.target.value)}
              placeholder="Search columns…"
              className="w-full rounded-lg border border-gray-200 bg-gray-50 py-2 pl-8 pr-3 text-xs text-gray-800 outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
            />
            {dimSearch && (
              <button type="button" onClick={() => setDimSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Scrollable column list grouped by role */}
          <div className="max-h-52 overflow-y-auto rounded-lg border border-gray-200 bg-white">
            {(() => {
              const filtered = headerNames.filter((h) =>
                !dimSearch || h.toLowerCase().includes(dimSearch.toLowerCase()),
              );
              if (!filtered.length) return (
                <p className="px-4 py-6 text-center text-xs text-gray-400">No columns match &quot;{dimSearch}&quot;</p>
              );
              // Group by role
              const groups: Record<string, string[]> = {};
              filtered.forEach((h) => {
                const role = roleByName.get(h) ?? 'other';
                (groups[role] ??= []).push(h);
              });
              const roleOrder = ['dimension', 'time', 'measure', 'metadata', 'other'];
              const roleLabel: Record<string, string> = { dimension: 'Dimension', time: 'Time', measure: 'Measure', metadata: 'Metadata', other: 'Other' };
              const roleColor: Record<string, string> = { dimension: 'text-blue-600 bg-blue-50', time: 'text-purple-600 bg-purple-50', measure: 'text-green-700 bg-green-50', metadata: 'text-gray-500 bg-gray-100', other: 'text-gray-400 bg-gray-50' };
              return roleOrder.filter((r) => groups[r]?.length).map((role) => (
                <div key={role}>
                  <div className="sticky top-0 z-10 border-b border-gray-100 bg-gray-50 px-3 py-1.5">
                    <span className={cn('rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider', roleColor[role] ?? 'text-gray-400 bg-gray-50')}>
                      {roleLabel[role] ?? role}
                    </span>
                    <span className="ml-2 text-[10px] text-gray-400">{groups[role].length} columns</span>
                  </div>
                  {groups[role].map((h) => {
                    const active = config.dimensions.includes(h);
                    return (
                      <button
                        key={h}
                        type="button"
                        onClick={() => toggleDimension(h)}
                        className={cn(
                          'flex w-full items-center gap-3 px-4 py-2.5 text-left text-xs transition-colors',
                          active
                            ? 'bg-[#f5c518]/10 font-semibold text-[#b8940e]'
                            : 'text-gray-700 hover:bg-gray-50',
                        )}
                      >
                        <span className={cn(
                          'flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors',
                          active ? 'border-[#f5c518] bg-[#f5c518] text-white' : 'border-gray-300 bg-white',
                        )}>
                          {active && <Check className="h-2.5 w-2.5" />}
                        </span>
                        <span className="flex-1 truncate font-mono">{h}</span>
                      </button>
                    );
                  })}
                </div>
              ));
            })()}
          </div>
        </div>

        {/* Time + Weight */}
        <div className="grid gap-4 border-t border-gray-100 px-6 py-4 sm:grid-cols-2">
          <label className="block">
            <FieldLabel>Time column <span className="normal-case font-normal text-gray-400">(optional)</span></FieldLabel>
            <select value={config.timeCol ?? ''} onChange={(e) => update({ timeCol: e.target.value || null })} className={fieldCls}>
              <option value="">— none —</option>
              {headerNames.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
          <label className="block">
            <FieldLabel>
              <span className="flex items-center gap-1"><Scale className="h-3 w-3" /> Multiplier column (wᵢ)</span>
            </FieldLabel>
            <select value={config.weightCol ?? ''} onChange={(e) => update({ weightCol: e.target.value || null })} className={fieldCls}>
              <option value="">— none —</option>
              {(numericHeaders.length ? numericHeaders : headerNames).map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
        </div>

        {/* Measures */}
        <div className="border-t border-gray-100 px-6 py-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
              <Sigma className="h-3.5 w-3.5" /> Measures
            </p>
            <button type="button" onClick={addMeasure} className="inline-flex items-center gap-1.5 rounded-lg border border-[#0a1f44]/20 px-3 py-1.5 text-xs font-semibold text-[#0a1f44] hover:bg-[#0a1f44]/5 transition-colors">
              <Plus className="h-3.5 w-3.5" /> Add Measure
            </button>
          </div>
          {config.measures.length === 0 ? (
            <div className="rounded-lg border-2 border-dashed border-gray-200 bg-gray-50 px-4 py-5 text-center">
              <p className="text-xs text-gray-400">Add at least one measure to compute results.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {config.measures.map((m, idx) => (
                <div key={m.id} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#0a1f44]/10 text-[10px] font-bold text-[#0a1f44]">
                      {idx + 1}
                    </span>
                    <select
                      value={m.col}
                      onChange={(e) => updateMeasure(m.id, { col: e.target.value })}
                      className="min-w-[8rem] flex-1 rounded-md border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 shadow-sm outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
                    >
                      {headerNames.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <input
                      value={m.label}
                      onChange={(e) => updateMeasure(m.id, { label: e.target.value })}
                      placeholder="Display label"
                      className="min-w-[7rem] flex-1 rounded-md border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 shadow-sm outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
                    />
                    <select
                      value={m.agg}
                      onChange={(e) => updateMeasure(m.id, { agg: e.target.value as AggregationKind, weighted: e.target.value === 'weighted_mean' })}
                      className="rounded-md border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 shadow-sm outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
                    >
                      {AGG_OPTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                    </select>
                    <input
                      value={m.unit}
                      onChange={(e) => updateMeasure(m.id, { unit: e.target.value })}
                      placeholder="unit"
                      className="w-20 rounded-md border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 shadow-sm outline-none focus:border-[#0a1f44] focus:ring-2 focus:ring-[#0a1f44]/20"
                    />
                    {/* Weight toggle */}
                    <button
                      type="button"
                      onClick={() => toggleMeasureWeight(m.id)}
                      title={m.weighted ? 'Weighted · click to disable' : 'Apply survey weight (wᵢ)'}
                      aria-pressed={m.weighted}
                      className={cn(
                        'inline-flex h-8 w-8 items-center justify-center rounded-full border text-xs font-bold transition-colors',
                        m.weighted
                          ? 'border-[#0a1f44] bg-[#0a1f44] text-[#f5c518] shadow-sm'
                          : 'border-gray-300 bg-white text-gray-400 hover:border-[#0a1f44] hover:text-[#0a1f44]',
                      )}
                    >
                      W
                    </button>
                    <button type="button" onClick={() => removeMeasure(m.id)} className="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors">
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  {m.weighted && (
                    <p className="mt-1.5 pl-8 text-xs text-[#0a1f44]">
                      ⚖ Weighted by <span className="font-mono font-semibold">{config.weightCol ?? '⚠ no multiplier column selected'}</span>
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── 4. Analysis + Output ─────────────────────────────────────────── */}
      <div className={cn('grid gap-5', hideOutputComponents ? 'lg:grid-cols-1' : 'lg:grid-cols-2')}>

        {/* Analysis */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="px-6 pt-5 pb-4">
            <SectionHeader icon={<BarChart3 className="h-4 w-4" />} title="4. Analysis" hint="How the data should be interpreted" />
          </div>
          <div className="space-y-4 px-6 pb-5">
            <div>
              <FieldLabel>Analysis type</FieldLabel>
              <div className="grid grid-cols-2 gap-2">
                {ANALYSIS_TYPES.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => update({ analysisType: t.value })}
                    className={cn(
                      'flex flex-col items-start rounded-lg border p-3 text-left transition-all',
                      config.analysisType === t.value
                        ? 'border-[#0a1f44] bg-[#0a1f44]/5 shadow-sm'
                        : 'border-gray-200 bg-gray-50 hover:border-gray-300',
                    )}
                  >
                    <span className={cn('text-xs font-bold', config.analysisType === t.value ? 'text-[#0a1f44]' : 'text-gray-700')}>{t.label}</span>
                    <span className="mt-0.5 text-[10px] text-gray-400">{t.desc}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <FieldLabel>Sort by</FieldLabel>
                <select value={config.sortBy ?? ''} onChange={(e) => update({ sortBy: e.target.value || null })} className={fieldCls}>
                  <option value="">— none —</option>
                  {sortOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
              <label className="block">
                <FieldLabel>Order</FieldLabel>
                <select value={config.sortOrder} onChange={(e) => update({ sortOrder: e.target.value as 'asc' | 'desc' })} className={fieldCls}>
                  <option value="desc">Descending ↓</option>
                  <option value="asc">Ascending ↑</option>
                </select>
              </label>
            </div>
          </div>
        </div>

        {/* Output components */}
        {!hideOutputComponents && (
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="px-6 pt-5 pb-4">
            <SectionHeader icon={<Ruler className="h-4 w-4" />} title="5. Output Components" hint="What gets generated for this section" />
          </div>
          <div className="space-y-4 px-6 pb-5">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {COMPONENT_OPTIONS.map((c) => {
                const active = config.components.includes(c.value);
                return (
                  <button
                    key={c.value}
                    type="button"
                    onClick={() => toggleComponent(c.value)}
                    className={cn(
                      'flex items-center gap-2 rounded-lg border p-3 text-sm font-medium transition-all',
                      active
                        ? 'border-[#0a1f44] bg-[#0a1f44]/5 text-[#0a1f44] shadow-sm'
                        : 'border-gray-200 bg-gray-50 text-gray-500 hover:border-gray-300',
                    )}
                  >
                    <span>{c.icon}</span>
                    <span className="text-xs">{c.label}</span>
                    {active && <Check className="ml-auto h-3.5 w-3.5 text-[#0a1f44]" />}
                  </button>
                );
              })}
            </div>
            {config.components.includes('chart') && (
              <label className="block">
                <FieldLabel>Chart type</FieldLabel>
                <select value={config.chartType} onChange={(e) => update({ chartType: e.target.value as ChartType })} className={fieldCls}>
                  {CHART_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </label>
            )}
          </div>
        </div>
        )}
      </div>

      {/* ── 6. Filtered Slice Preview ─────────────────────────────────────── */}
      {slicePreview && (
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-5 pb-4">
            <SectionHeader
              icon={<Table2 className="h-4 w-4" />}
              title="6. Filtered Slice Preview"
              hint={`${slicePreview.total.toLocaleString('en-IN')} row${slicePreview.total === 1 ? '' : 's'} match · ${slicePreview.cols.length} columns`}
            />
            <span className={cn(
              'rounded-full px-3 py-1 text-xs font-semibold',
              slicePreview.total ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700',
            )}>
              {slicePreview.total ? `${slicePreview.total.toLocaleString('en-IN')} rows match` : 'No rows match'}
            </span>
          </div>
          {slicePreview.total === 0 ? (
            <div className="px-6 pb-5">
              <Alert variant="warning" title="No rows match the current filters">
                Loosen a predicate or check the values — the query selects 0 rows.
              </Alert>
            </div>
          ) : (
            <div className="px-6 pb-5">
              <div className="overflow-auto rounded-lg border border-gray-200" style={{ maxHeight: '22rem' }}>
                <table className="w-full border-collapse text-xs">
                  <thead className="sticky top-0 z-10 bg-[#0a1f44] text-white">
                    <tr>
                      <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wide text-white/70">#</th>
                      {slicePreview.cols.map((c) => {
                        const isDim = config.dimensions.includes(c);
                        const isMeasure = config.measures.some((m) => m.col === c);
                        const isFilter = config.filters.some((f) => f.col === c);
                        return (
                          <th key={c} className="whitespace-nowrap px-3 py-2.5 text-left">
                            <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide">
                              <span className={cn(
                                isMeasure ? 'text-[#f5c518]' : isDim ? 'text-white' : 'text-white/70',
                              )}>{c}</span>
                              {isMeasure && <span className="rounded bg-[#f5c518]/20 px-1 text-[8px] text-[#f5c518]">M</span>}
                              {isDim && !isMeasure && <span className="rounded bg-white/20 px-1 text-[8px] text-white/80">D</span>}
                              {isFilter && <Filter className="h-2.5 w-2.5 text-blue-300" />}
                            </span>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {slicePreview.rows.map((row, rIdx) => (
                      <tr key={rIdx} className={cn('transition-colors hover:bg-[#0a1f44]/5', rIdx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50')}>
                        <td className="px-3 py-2 text-[10px] tabular-nums text-gray-400">{rIdx + 1}</td>
                        {slicePreview.cols.map((c) => {
                          const v = row[c];
                          const isNum = typeof v === 'number';
                          return (
                            <td
                              key={c}
                              className={cn(
                                'whitespace-nowrap px-3 py-2 text-xs text-gray-800',
                                isNum && 'text-right tabular-nums font-mono',
                                config.measures.some((m) => m.col === c) && 'font-semibold text-[#0a1f44]',
                              )}
                            >
                              {v === null || v === undefined || v === ''
                                ? <span className="text-gray-300">—</span>
                                : isNum ? (v as number).toLocaleString('en-IN') : String(v)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-gray-400">
                Showing {Math.min(slicePreview.rows.length, SLICE_PREVIEW_ROWS)} of {slicePreview.total.toLocaleString('en-IN')} matching rows.
                {spec.scope.columns.include.length > 0 && ' Columns follow the spec include list.'}
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── 7. Generate ──────────────────────────────────────────────────── */}
      {!hideGenerateControls && (
      <div className="rounded-xl border-2 border-[#0a1f44]/20 bg-gradient-to-br from-[#0a1f44]/5 to-white p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
          <div className="flex items-center gap-2">
            <Code2 className="h-5 w-5 text-[#0a1f44]" />
            <div>
              <h4 className="text-sm font-bold text-[#0a1f44]">report.section.v1</h4>
              <p className="text-[11px] font-mono text-gray-500">{spec.requestId}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setShowJson((v) => !v)} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 transition-colors">
              <Code2 className="h-3.5 w-3.5" /> {showJson ? 'Hide' : 'Show'} JSON
            </button>
            <button type="button" onClick={copyJson} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 transition-colors">
              <Copy className="h-3.5 w-3.5" /> Copy
            </button>
            <button type="button" onClick={downloadJson} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 transition-colors">
              <Download className="h-3.5 w-3.5" /> Download
            </button>
          </div>
        </div>

        {configIssues.length > 0 && (
          <Alert variant="warning" title="Complete the spec before generating">
            <ul className="ml-4 list-disc space-y-0.5">
              {configIssues.map((iss) => <li key={iss} className="text-xs">{iss}</li>)}
            </ul>
          </Alert>
        )}

        {showJson && (
          <pre className="my-3 max-h-72 overflow-auto rounded-lg border border-gray-200 bg-gray-900 p-4 text-[11px] leading-relaxed text-green-400">
            {specJson}
          </pre>
        )}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={generate}
            disabled={configIssues.length > 0 || generating}
            className={cn(
              'inline-flex items-center gap-2 rounded-lg px-6 py-3 text-sm font-bold shadow-sm transition-all',
              configIssues.length > 0 || generating
                ? 'cursor-not-allowed bg-gray-200 text-gray-400'
                : 'bg-[#0a1f44] text-white hover:bg-[#0f2d52] active:scale-[0.98]',
            )}
          >
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {generating ? 'Generating…' : generateLabel}
          </button>
        </div>
      </div>
      )}

      {/* ── 8. Generated Preview ─────────────────────────────────────────── */}
      {!hidePreview && execution && (
        <div className="rounded-xl border border-green-200 bg-green-50 p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-green-600" />
              <div>
                <h4 className="text-sm font-bold text-green-800">Generated Section</h4>
                <p className="text-[11px] text-green-600">
                  {execution.rowsAfterFilter.toLocaleString('en-IN')} of {execution.rowsScanned.toLocaleString('en-IN')} rows · {execution.rows.length} group(s)
                  {execution.cacheHit && ' · cached'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {engineUsed && (
                <span className={cn('rounded-full px-2.5 py-1 text-[10px] font-bold uppercase', engineUsed === 'server' ? 'bg-blue-100 text-blue-700' : 'bg-gray-200 text-gray-600')}>
                  {engineUsed}
                </span>
              )}
              <span className="rounded-full bg-green-200 px-2.5 py-1 text-[10px] font-bold text-green-800">
                {blocks.length} block{blocks.length !== 1 ? 's' : ''}
              </span>
            </div>
          </div>

          {genIssues.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {genIssues.map((iss, i) => (
                <span key={`${iss.code}-${i}`} className={cn(
                  'rounded border px-2.5 py-1 text-[11px] font-medium',
                  iss.severity === 'error' ? 'border-red-200 bg-red-50 text-red-700'
                    : iss.severity === 'warn' ? 'border-yellow-200 bg-yellow-50 text-yellow-700'
                      : 'border-gray-200 bg-white text-gray-500',
                )}>
                  {iss.code}: {iss.message}
                </span>
              ))}
            </div>
          )}

          <div className="space-y-3">
            {blocks.map((b) => <SectionBlockView key={b.id} block={b} />)}
          </div>

          {genWarnings.length > 0 && (
            <label className="mt-4 flex items-center gap-2 text-sm text-yellow-700">
              <input type="checkbox" checked={ackWarnings} onChange={(e) => setAckWarnings(e.target.checked)} className="rounded" />
              Acknowledge {genWarnings.length} warning(s) before appending to the canvas
            </label>
          )}
        </div>
      )}
    </div>
  );
}

export default QueryIndicatorFilters;
