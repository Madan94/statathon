'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import {
  BarChart3,
  Check,
  Code2,
  Copy,
  Download,
  Filter,
  Layers,
  Play,
  Plus,
  Ruler,
  Scale,
  Sigma,
  Sparkles,
  Table2,
  Tag,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { parseCsv, detectNumericColumns, type ParsedCsv } from '@/lib/csv';
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
  buildSectionBlocks,
  executeWithSliceCache,
  reportSectionDatasetStore,
  validateSectionRequest,
  type DataRow,
  type GeneratedSectionBlock,
  type SectionExecutionResult,
  type SectionIssue,
} from '@/lib/report-section';
import type { DatasetColumnProfile } from '@/lib/api';

// ─────────────────────────────────────────────────────────────────────────────
// Query indicator filters — full section-spec builder + live generation.
//   The officer picks columns (dimensions / measures / time), filters values,
//   optionally weights measures with the "w" button, and chooses the analysis +
//   output components. The config compiles into the team's canonical
//   report.section.v1 request, and the in-browser CSV is run through the team
//   slice engine to GENERATE the section blocks (narrative / table / chart /
//   key finding) right here — proving the BI JSON and the report.
// ─────────────────────────────────────────────────────────────────────────────

const COMPUTE_CAP = 100_000;
const MAX_DISTINCT = 40;
const SLICE_PREVIEW_ROWS = 50; // filtered rows rendered in the slice preview table

const OPERATORS: Array<{ value: FilterOp; label: string; symbol: string; numeric?: boolean; noValue?: boolean }> = [
  { value: 'eq', label: 'equals', symbol: '=' },
  { value: 'ne', label: 'not equals', symbol: '≠' },
  { value: 'gt', label: 'greater than', symbol: '>', numeric: true },
  { value: 'ge', label: 'at least', symbol: '≥', numeric: true },
  { value: 'lt', label: 'less than', symbol: '<', numeric: true },
  { value: 'le', label: 'at most', symbol: '≤', numeric: true },
  { value: 'in', label: 'in list', symbol: '∈' },
  { value: 'not_in', label: 'not in list', symbol: '∉' },
  { value: 'between', label: 'between', symbol: '↔', numeric: true },
  { value: 'contains', label: 'contains', symbol: '⊇' },
  { value: 'is_null', label: 'is empty', symbol: '∅', noValue: true },
  { value: 'not_null', label: 'is not empty', symbol: '≠∅', noValue: true },
];

const AGG_OPTIONS: AggregationKind[] = ['reported_value', 'sum', 'mean', 'weighted_mean', 'count', 'median', 'min', 'max'];
const COMPONENT_OPTIONS: Array<{ value: SectionComponentType; label: string }> = [
  { value: 'narrative', label: 'Narrative' },
  { value: 'table', label: 'Table' },
  { value: 'chart', label: 'Chart' },
  { value: 'metric', label: 'Metric' },
  { value: 'key_finding', label: 'Key finding' },
];
const CHART_TYPES: ChartType[] = ['bar', 'hbar', 'line', 'donut', 'pie'];
const ANALYSIS_TYPES: AnalysisType[] = ['comparison', 'trend', 'ranking', 'distribution', 'summary', 'metric'];

const MULTIPLIER_PATTERNS = [/^multiplier$/i, /^mult$/i, /multiplier/i, /^mlt$/i, /^wt$/i, /^wgt$/i, /^weight$/i, /weight/i];

function detectMultiplierColumn(headers: string[], numeric: Set<string>): string | null {
  for (const pat of MULTIPLIER_PATTERNS) {
    const hit = headers.find((h) => numeric.has(h) && pat.test(h.trim()));
    if (hit) return hit;
  }
  return null;
}

/** Coerce a CSV cell into a typed primitive for the frontend dataset cache. */
function coerceCell(raw: string | undefined): unknown {
  const v = (raw ?? '').trim();
  if (v === '') return null;
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  if (/^(true|false)$/i.test(v)) return /^true$/i.test(v);
  return v;
}

function fmtVal(value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—';
  return Math.abs(value) >= 1000 ? value.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : value.toFixed(Number.isInteger(value) ? 0 : 2);
}

interface QueryIndicatorFiltersProps {
  file: File | null;
  columns: DatasetColumnProfile[];
  config: ReportSectionConfig;
  onChange: (config: ReportSectionConfig) => void;
  templateId: string;
  signature: string;
  datasetId: string;
  onGenerate?: (blocks: GeneratedSectionBlock[], request: ReportSectionRequest, execution: SectionExecutionResult) => void;
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
  className,
}: QueryIndicatorFiltersProps) {
  const [parsed, setParsed] = useState<ParsedCsv | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [blocks, setBlocks] = useState<GeneratedSectionBlock[]>([]);
  const [genIssues, setGenIssues] = useState<SectionIssue[]>([]);
  const [execution, setExecution] = useState<SectionExecutionResult | null>(null);
  const [ackWarnings, setAckWarnings] = useState(false);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    file
      .text()
      .then((text) => {
        if (cancelled) return;
        const result = parseCsv(text, COMPUTE_CAP);
        if (!result.headers.length) {
          setError('Could not read any columns from this file.');
          setParsed(null);
        } else {
          setError(null);
          setParsed(result);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to read the CSV file.');
        setParsed(null);
      });
    return () => {
      cancelled = true;
    };
  }, [file]);

  const headerNames = useMemo(
    () => (parsed ? parsed.headers : columns.map((c) => c.name)),
    [parsed, columns],
  );
  const numericSet = useMemo(() => (parsed ? detectNumericColumns(parsed) : new Set<string>()), [parsed]);
  const numericHeaders = headerNames.filter((h) => numericSet.has(h));
  const roleByName = useMemo(() => {
    const map = new Map<string, DatasetColumnProfile['role']>();
    columns.forEach((c) => map.set(c.name, c.role));
    return map;
  }, [columns]);

  // CSV → typed DataRow[] for the team slice engine (robust quote handling via parseCsv).
  const dataRows = useMemo<DataRow[]>(() => {
    if (!parsed) return [];
    return parsed.rows.map((r) => {
      const obj: DataRow = {};
      parsed.headers.forEach((h, i) => {
        obj[h] = coerceCell(r[i]);
      });
      return obj;
    });
  }, [parsed]);

  // Distinct values per column (for value chips), capped.
  const distinctByColumn = useMemo(() => {
    const map = new Map<string, string[]>();
    if (!parsed) return map;
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

  // Auto-seed a sensible default config the first time the CSV parses (only if empty).
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

  const spec = useMemo(
    () => buildReportSectionSpec(config, { templateId, signature, datasetId }),
    [config, templateId, signature, datasetId],
  );
  const specJson = useMemo(() => JSON.stringify(spec, null, 2), [spec]);
  const configIssues = useMemo(() => validateSectionConfig(config), [config]);

  // Live matched-row count via the team predicate engine (exact contract semantics).
  const match = useMemo(() => {
    if (!dataRows.length) return null;
    const { indexes } = applyPredicates(dataRows, spec.scope.filters);
    return { matched: indexes.length, total: dataRows.length };
  }, [dataRows, spec.scope.filters]);

  // Filtered slice preview — the actual rows the query selects, so the officer
  // can see exactly what the filter returns (capped for display). Columns follow
  // scope.include when set, else all columns.
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

  // ── Filters ───────────────────────────────────────────────────────────────
  const addFilter = () => {
    const firstCol = headerNames[0] ?? '';
    update({ filters: [...config.filters, { id: newId('flt'), col: firstCol, op: 'eq', value: '', required: true }] });
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
      ?? headerNames[0]
      ?? '';
    const measure: SectionMeasure = { id: newId('msr'), col: firstNumeric, label: firstNumeric, agg: 'reported_value', unit: '', weighted: false };
    update({ measures: [...config.measures, measure] });
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
    a.href = url;
    a.download = `${spec.requestId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Generate the report section via the team slice engine ───────────────────
  const generate = () => {
    if (configIssues.length) {
      toast.error(configIssues[0]);
      return;
    }
    if (!dataRows.length) {
      toast.error('No dataset rows to analyse.');
      return;
    }
    reportSectionDatasetStore.registerRows(spec.datasetId, dataRows);
    const snapshot = reportSectionDatasetStore.getSnapshot(spec.datasetId);
    const validation = validateSectionRequest(spec, snapshot);
    if (validation.status === 'cannot_compute') {
      setBlocks([]);
      setExecution(null);
      setGenIssues(validation.issues);
      toast.error('Cannot compute — resolve the errors below.');
      return;
    }
    const result = executeWithSliceCache(spec, reportSectionDatasetStore.getRows(spec.datasetId));
    const built = buildSectionBlocks(spec, result);
    setExecution(result);
    setBlocks(built);
    setGenIssues([...validation.issues, ...result.warnings]);
    setAckWarnings(false);
    onGenerate?.(built, spec, result);
    toast.success(`Generated ${built.length} block(s) · ${result.rowsAfterFilter.toLocaleString('en-IN')} rows after filter`);
  };

  const genWarnings = genIssues.filter((i) => i.severity !== 'info');
  const pct = match && match.total > 0 ? Math.round((match.matched / match.total) * 100) : 0;

  const sectionLabel = (icon: ReactNode, title: string, hint?: string) => (
    <div className="flex items-center gap-2">
      <span className="text-primary">{icon}</span>
      <h4 className="text-sm font-semibold text-text">{title}</h4>
      {hint && <span className="truncate text-[11px] text-text-muted">· {hint}</span>}
    </div>
  );

  const renderBlock = (block: GeneratedSectionBlock) => {
    const rows = (block.tableData?.rows as Array<{ key: Record<string, unknown>; value: number | null; n: number }> | undefined) ?? [];
    const maxVal = rows.reduce((mx, r) => Math.max(mx, Math.abs(r.value ?? 0)), 0) || 1;
    const keyLabel = (k: Record<string, unknown>) => Object.values(k).filter((v) => v != null && v !== '').map(String).join(' / ') || 'All';
    return (
      <div key={block.id} className="rounded-xl border border-border bg-surface-card p-4">
        <div className="mb-2 flex items-center gap-2">
          <Badge variant={block.kind === 'chart' ? 'default' : block.kind === 'table' ? 'warning' : block.kind === 'metric' ? 'success' : 'muted'} className="text-[9px] uppercase">
            {block.kind}
          </Badge>
          <span className="text-sm font-semibold text-text">{block.title}</span>
        </div>
        {(block.kind === 'narrative' || block.kind === 'key_finding' || block.kind === 'source_note') && (
          <p className="text-xs leading-relaxed text-text">{block.content || '—'}</p>
        )}
        {block.kind === 'metric' && (
          <p className="text-2xl font-bold text-primary">
            {block.metricValue}
            {block.metricUnit ? <span className="ml-1 text-sm font-normal text-text-muted">{block.metricUnit}</span> : null}
          </p>
        )}
        {block.kind === 'table' && (
          <div className="overflow-auto rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[10px] uppercase text-text-muted">
                  <th className="px-3 py-1.5">Group</th>
                  <th className="px-3 py-1.5 text-right">{String(block.tableData?.measure ?? 'Value')}</th>
                  <th className="px-3 py-1.5 text-right">n</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="px-3 py-1.5 font-medium text-text">{keyLabel(r.key)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-text">{fmtVal(r.value)}{block.tableData?.unit ? ` ${String(block.tableData.unit)}` : ''}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-text-muted">{r.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {block.kind === 'chart' && (
          <div className="space-y-1.5">
            {rows.slice(0, 12).map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-28 shrink-0 truncate text-[11px] text-text-muted" title={keyLabel(r.key)}>{keyLabel(r.key)}</span>
                <div className="h-3 flex-1 overflow-hidden rounded-full bg-border/30">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round((Math.abs(r.value ?? 0) / maxVal) * 100)}%` }} />
                </div>
                <span className="w-20 shrink-0 text-right text-[11px] tabular-nums text-text">{fmtVal(r.value)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={cn('space-y-4', className)}>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-surface-card px-5 py-4 shadow-sm">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-text">
            <Filter className="h-4 w-4 text-primary" aria-hidden />
            Query indicator builder
            <Badge variant="default" className="text-[9px]">loop template</Badge>
          </h3>
          <p className="mt-0.5 text-xs text-text-muted">
            Pick columns, filter values, weight measures, then generate the <span className="font-mono">report.section.v1</span> section for BI.
          </p>
        </div>
        {match && (
          <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-1.5 text-right">
            <p className="text-sm font-bold tabular-nums text-primary">
              {match.matched.toLocaleString()}
              <span className="text-xs font-normal text-text-muted"> / {match.total.toLocaleString()} rows</span>
            </p>
            <p className="text-[10px] text-text-muted">{pct}% match scope</p>
          </div>
        )}
      </div>

      {error && <Alert variant="error" title="Could not read the dataset">{error}</Alert>}

      {/* Target */}
      <div className="space-y-3 rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
        {sectionLabel(<Layers className="h-4 w-4" />, 'Section target', 'where this lands in the report')}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-text-muted">Chapter title</span>
            <input
              value={config.chapterTitle}
              onChange={(e) => update({ chapterTitle: e.target.value })}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-text-muted">Section title</span>
            <input
              value={config.sectionTitle}
              onChange={(e) => update({ sectionTitle: e.target.value })}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            />
          </label>
        </div>
        <label className="block">
          <span className="text-[11px] uppercase tracking-wide text-text-muted">Description</span>
          <textarea
            value={config.descriptionText}
            onChange={(e) => update({ descriptionText: e.target.value })}
            rows={2}
            placeholder="What should this section show? (used as the generation prompt)"
            className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
          />
        </label>
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-text-muted">Mode</span>
          <div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
            {(['append', 'insert_after'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => update({ mode: m })}
                className={cn(
                  'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                  config.mode === m ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
                )}
              >
                {m === 'append' ? 'Append' : 'Insert after'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="space-y-3 rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
        {sectionLabel(<Filter className="h-4 w-4" />, 'Scope filters', 'restrict which rows are analysed')}

        {config.filters.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-surface px-4 py-6 text-center">
            <p className="text-sm text-text">No filters — the whole dataset is in scope.</p>
            <Button type="button" size="sm" className="mt-2" onClick={addFilter}>
              <Plus className="h-4 w-4" /> Add filter
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            {config.filters.map((rule) => {
              const op = OPERATORS.find((o) => o.value === rule.op);
              const distinct = distinctByColumn.get(rule.col) ?? (columns.find((c) => c.name === rule.col)?.sampleValues ?? []).map(String);
              const chips = distinct.slice(0, 6).filter(Boolean);
              return (
                <div key={rule.id} className="rounded-xl border border-border bg-surface p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={rule.col}
                      onChange={(e) => updateFilter(rule.id, { col: e.target.value })}
                      className="min-w-[9rem] flex-1 rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {headerNames.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <select
                      value={rule.op}
                      onChange={(e) => updateFilter(rule.id, { op: e.target.value as FilterOp })}
                      className="rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {OPERATORS.map((o) => <option key={o.value} value={o.value}>{o.symbol} {o.label}</option>)}
                    </select>
                    {!op?.noValue && (
                      <input
                        value={rule.value}
                        onChange={(e) => updateFilter(rule.id, { value: e.target.value })}
                        placeholder={rule.op === 'in' || rule.op === 'not_in' ? 'a, b, c' : rule.op === 'between' ? 'lo, hi' : op?.numeric ? 'number' : 'value'}
                        inputMode={op?.numeric ? 'decimal' : 'text'}
                        className="min-w-[7rem] flex-1 rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                      />
                    )}
                    <button
                      type="button"
                      onClick={() => updateFilter(rule.id, { required: !rule.required })}
                      title={rule.required ? 'Required filter' : 'Optional filter'}
                      className={cn(
                        'rounded-md border px-2 py-1 text-[10px] font-semibold transition-colors',
                        rule.required ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-surface-card text-text-muted hover:text-text',
                      )}
                    >
                      {rule.required ? 'required' : 'optional'}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeFilter(rule.id)}
                      title="Remove filter"
                      className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-danger/10 hover:text-danger"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {!op?.noValue && chips.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap items-center gap-1 pl-1">
                      <span className="text-[9px] uppercase text-text-muted">values</span>
                      {chips.map((s, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() =>
                            updateFilter(rule.id, {
                              value: (rule.op === 'in' || rule.op === 'not_in') && rule.value.trim()
                                ? `${rule.value.trim().replace(/,\s*$/, '')}, ${s}`
                                : s,
                            })
                          }
                          className="max-w-[7rem] truncate rounded bg-surface-card px-1.5 py-0.5 text-[10px] text-text-muted ring-1 ring-border/60 hover:text-primary"
                          title={`Use “${s}”`}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            <Button type="button" variant="outline" size="sm" onClick={addFilter}>
              <Plus className="h-4 w-4" /> Add filter
            </Button>
          </div>
        )}
      </div>

      {/* Columns: dimensions + time + weight + measures */}
      <div className="space-y-4 rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
        {sectionLabel(<Tag className="h-4 w-4" />, 'Columns', 'pick dimensions, measures and time')}

        {/* Dimensions */}
        <div>
          <p className="mb-1.5 text-[11px] uppercase tracking-wide text-text-muted">Dimensions (group by)</p>
          <div className="flex flex-wrap gap-1.5">
            {headerNames.map((h) => {
              const active = config.dimensions.includes(h);
              const role = roleByName.get(h);
              return (
                <button
                  key={h}
                  type="button"
                  onClick={() => toggleDimension(h)}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors',
                    active ? 'border-warning bg-warning/10 text-warning' : 'border-border bg-surface text-text-muted hover:text-text',
                  )}
                >
                  {active && <Check className="h-3 w-3" />}
                  {h}
                  {role && <span className="text-[8px] uppercase opacity-60">{role}</span>}
                </button>
              );
            })}
          </div>
        </div>

        {/* Time + weight column */}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-text-muted">Time column (optional)</span>
            <select
              value={config.timeCol ?? ''}
              onChange={(e) => update({ timeCol: e.target.value || null })}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              <option value="">— none —</option>
              {headerNames.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-text-muted">
              <Scale className="h-3 w-3" /> Multiplier column (wᵢ)
            </span>
            <select
              value={config.weightCol ?? ''}
              onChange={(e) => update({ weightCol: e.target.value || null })}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              <option value="">— none —</option>
              {(numericHeaders.length ? numericHeaders : headerNames).map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
        </div>

        {/* Measures */}
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-text-muted">
              <Sigma className="h-3 w-3" /> Measures
            </p>
            <Button type="button" variant="outline" size="sm" onClick={addMeasure}>
              <Plus className="h-3.5 w-3.5" /> Add measure
            </Button>
          </div>
          {config.measures.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-surface px-3 py-3 text-center text-xs text-text-muted">
              Add at least one measure to compute.
            </p>
          ) : (
            <div className="space-y-2">
              {config.measures.map((m) => (
                <div key={m.id} className="rounded-xl border border-border bg-surface p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={m.col}
                      onChange={(e) => updateMeasure(m.id, { col: e.target.value })}
                      className="min-w-[8rem] flex-1 rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {headerNames.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <input
                      value={m.label}
                      onChange={(e) => updateMeasure(m.id, { label: e.target.value })}
                      placeholder="label"
                      className="min-w-[7rem] flex-1 rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    />
                    <select
                      value={m.agg}
                      onChange={(e) => updateMeasure(m.id, { agg: e.target.value as AggregationKind, weighted: e.target.value === 'weighted_mean' })}
                      className="rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {AGG_OPTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
                    </select>
                    <input
                      value={m.unit}
                      onChange={(e) => updateMeasure(m.id, { unit: e.target.value })}
                      placeholder="unit"
                      className="w-16 rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    />
                    <button
                      type="button"
                      onClick={() => toggleMeasureWeight(m.id)}
                      title={m.weighted ? 'Weighted by multiplier — click to turn off' : 'Apply survey weight (wᵢ)'}
                      aria-pressed={m.weighted}
                      className={cn(
                        'inline-flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-bold lowercase transition-colors',
                        m.weighted ? 'border-primary bg-primary text-white shadow-sm' : 'border-border bg-surface-card text-text-muted hover:border-primary hover:text-primary',
                      )}
                    >
                      w
                    </button>
                    <button
                      type="button"
                      onClick={() => removeMeasure(m.id)}
                      title="Remove measure"
                      className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-danger/10 hover:text-danger"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {m.weighted && (
                    <p className="mt-1 pl-1 text-[10px] text-primary">
                      Weighted by <span className="font-mono">{config.weightCol ?? '⚠ select a multiplier column'}</span>
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Analysis + components */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3 rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
          {sectionLabel(<BarChart3 className="h-4 w-4" />, 'Analysis')}
          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-text-muted">Type</span>
            <select
              value={config.analysisType}
              onChange={(e) => update({ analysisType: e.target.value as AnalysisType })}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              {ANALYSIS_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wide text-text-muted">Sort by</span>
              <select
                value={config.sortBy ?? ''}
                onChange={(e) => update({ sortBy: e.target.value || null })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                <option value="">— none —</option>
                {sortOptions.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wide text-text-muted">Order</span>
              <select
                value={config.sortOrder}
                onChange={(e) => update({ sortOrder: e.target.value as 'asc' | 'desc' })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                <option value="desc">descending</option>
                <option value="asc">ascending</option>
              </select>
            </label>
          </div>
        </div>

        <div className="space-y-3 rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
          {sectionLabel(<Ruler className="h-4 w-4" />, 'Output components')}
          <div className="flex flex-wrap gap-1.5">
            {COMPONENT_OPTIONS.map((c) => {
              const active = config.components.includes(c.value);
              return (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => toggleComponent(c.value)}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors',
                    active ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-surface text-text-muted hover:text-text',
                  )}
                >
                  {active && <Check className="h-3 w-3" />}
                  {c.label}
                </button>
              );
            })}
          </div>
          {config.components.includes('chart') && (
            <label className="block">
              <span className="text-[11px] uppercase tracking-wide text-text-muted">Chart type</span>
              <select
                value={config.chartType}
                onChange={(e) => update({ chartType: e.target.value as ChartType })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                {CHART_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
          )}
        </div>
      </div>

      {/* Filtered slice preview — the actual rows the query returns */}
      {slicePreview && (
        <div className="space-y-3 rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            {sectionLabel(
              <Table2 className="h-4 w-4" />,
              'Filtered slice preview',
              `${slicePreview.total.toLocaleString('en-IN')} row${slicePreview.total === 1 ? '' : 's'} match · ${slicePreview.cols.length} column${slicePreview.cols.length === 1 ? '' : 's'}`,
            )}
            <Badge variant={slicePreview.total ? 'success' : 'muted'} className="text-[9px]">
              {slicePreview.total ? 'WHERE applied' : 'no rows match'}
            </Badge>
          </div>
          {slicePreview.total === 0 ? (
            <Alert variant="warning" title="No rows match the current filters">
              Loosen a predicate or check the values — the query selects 0 rows.
            </Alert>
          ) : (
            <>
              <div className="max-h-[24rem] overflow-auto rounded-xl border border-border">
                <table className="w-full border-collapse text-xs">
                  <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_0_var(--color-border)]">
                    <tr className="text-left text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                      <th className="px-3 py-2">#</th>
                      {slicePreview.cols.map((c) => {
                        const isDim = config.dimensions.includes(c);
                        const isMeasure = config.measures.some((m) => m.col === c);
                        const isFilter = config.filters.some((f) => f.col === c);
                        return (
                          <th key={c} className="whitespace-nowrap px-3 py-2">
                            <span className="flex items-center gap-1">
                              {c}
                              {isMeasure && <span className="text-success" title="measure">●</span>}
                              {isDim && <span className="text-warning" title="dimension">●</span>}
                              {isFilter && <Filter className="h-2.5 w-2.5 text-primary" aria-label="filtered" />}
                            </span>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {slicePreview.rows.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-primary/[0.03]">
                        <td className="px-3 py-1.5 text-[10px] tabular-nums text-text-muted">{rIdx + 1}</td>
                        {slicePreview.cols.map((c) => {
                          const v = row[c];
                          const isNum = typeof v === 'number';
                          return (
                            <td
                              key={c}
                              className={cn(
                                'whitespace-nowrap px-3 py-1.5 text-text',
                                isNum && 'text-right tabular-nums',
                                config.measures.some((m) => m.col === c) && 'bg-success/5 font-medium',
                              )}
                            >
                              {v === null || v === undefined || v === '' ? <span className="text-text-muted">—</span> : isNum ? (v as number).toLocaleString('en-IN') : String(v)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-text-muted">
                Showing {Math.min(slicePreview.rows.length, SLICE_PREVIEW_ROWS).toLocaleString('en-IN')} of {slicePreview.total.toLocaleString('en-IN')} matching rows.
                {spec.scope.columns.include.length > 0 && ' Columns follow the spec include list.'}
              </p>
            </>
          )}
        </div>
      )}

      {/* Generate + JSON */}
      <div className="space-y-3 rounded-2xl border border-primary/20 bg-primary/5 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {sectionLabel(<Code2 className="h-4 w-4" />, 'report.section.v1', spec.requestId)}
          <div className="flex items-center gap-1.5">
            <Button type="button" variant="outline" size="sm" onClick={() => setShowJson((v) => !v)}>
              {showJson ? 'Hide' : 'Show'} JSON
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={copyJson}>
              <Copy className="h-3.5 w-3.5" /> Copy
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={downloadJson}>
              <Download className="h-3.5 w-3.5" /> Download
            </Button>
          </div>
        </div>

        {configIssues.length > 0 && (
          <Alert variant="warning" title="Finish the spec before generating">
            <ul className="ml-4 list-disc">
              {configIssues.map((iss) => <li key={iss}>{iss}</li>)}
            </ul>
          </Alert>
        )}

        {showJson && (
          <pre className="max-h-[24rem] overflow-auto rounded-xl border border-border bg-surface-card p-4 text-[11px] leading-relaxed text-text">
            {specJson}
          </pre>
        )}

        <div className="flex justify-end">
          <Button type="button" onClick={generate} disabled={configIssues.length > 0}>
            <Play className="h-4 w-4" /> Generate report section
          </Button>
        </div>
      </div>

      {/* Generated section preview */}
      {execution && (
        <div className="space-y-3 rounded-2xl border border-success/30 bg-success/5 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            {sectionLabel(<Sparkles className="h-4 w-4" />, 'Generated section', `${execution.rowsAfterFilter.toLocaleString('en-IN')} of ${execution.rowsScanned.toLocaleString('en-IN')} rows · ${execution.rows.length} group(s)${execution.cacheHit ? ' · cached' : ''}`)}
            <Badge variant="success" className="text-[9px]">{blocks.length} block(s)</Badge>
          </div>

          {genIssues.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {genIssues.map((iss, i) => (
                <span
                  key={`${iss.code}-${i}`}
                  className={cn(
                    'rounded border px-2 py-1 text-[10px]',
                    iss.severity === 'error' ? 'border-danger/30 bg-danger/5 text-danger'
                      : iss.severity === 'warn' ? 'border-warning/30 bg-warning/5 text-warning'
                        : 'border-border bg-surface text-text-muted',
                  )}
                >
                  {iss.code}: {iss.message}
                </span>
              ))}
            </div>
          )}

          <div className="space-y-3">
            {blocks.map(renderBlock)}
          </div>

          {genWarnings.length > 0 && (
            <label className="flex items-center gap-2 text-xs text-warning">
              <input type="checkbox" checked={ackWarnings} onChange={(e) => setAckWarnings(e.target.checked)} />
              Acknowledge {genWarnings.length} warning(s) before appending to the canvas
            </label>
          )}
        </div>
      )}
    </div>
  );
}

export default QueryIndicatorFilters;
