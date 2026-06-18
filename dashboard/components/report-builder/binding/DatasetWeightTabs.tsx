'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Calculator, Scale, Sigma, Table2 } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { parseCsv, toNumber, detectNumericColumns, type ParsedCsv } from '@/lib/csv';
import type { DatasetColumnProfile } from '@/lib/api';

// ─────────────────────────────────────────────────────────────────────────────
// Dataset weight tabs
//   Tab 1 "Data table"   — the raw uploaded CSV, no weighting.
//   Tab 2 "Weight table"  — same rows, with a small "w" toggle on each numeric
//                           column header. Toggling weights that column with a
//                           survey estimator the officer picks per column:
//                               Total       Ŷ = Σ(valueᵢ · wᵢ)
//                               Proportion  p̂ = Σ(wᵢ · Iᵢ) / Σwᵢ
//                               Ratio       R̂ = Σ(wᵢ · yᵢ) / Σ(wᵢ · xᵢ)
//   wᵢ is the per-row weight read from the auto-detected (re-selectable) weight
//   column, optionally ÷100 (NSS/PLFS multipliers are stored ×100). Proportion
//   needs a category value (Iᵢ = 1 when the cell equals it); Ratio needs a
//   denominator column x. A results panel summarises every estimate.
// ─────────────────────────────────────────────────────────────────────────────

const COMPUTE_CAP = 100_000; // hard cap on rows parsed for aggregation (browser safety)
const PREVIEW_ROWS = 100; // rows rendered in the on-screen table
const COLUMN_LIMIT_OPTIONS: Array<number | 'all'> = [10, 25, 50, 100, 'all']; // officer-selectable column counts

// Survey estimators the officer can apply to a weighted column. wᵢ is the
// per-row design weight (optionally ÷100, see WeightScale).
//   total       → Ŷ  = Σ(valueᵢ · wᵢ)                 weighted total
//   proportion  → p̂  = Σ(wᵢ · Iᵢ) / Σwᵢ   Iᵢ∈{0,1}    weighted proportion
//   ratio       → R̂  = Σ(wᵢ · yᵢ) / Σ(wᵢ · xᵢ)       weighted ratio (y over x)
type Estimator = 'total' | 'proportion' | 'ratio';
const ESTIMATOR_ORDER: Estimator[] = ['total', 'proportion', 'ratio'];
const ESTIMATORS: Record<Estimator, { label: string; symbol: string; expr: string; help: string }> = {
  total: {
    label: 'Total',
    symbol: 'Ŷ',
    expr: 'Σ(valueᵢ × wᵢ)',
    help: 'Weighted total — Ŷ = Σ(valueᵢ × weightᵢ).',
  },
  proportion: {
    label: 'Proportion',
    symbol: 'p̂',
    expr: 'Σ(wᵢ·Iᵢ) ÷ Σwᵢ',
    help: 'Weighted proportion of rows whose value equals a chosen category — p̂ = Σ(wᵢ·Iᵢ) ÷ Σwᵢ.',
  },
  ratio: {
    label: 'Ratio',
    symbol: 'R̂',
    expr: 'Σ(wᵢ·yᵢ) ÷ Σ(wᵢ·xᵢ)',
    help: 'Weighted ratio of this column (y) to a denominator column (x) — R̂ = Σ(wᵢ·yᵢ) ÷ Σ(wᵢ·xᵢ).',
  },
};

// How the raw weight column is read into wᵢ. ÷100 is the NSS/PLFS multiplier
// convention; it cancels in Proportion/Ratio but scales the Total.
type WeightScale = 'raw' | 'percent';
const WEIGHT_SCALES: Record<WeightScale, { label: string; expr: string }> = {
  raw: { label: 'Raw wᵢ', expr: 'wᵢ' },
  percent: { label: 'wᵢ ÷ 100', expr: 'wᵢ/100' },
};

// Per weighted column: which estimator and its required inputs.
interface ColumnConfig {
  estimator: Estimator;
  indicatorValue?: string; // proportion: Iᵢ = 1 when the cell equals this value
  denominatorCol?: string; // ratio: the x (denominator) column
}

interface WeightResult {
  column: string;
  estimator: Estimator;
  detail?: string; // category value (proportion) or denominator column (ratio)
  rowsUsed: number;
  rowsSkipped: number;
  weightSum: number; // Σwᵢ over used rows
  numerator: number; // Σ(wᵢ·yᵢ) | Σ(wᵢ·Iᵢ) | Σ(wᵢ·yᵢ)
  denominator: number; // Σwᵢ (proportion) | Σ(wᵢ·xᵢ) (ratio)
  value: number; // Ŷ | p̂ | R̂
  unweightedMean: number; // plain mean / proportion / ratio for comparison
  valid: boolean;
  warning?: string; // set when required config is missing
}

interface DatasetWeightTabsProps {
  /** CSV file to parse client-side. Provide this OR `rows`. */
  file?: File | null;
  /** Pre-parsed slice (object rows keyed by column name) — alternative to `file`. */
  rows?: Array<Record<string, unknown>>;
  /** Column order when `rows` is provided (defaults to `columns` order). */
  headers?: string[];
  columns: DatasetColumnProfile[];
  datasetName?: string;
  rowCount?: number;
  /** Weight-only view: hide the Raw/Weight tab switcher and show the weight table. */
  embedded?: boolean;
  /** Fired when the officer changes the weight (multiplier) column in the selector. */
  onMultiplierColumnChange?: (column: string | null) => void;
  className?: string;
}

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

/** Auto-detect the survey multiplier (wᵢ) column, preferring numeric columns. */
function detectMultiplierColumn(headers: string[], numericSet: Set<string>): string | null {
  for (const pat of MULTIPLIER_PATTERNS) {
    const hit = headers.find((h) => numericSet.has(h) && pat.test(h.trim()));
    if (hit) return hit;
  }
  return null;
}

function fmtNum(n: number, maxFrac = 2): string {
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: maxFrac });
}

export function DatasetWeightTabs({
  file,
  rows,
  headers: providedHeaders,
  columns,
  datasetName,
  rowCount,
  embedded = false,
  onMultiplierColumnChange,
  className,
}: DatasetWeightTabsProps) {
  const [tab, setTab] = useState<'raw' | 'weight'>(embedded ? 'weight' : 'raw');
  const [fileParsed, setFileParsed] = useState<ParsedCsv | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [multiplierOverride, setMultiplierOverride] = useState<string | null | undefined>(undefined);
  // Each weighted column → its estimator config. Columns are independent, so any
  // column may use any of the three survey estimators with its own inputs.
  const [weightedCols, setWeightedCols] = useState<Map<string, ColumnConfig>>(new Map());
  // How many columns the data/weight tables render (officer-selectable).
  const [columnLimit, setColumnLimit] = useState<number | 'all'>(25);
  // Estimator a column starts with when first switched on (editable per column).
  const [defaultEstimator, setDefaultEstimator] = useState<Estimator>('total');
  // How the raw weight column is read into wᵢ (raw, or ÷100 for NSS/PLFS).
  const [weightScale, setWeightScale] = useState<WeightScale>('percent');

  // Parse the uploaded CSV file client-side whenever it changes. Skipped when
  // pre-parsed `rows` are supplied. All state updates happen inside async
  // callbacks (never synchronously in the effect).
  useEffect(() => {
    if (!file || rows) return;
    let cancelled = false;
    file
      .text()
      .then((text) => {
        if (cancelled) return;
        const result = parseCsv(text, COMPUTE_CAP);
        if (!result.headers.length) {
          setError('Could not read any columns from this file.');
          setFileParsed(null);
        } else {
          setError(null);
          setFileParsed(result);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to read the CSV file.');
        setFileParsed(null);
      });
    return () => {
      cancelled = true;
    };
  }, [file, rows]);

  // Build a ParsedCsv-shaped view from the provided object rows (filtered slice).
  const providedParsed = useMemo<ParsedCsv | null>(() => {
    if (!rows) return null;
    const hdrs = providedHeaders && providedHeaders.length ? providedHeaders : columns.map((c) => c.name);
    const stringRows = rows.slice(0, COMPUTE_CAP).map((row) =>
      hdrs.map((h) => {
        const v = row[h];
        return v == null ? '' : String(v);
      }),
    );
    return { headers: hdrs, rows: stringRows, totalDataRows: rows.length, truncated: rows.length > COMPUTE_CAP };
  }, [rows, providedHeaders, columns]);

  // Effective parsed dataset: provided rows take precedence over the file parse.
  const parsed = providedParsed ?? fileParsed;

  const loading = Boolean(file) && !rows && !parsed && !error;

  const numericSet = useMemo(() => (parsed ? detectNumericColumns(parsed) : new Set<string>()), [parsed]);

  // Multiplier column: auto-detected default, overridable by the officer.
  const autoMultiplier = useMemo(
    () => (parsed ? detectMultiplierColumn(parsed.headers, numericSet) : null),
    [parsed, numericSet],
  );
  const multiplierCol = multiplierOverride !== undefined ? multiplierOverride : autoMultiplier;

  const roleByName = useMemo(() => {
    const map = new Map<string, DatasetColumnProfile['role']>();
    columns.forEach((c) => map.set(c.name, c.role));
    return map;
  }, [columns]);

  const colIndex = useMemo(() => {
    const map = new Map<string, number>();
    parsed?.headers.forEach((h, idx) => map.set(h, idx));
    return map;
  }, [parsed]);

  // Per-row design weight wᵢ from the weight column, scaled per WeightScale.
  // Indexed by position in parsed.rows so it lines up with rendered rows.
  const baseWeights = useMemo<(number | null)[]>(() => {
    if (!parsed || !multiplierCol) return [];
    const wIdx = colIndex.get(multiplierCol);
    if (wIdx == null) return [];
    const div = weightScale === 'percent' ? 100 : 1;
    return parsed.rows.map((row) => {
      const wi = toNumber(row[wIdx]);
      return wi !== null && wi > 0 ? wi / div : null;
    });
  }, [parsed, multiplierCol, weightScale, colIndex]);

  // Compute the chosen survey estimator for every toggled-on column.
  const results = useMemo<WeightResult[]>(() => {
    if (!parsed || !multiplierCol) return [];
    return Array.from(weightedCols.entries())
      .filter(([column]) => column !== multiplierCol)
      .map(([column, cfg]) => {
        const yIdx = colIndex.get(column);
        const res: WeightResult = {
          column,
          estimator: cfg.estimator,
          rowsUsed: 0,
          rowsSkipped: 0,
          weightSum: 0,
          numerator: 0,
          denominator: 0,
          value: NaN,
          unweightedMean: NaN,
          valid: false,
        };
        if (yIdx == null) return res;

        if (cfg.estimator === 'proportion') {
          res.detail = cfg.indicatorValue;
          if (!cfg.indicatorValue) {
            res.warning = 'Pick the category value that counts as 1.';
            return res;
          }
          let matches = 0;
          parsed.rows.forEach((row, i) => {
            const w = baseWeights[i];
            if (w === null) {
              res.rowsSkipped += 1;
              return;
            }
            const ind = (row[yIdx] ?? '').trim() === cfg.indicatorValue ? 1 : 0;
            res.weightSum += w;
            res.numerator += w * ind; // Σ(wᵢ·Iᵢ)
            matches += ind;
            res.rowsUsed += 1;
          });
          res.denominator = res.weightSum; // Σwᵢ
          res.value = res.weightSum > 0 ? res.numerator / res.weightSum : NaN; // p̂
          res.unweightedMean = res.rowsUsed > 0 ? matches / res.rowsUsed : NaN;
          res.valid = res.rowsUsed > 0 && res.weightSum > 0;
          return res;
        }

        if (cfg.estimator === 'ratio') {
          res.detail = cfg.denominatorCol;
          const xIdx = cfg.denominatorCol ? colIndex.get(cfg.denominatorCol) : undefined;
          if (xIdx == null) {
            res.warning = 'Pick a denominator column (x).';
            return res;
          }
          let ySum = 0;
          let xSum = 0;
          parsed.rows.forEach((row, i) => {
            const w = baseWeights[i];
            const yi = toNumber(row[yIdx]);
            const xi = toNumber(row[xIdx]);
            if (w === null || yi === null || xi === null) {
              res.rowsSkipped += 1;
              return;
            }
            res.weightSum += w;
            res.numerator += w * yi; // Σ(wᵢ·yᵢ)
            res.denominator += w * xi; // Σ(wᵢ·xᵢ)
            ySum += yi;
            xSum += xi;
            res.rowsUsed += 1;
          });
          res.value = res.denominator !== 0 ? res.numerator / res.denominator : NaN; // R̂
          res.unweightedMean = xSum !== 0 ? ySum / xSum : NaN; // unweighted ratio
          res.valid = res.rowsUsed > 0 && res.denominator !== 0;
          return res;
        }

        // total → Ŷ = Σ(valueᵢ · wᵢ)
        let rawSum = 0;
        parsed.rows.forEach((row, i) => {
          const w = baseWeights[i];
          const yi = toNumber(row[yIdx]);
          if (w === null || yi === null) {
            res.rowsSkipped += 1;
            return;
          }
          res.weightSum += w;
          res.numerator += w * yi;
          rawSum += yi;
          res.rowsUsed += 1;
        });
        res.denominator = res.weightSum;
        res.value = res.numerator; // Ŷ
        res.unweightedMean = res.rowsUsed > 0 ? rawSum / res.rowsUsed : NaN;
        res.valid = res.rowsUsed > 0;
        return res;
      });
  }, [parsed, multiplierCol, weightedCols, colIndex, baseWeights]);

  const resultByColumn = useMemo(() => {
    const map = new Map<string, WeightResult>();
    results.forEach((r) => map.set(r.column, r));
    return map;
  }, [results]);

  const validResults = useMemo(() => results.filter((r) => r.valid), [results]);
  // Combined total only sums Total (Ŷ) columns — adding proportions/ratios is
  // not meaningful.
  const totalResults = useMemo(() => validResults.filter((r) => r.estimator === 'total'), [validResults]);
  const combinedTotal = useMemo(
    () => totalResults.reduce((acc, r) => acc + r.value, 0),
    [totalResults],
  );

  const toggleWeight = (column: string) => {
    setWeightedCols((prev) => {
      const next = new Map(prev);
      if (next.has(column)) next.delete(column);
      else next.set(column, { estimator: defaultEstimator });
      return next;
    });
  };

  const setColumnConfig = (column: string, patch: Partial<ColumnConfig>) => {
    setWeightedCols((prev) => {
      const next = new Map(prev);
      const cur = next.get(column) ?? { estimator: defaultEstimator };
      next.set(column, { ...cur, ...patch });
      return next;
    });
  };

  // Distinct values of a column (for the Proportion indicator picker). Capped
  // so the dropdown stays usable on high-cardinality columns.
  const distinctValuesFor = (colName: string): string[] => {
    const idx = colIndex.get(colName);
    if (idx == null || !parsed) return [];
    const seen = new Set<string>();
    for (const row of parsed.rows) {
      const v = (row[idx] ?? '').trim();
      if (v) seen.add(v);
      if (seen.size >= 200) break;
    }
    return Array.from(seen).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  };

  // ── Empty / loading / error states ────────────────────────────────────────
  if (!file && !rows) {
    return (
      <div className={className}>
        <Alert variant="info" title="No CSV in this session">
          Upload a dataset on the first step to preview its rows and apply survey weights here.
        </Alert>
      </div>
    );
  }
  if (loading) {
    return (
      <div className={cn('rounded-xl border border-border bg-surface-card p-6 text-sm text-text-muted', className)}>
        Reading {datasetName ? `${datasetName}.csv` : 'dataset'}…
      </div>
    );
  }
  if (error || !parsed) {
    return (
      <div className={className}>
        <Alert variant="error" title="Could not preview the dataset">
          {error || 'No rows were found in the uploaded file.'}
        </Alert>
      </div>
    );
  }

  const { headers, rows: parsedRows, totalDataRows, truncated } = parsed;
  const previewRows = parsedRows.slice(0, PREVIEW_ROWS);
  const numericColumnCount = headers.filter((h) => numericSet.has(h) && h !== multiplierCol).length;
  const effectiveColLimit = columnLimit === 'all' ? headers.length : Math.min(columnLimit, headers.length);
  // The weight column wᵢ must be numeric — it is read as the per-row design weight.
  const weightSourceColumns = headers.filter((h) => numericSet.has(h));

  const renderColumnLimitControl = () => (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-[11px] text-text-muted">
        Showing <span className="font-semibold text-text">{Math.min(effectiveColLimit, headers.length)}</span> of {headers.length} columns
      </span>
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] uppercase tracking-wide text-text-muted">Columns</span>
        <div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
          {COLUMN_LIMIT_OPTIONS.map((opt) => {
            const active = columnLimit === opt;
            const disabled = opt !== 'all' && opt >= headers.length && columnLimit !== opt;
            return (
              <button
                key={String(opt)}
                type="button"
                onClick={() => setColumnLimit(opt)}
                disabled={disabled}
                className={cn(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  active ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
                  disabled && 'cursor-not-allowed opacity-30 hover:text-text-muted',
                )}
              >
                {opt === 'all' ? 'All' : opt}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );

  const renderTable = (weightView: boolean) => {
    const showFooter = weightView && weightedCols.size > 0;
    // Slice columns to the officer-selected limit. In weight mode always keep the
    // multiplier column visible (so its wᵢ source / footer stays in view).
    const baseDisplayed = headers.slice(0, effectiveColLimit);
    const displayedHeaders = weightView && multiplierCol && !baseDisplayed.includes(multiplierCol)
      ? [...baseDisplayed, multiplierCol]
      : baseDisplayed;
    return (
    <div className="max-h-[32rem] overflow-auto rounded-xl border border-border">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 z-10 bg-surface-card shadow-[0_1px_0_0_var(--color-border)]">
          <tr className="border-b border-border text-left">
            <th className="px-3 py-2 text-[10px] font-semibold uppercase text-text-muted">#</th>
            {displayedHeaders.map((h) => {
              const isMultiplier = h === multiplierCol;
              const isNumeric = numericSet.has(h);
              const isActive = weightedCols.has(h);
              const cfg = weightedCols.get(h);
              const role = roleByName.get(h);
              return (
                <th key={h} className={cn('px-3 py-2 align-bottom', isMultiplier && 'bg-accent/5')}>
                  <div className="flex items-center gap-1.5">
                    <span className="whitespace-nowrap font-semibold text-text">{h}</span>
                    {weightView && isMultiplier && (
                      <Badge variant="default" className="text-[8px]">
                        wᵢ source
                      </Badge>
                    )}
                    {weightView && !isMultiplier && !isActive && (
                      <button
                        type="button"
                        onClick={() => isNumeric && toggleWeight(h)}
                        disabled={!isNumeric}
                        title={
                          isNumeric
                            ? `Estimate ${h} with the ${ESTIMATORS[defaultEstimator].label} estimator`
                            : 'Weights apply to numeric columns only'
                        }
                        aria-pressed={false}
                        className={cn(
                          'inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold lowercase transition-colors',
                          'border-border bg-surface text-text-muted hover:border-primary hover:text-primary',
                          !isNumeric && 'cursor-not-allowed opacity-30 hover:border-border hover:text-text-muted',
                        )}
                      >
                        w
                      </button>
                    )}
                    {weightView && !isMultiplier && isActive && cfg && (
                      <div className="flex items-center gap-1">
                        <select
                          value={cfg.estimator}
                          onChange={(e) => setColumnConfig(h, { estimator: e.target.value as Estimator })}
                          title={`Estimator for ${h}`}
                          aria-label={`Estimator for ${h}`}
                          className="rounded-md border border-primary/40 bg-primary/10 px-1 py-0.5 text-[10px] font-medium text-primary outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                        >
                          {ESTIMATOR_ORDER.map((est) => (
                            <option key={est} value={est}>
                              {ESTIMATORS[est].label}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => toggleWeight(h)}
                          title={`Turn off weighting for ${h}`}
                          aria-label={`Turn off weighting for ${h}`}
                          className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-border bg-surface text-[9px] text-text-muted transition-colors hover:border-warning hover:text-warning"
                        >
                          ×
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="mt-0.5 flex flex-col gap-1">
                    <div className="flex items-center gap-1">
                      {role && (
                        <span className="text-[9px] uppercase tracking-wide text-text-muted">{role}</span>
                      )}
                      {weightView && isActive && cfg && (
                        <span className="text-[9px] font-medium text-primary">{ESTIMATORS[cfg.estimator].symbol} {ESTIMATORS[cfg.estimator].label}</span>
                      )}
                    </div>
                    {weightView && isActive && cfg?.estimator === 'proportion' && (
                      <select
                        value={cfg.indicatorValue ?? ''}
                        onChange={(e) => setColumnConfig(h, { indicatorValue: e.target.value || undefined })}
                        title={`Category that counts as 1 for ${h}`}
                        aria-label={`Indicator category for ${h}`}
                        className="max-w-[8rem] rounded border border-border bg-surface-card px-1 py-0.5 text-[9px] text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                      >
                        <option value="">= value…</option>
                        {distinctValuesFor(h).map((v) => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>
                    )}
                    {weightView && isActive && cfg?.estimator === 'ratio' && (
                      <select
                        value={cfg.denominatorCol ?? ''}
                        onChange={(e) => setColumnConfig(h, { denominatorCol: e.target.value || undefined })}
                        title={`Denominator column (x) for ${h}`}
                        aria-label={`Denominator column for ${h}`}
                        className="max-w-[8rem] rounded border border-border bg-surface-card px-1 py-0.5 text-[9px] text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                      >
                        <option value="">÷ column…</option>
                        {weightSourceColumns
                          .filter((c) => c !== h && c !== multiplierCol)
                          .map((c) => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                      </select>
                    )}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {previewRows.map((row, rIdx) => {
            return (
            <tr key={rIdx} className="hover:bg-primary/[0.03]">
              <td className="px-3 py-1.5 text-[10px] tabular-nums text-text-muted">{rIdx + 1}</td>
              {displayedHeaders.map((h) => {
                const cIdx = colIndex.get(h) ?? -1;
                const isMultiplier = h === multiplierCol;
                const isActive = weightView && weightedCols.has(h);
                const raw = cIdx >= 0 ? (row[cIdx] ?? '') : '';
                if (isActive) {
                  const cfg = weightedCols.get(h);
                  const w = baseWeights[rIdx] ?? null;
                  const yi = toNumber(raw);
                  let contrib: number | null = null;
                  let sub = '';
                  if (w !== null && Number.isFinite(w)) {
                    if (cfg?.estimator === 'proportion') {
                      const ind = cfg.indicatorValue != null && raw.trim() === cfg.indicatorValue ? 1 : 0;
                      contrib = w * ind;
                      sub = `${fmtNum(w, 3)} × ${ind}`;
                    } else if (yi !== null) {
                      contrib = w * yi;
                      sub = `${raw} × ${fmtNum(w, 3)}`;
                    }
                  }
                  return (
                    <td key={h} className="whitespace-nowrap bg-primary/5 px-3 py-1.5 text-right">
                      {contrib !== null ? (
                        <span className="flex flex-col items-end leading-tight">
                          <span className="font-semibold tabular-nums text-primary">{fmtNum(contrib, 3)}</span>
                          <span className="text-[9px] tabular-nums text-text-muted">{sub}</span>
                        </span>
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                  );
                }
                return (
                  <td
                    key={h}
                    className={cn(
                      'whitespace-nowrap px-3 py-1.5 text-text',
                      numericSet.has(h) && 'text-right tabular-nums',
                      weightView && isMultiplier && 'bg-accent/5 font-medium text-accent',
                    )}
                  >
                    {raw}
                  </td>
                );
              })}
            </tr>
            );
          })}
        </tbody>
        {showFooter && (
          <tfoot className="sticky bottom-0 z-10 bg-surface-card">
            <tr className="border-t-2 border-primary/30">
              <td className="px-3 py-2 text-[11px] font-bold text-primary">Σ</td>
              {displayedHeaders.map((h) => {
                const isMultiplier = h === multiplierCol;
                const r = resultByColumn.get(h);
                if (isMultiplier) {
                  return (
                    <td key={h} className="whitespace-nowrap px-3 py-2 text-right align-bottom">
                      <span className="text-[9px] text-text-muted">wᵢ source</span>
                    </td>
                  );
                }
                if (r && r.valid) {
                  return (
                    <td key={h} className="whitespace-nowrap px-3 py-2 text-right align-bottom">
                      <span className="flex flex-col items-end leading-tight">
                        <span className="font-bold tabular-nums text-primary">
                          {r.estimator === 'proportion' ? `${fmtNum(r.value * 100, 2)}%` : fmtNum(r.value, r.estimator === 'ratio' ? 4 : 2)}
                        </span>
                        <span className="text-[9px] text-text-muted">{ESTIMATORS[r.estimator].symbol} {ESTIMATORS[r.estimator].label}</span>
                      </span>
                    </td>
                  );
                }
                return <td key={h} className="px-3 py-2" />;
              })}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
    );
  };

  return (
    <div className={cn('rounded-2xl border border-border bg-surface-card shadow-sm', className)}>
      {/* Header + tab switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-text">
            <Table2 className="h-4 w-4 text-primary" aria-hidden />
            {datasetName ? `${datasetName}.csv` : 'Uploaded dataset'}
          </h3>
          <p className="mt-0.5 text-xs text-text-muted">
            {(rowCount ?? totalDataRows).toLocaleString()} rows × {headers.length} columns
            {truncated && ` · previewing first ${COMPUTE_CAP.toLocaleString()} for weighting`}
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
          <button
            type="button"
            onClick={() => setTab('raw')}
            hidden={embedded}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              embedded && 'hidden',
              tab === 'raw' ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
            )}
          >
            <Table2 className="h-3.5 w-3.5" aria-hidden /> Data table
          </button>
          <button
            type="button"
            onClick={() => setTab('weight')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              embedded && 'pointer-events-none',
              tab === 'weight' ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
            )}
          >
            <Scale className="h-3.5 w-3.5" aria-hidden /> Weight table
          </button>
        </div>
      </div>

      <div className="space-y-4 p-5">
        {tab === 'raw' && (
          <>
            <p className="text-xs text-text-muted">
              Raw uploaded data, exactly as profiled — no weights applied. Switch to{' '}
              <span className="font-medium text-text">Weight table</span> to apply survey multipliers.
            </p>
            {renderColumnLimitControl()}
            {renderTable(false)}
            <p className="text-[11px] text-text-muted">
              Showing {previewRows.length.toLocaleString()} of {totalDataRows.toLocaleString()} rows.
            </p>
          </>
        )}

        {tab === 'weight' && (
          <>
            {/* Weight column + formula selector */}
            <div className="space-y-3 rounded-lg border border-border bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-xs">
                  <Scale className="h-4 w-4 text-accent" aria-hidden />
                  <span className="font-medium text-text">Weight column (wᵢ)</span>
                  <select
                    value={multiplierCol ?? ''}
                    onChange={(e) => {
                      const val = e.target.value || null;
                      setMultiplierOverride(val);
                      onMultiplierColumnChange?.(val);
                      if (val) {
                        setWeightedCols((prev) => {
                          const next = new Map(prev);
                          next.delete(val);
                          return next;
                        });
                      }
                    }}
                    className="rounded-md border border-border bg-surface-card px-2 py-1 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                  >
                    <option value="">— select —</option>
                    {weightSourceColumns.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </div>
                {weightedCols.size > 0 && (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setWeightedCols(new Map())}>
                    Clear weights
                  </Button>
                )}
              </div>

              {/* Weight scale — how the raw weight column is read into wᵢ. */}
              <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                <span className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">
                  <Scale className="h-3.5 w-3.5 text-accent" aria-hidden /> Weight scale
                </span>
                <div className="inline-flex rounded-lg border border-border bg-surface-card p-0.5">
                  {(['raw', 'percent'] as WeightScale[]).map((scale) => {
                    const active = weightScale === scale;
                    return (
                      <button
                        key={scale}
                        type="button"
                        onClick={() => setWeightScale(scale)}
                        title={scale === 'percent' ? 'Divide each weight by 100 (NSS/PLFS multipliers are stored ×100).' : 'Use the weight column value directly.'}
                        className={cn(
                          'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                          active ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
                        )}
                      >
                        {WEIGHT_SCALES[scale].label}
                      </button>
                    );
                  })}
                </div>
                <code className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-text-muted">wᵢ = {WEIGHT_SCALES[weightScale].expr}</code>
              </div>

              {/* Default estimator — applied the moment a column is switched on.
                  Each column's estimator (and its inputs) is then editable from
                  its table header, so columns can use different estimators. */}
              <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                <span className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">
                  <Sigma className="h-3.5 w-3.5 text-accent" aria-hidden /> New-column estimator
                </span>
                <div className="inline-flex flex-wrap rounded-lg border border-border bg-surface-card p-0.5">
                  {ESTIMATOR_ORDER.map((est) => {
                    const active = defaultEstimator === est;
                    return (
                      <button
                        key={est}
                        type="button"
                        title={ESTIMATORS[est].help}
                        onClick={() => setDefaultEstimator(est)}
                        className={cn(
                          'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                          active ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
                        )}
                      >
                        {ESTIMATORS[est].label}
                      </button>
                    );
                  })}
                </div>
                <span className="text-[10px] text-text-muted">
                  Applied when you switch a column on — change any column&apos;s estimator in its header.
                </span>
              </div>
            </div>

            {!multiplierCol ? (
              <Alert variant="warning" title="Select a multiplier column">
                No survey multiplier was auto-detected. Pick the column that holds the per-row weight
                (wᵢ) above to enable weighting.
              </Alert>
            ) : numericColumnCount === 0 ? (
              <Alert variant="info" title="No measures to weight">
                This dataset has no numeric measure columns besides the multiplier.
              </Alert>
            ) : (
              <p className="text-xs text-text-muted">
                Click the <span className="font-semibold text-primary">w</span> button on any numeric
                column to estimate it with the{' '}
                <span className="font-medium text-text">{ESTIMATORS[defaultEstimator].label}</span> estimator,
                then change that column&apos;s estimator (and its inputs) from its header. Total ={' '}
                <span className="font-mono">Σ(yᵢ·wᵢ)</span>, Proportion ={' '}
                <span className="font-mono">Σ(wᵢ·Iᵢ)÷Σwᵢ</span>, Ratio ={' '}
                <span className="font-mono">Σ(wᵢ·yᵢ)÷Σ(wᵢ·xᵢ)</span>.
              </p>
            )}

            {renderColumnLimitControl()}
            {renderTable(true)}
            <p className="text-[11px] text-text-muted">
              Showing {previewRows.length.toLocaleString()} of {totalDataRows.toLocaleString()} rows ·
              aggregates computed over all {Math.min(totalDataRows, COMPUTE_CAP).toLocaleString()} rows.
            </p>

            {/* Results */}
            {multiplierCol && weightedCols.size > 0 && (
              <div className="space-y-4 rounded-xl border border-primary/20 bg-primary/5 p-4">
                <div className="flex items-center gap-2">
                  <Calculator className="h-4 w-4 text-primary" aria-hidden />
                  <h4 className="text-sm font-semibold text-text">Weighted results</h4>
                </div>

                {/* Estimator formulas */}
                <div className="space-y-1 rounded-lg border border-border bg-surface-card px-4 py-3 font-mono text-xs text-text">
                  <div className="flex items-center gap-2">
                    <Sigma className="h-3.5 w-3.5 text-accent" aria-hidden />
                    Total&nbsp;Ŷ = Σ(valueᵢ · wᵢ)
                  </div>
                  <div className="flex items-center gap-2 text-text-muted">
                    <Sigma className="h-3.5 w-3.5" aria-hidden />
                    Proportion&nbsp;p̂ = Σ(wᵢ · Iᵢ) ÷ Σwᵢ
                  </div>
                  <div className="flex items-center gap-2 text-text-muted">
                    <Sigma className="h-3.5 w-3.5" aria-hidden />
                    Ratio&nbsp;R̂ = Σ(wᵢ · yᵢ) ÷ Σ(wᵢ · xᵢ)
                  </div>
                  <div className="flex items-center gap-2 text-text-muted">
                    <Calculator className="h-3.5 w-3.5" aria-hidden />
                    wᵢ = {WEIGHT_SCALES[weightScale].expr} · each column uses its own estimator
                  </div>
                </div>

                <div className="overflow-auto rounded-lg border border-border bg-surface-card">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-left text-[10px] uppercase text-text-muted">
                        <th className="px-3 py-2">Column</th>
                        <th className="px-3 py-2">Estimator</th>
                        <th className="px-3 py-2">Inputs</th>
                        <th className="px-3 py-2 text-right">Rows used</th>
                        <th className="px-3 py-2 text-right">Σwᵢ</th>
                        <th className="px-3 py-2 text-right">Estimate</th>
                        <th className="px-3 py-2 text-right">Unweighted</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {results.map((r) => (
                        <tr key={r.column}>
                          <td className="px-3 py-2 font-medium text-text">{r.column}</td>
                          <td className="px-3 py-2">
                            <span className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-2 py-0.5 text-[10px] font-medium text-primary">
                              {ESTIMATORS[r.estimator].symbol} {ESTIMATORS[r.estimator].label}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-[10px] text-text-muted">
                            {r.estimator === 'proportion' && (r.detail ? `= ${r.detail}` : '—')}
                            {r.estimator === 'ratio' && (r.detail ? `÷ ${r.detail}` : '—')}
                            {r.estimator === 'total' && '—'}
                          </td>
                          {r.valid ? (
                            <>
                              <td className="px-3 py-2 text-right tabular-nums text-text-muted">
                                {r.rowsUsed.toLocaleString()}
                                {r.rowsSkipped > 0 && (
                                  <span className="ml-1 text-[9px] text-warning">
                                    (−{r.rowsSkipped.toLocaleString()})
                                  </span>
                                )}
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums">{fmtNum(r.weightSum)}</td>
                              <td className="px-3 py-2 text-right font-semibold tabular-nums text-primary">
                                {r.estimator === 'proportion'
                                  ? `${fmtNum(r.value * 100, 2)}%`
                                  : fmtNum(r.value, r.estimator === 'ratio' ? 4 : 2)}
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums text-text-muted">
                                {r.estimator === 'proportion'
                                  ? `${fmtNum(r.unweightedMean * 100, 2)}%`
                                  : fmtNum(r.unweightedMean, r.estimator === 'ratio' ? 4 : 3)}
                              </td>
                            </>
                          ) : (
                            <td colSpan={4} className="px-3 py-2 text-warning">
                              <span className="flex items-center gap-1.5">
                                <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                                {r.warning ?? 'No valid (value, weight) rows — check the weight column and values.'}
                              </span>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                    {totalResults.length > 1 && (
                      <tfoot>
                        <tr className="border-t-2 border-primary/30 bg-primary/5">
                          <td className="px-3 py-2 text-xs font-bold text-text">
                            Combined total ({totalResults.length} columns)
                          </td>
                          <td className="px-3 py-2 text-text-muted">—</td>
                          <td className="px-3 py-2 text-text-muted">—</td>
                          <td className="px-3 py-2 text-right text-text-muted">—</td>
                          <td className="px-3 py-2 text-right text-text-muted">—</td>
                          <td className="px-3 py-2 text-right font-bold tabular-nums text-primary">
                            {fmtNum(combinedTotal)}
                          </td>
                          <td className="px-3 py-2 text-right text-text-muted">—</td>
                        </tr>
                      </tfoot>
                    )}
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default DatasetWeightTabs;
