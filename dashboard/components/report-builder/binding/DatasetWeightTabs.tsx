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
//                           column header. Toggling applies the survey multiplier
//                           wᵢ via the weighted formula:
//                               weighted mean  = Σ(xᵢ · wᵢ/100) / Σ(wᵢ/100)
//                               weighted total = Σ(xᵢ · wᵢ/100)
//   The multiplier column (wᵢ) is auto-detected from the dataset and can be
//   re-selected by the officer. A results panel is shown at the bottom once one
//   or more columns are weighted.
// ─────────────────────────────────────────────────────────────────────────────

const COMPUTE_CAP = 100_000; // hard cap on rows parsed for aggregation (browser safety)
const PREVIEW_ROWS = 100; // rows rendered in the on-screen table
const COLUMN_LIMIT_OPTIONS: Array<number | 'all'> = [10, 25, 50, 100, 'all']; // officer-selectable column counts

interface WeightResult {
  column: string;
  rowsUsed: number;
  rowsSkipped: number;
  weightSum: number; // Σ wᵢ/100
  weightedTotal: number; // Σ xᵢ·wᵢ/100
  weightedMean: number; // weightedTotal / weightSum
  unweightedMean: number; // Σ xᵢ / n
  unweightedTotal: number; // Σ xᵢ
  valid: boolean;
}

interface DatasetWeightTabsProps {
  file: File | null;
  columns: DatasetColumnProfile[];
  datasetName?: string;
  rowCount?: number;
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
  columns,
  datasetName,
  rowCount,
  className,
}: DatasetWeightTabsProps) {
  const [tab, setTab] = useState<'raw' | 'weight'>('raw');
  const [parsed, setParsed] = useState<ParsedCsv | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [multiplierOverride, setMultiplierOverride] = useState<string | null | undefined>(undefined);
  const [weightedCols, setWeightedCols] = useState<Set<string>>(new Set());
  // How many columns the data/weight tables render (officer-selectable).
  const [columnLimit, setColumnLimit] = useState<number | 'all'>(25);

  // Parse the uploaded CSV file client-side whenever it changes. All state
  // updates happen inside async callbacks (never synchronously in the effect).
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

  const loading = Boolean(file) && !parsed && !error;

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

  // Compute weighted aggregates for every toggled-on column.
  const results = useMemo<WeightResult[]>(() => {
    if (!parsed || !multiplierCol) return [];
    const wIdx = colIndex.get(multiplierCol);
    if (wIdx == null) return [];
    return Array.from(weightedCols)
      .filter((column) => column !== multiplierCol)
      .map((column) => {
        const xIdx = colIndex.get(column);
        const res: WeightResult = {
          column,
          rowsUsed: 0,
          rowsSkipped: 0,
          weightSum: 0,
          weightedTotal: 0,
          weightedMean: NaN,
          unweightedMean: NaN,
          unweightedTotal: 0,
          valid: false,
        };
        if (xIdx == null) return res;
        let rawSum = 0;
        for (const row of parsed.rows) {
          const xi = toNumber(row[xIdx]);
          const wi = toNumber(row[wIdx]);
          if (xi === null || wi === null || wi <= 0) {
            res.rowsSkipped += 1;
            continue;
          }
          const w = wi / 100;
          res.weightSum += w;
          res.weightedTotal += xi * w;
          rawSum += xi;
          res.rowsUsed += 1;
        }
        res.unweightedTotal = rawSum;
        res.unweightedMean = res.rowsUsed > 0 ? rawSum / res.rowsUsed : NaN;
        res.weightedMean = res.weightSum > 0 ? res.weightedTotal / res.weightSum : NaN;
        res.valid = res.rowsUsed > 0 && res.weightSum > 0;
        return res;
      });
  }, [parsed, multiplierCol, weightedCols, colIndex]);

  // Σ(wᵢ/100) across every row with a valid multiplier — the shared denominator.
  const multiplierWeightSum = useMemo(() => {
    if (!parsed || !multiplierCol) return 0;
    const wIdx = colIndex.get(multiplierCol);
    if (wIdx == null) return 0;
    let s = 0;
    for (const row of parsed.rows) {
      const wi = toNumber(row[wIdx]);
      if (wi !== null && wi > 0) s += wi / 100;
    }
    return s;
  }, [parsed, multiplierCol, colIndex]);

  const resultByColumn = useMemo(() => {
    const map = new Map<string, WeightResult>();
    results.forEach((r) => map.set(r.column, r));
    return map;
  }, [results]);

  const validResults = useMemo(() => results.filter((r) => r.valid), [results]);
  const combinedWeightedTotal = useMemo(
    () => validResults.reduce((acc, r) => acc + r.weightedTotal, 0),
    [validResults],
  );

  const toggleWeight = (column: string) => {
    setWeightedCols((prev) => {
      const next = new Set(prev);
      if (next.has(column)) next.delete(column);
      else next.add(column);
      return next;
    });
  };

  // ── Empty / loading / error states ────────────────────────────────────────
  if (!file) {
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

  const { headers, rows, totalDataRows, truncated } = parsed;
  const previewRows = rows.slice(0, PREVIEW_ROWS);
  const numericColumnCount = headers.filter((h) => numericSet.has(h) && h !== multiplierCol).length;
  const effectiveColLimit = columnLimit === 'all' ? headers.length : Math.min(columnLimit, headers.length);

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

  const renderTable = (weightMode: boolean) => {
    const wIdx = multiplierCol ? colIndex.get(multiplierCol) ?? null : null;
    const showFooter = weightMode && weightedCols.size > 0;
    // Slice columns to the officer-selected limit. In weight mode always keep the
    // multiplier column visible (so its wᵢ source / footer stays in view).
    const baseDisplayed = headers.slice(0, effectiveColLimit);
    const displayedHeaders = weightMode && multiplierCol && !baseDisplayed.includes(multiplierCol)
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
              const role = roleByName.get(h);
              return (
                <th key={h} className={cn('px-3 py-2 align-bottom', isMultiplier && 'bg-accent/5')}>
                  <div className="flex items-center gap-1.5">
                    <span className="whitespace-nowrap font-semibold text-text">{h}</span>
                    {weightMode && isMultiplier && (
                      <Badge variant="default" className="text-[8px]">
                        wᵢ source
                      </Badge>
                    )}
                    {weightMode && !isMultiplier && (
                      <button
                        type="button"
                        onClick={() => isNumeric && toggleWeight(h)}
                        disabled={!isNumeric}
                        title={
                          isNumeric
                            ? isActive
                              ? `Weighting ON for ${h} — click to turn off`
                              : `Apply the multiplier to ${h}`
                            : 'Weights apply to numeric columns only'
                        }
                        aria-pressed={isActive}
                        className={cn(
                          'inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold lowercase transition-colors',
                          isActive
                            ? 'border-primary bg-primary text-white shadow-sm'
                            : 'border-border bg-surface text-text-muted hover:border-primary hover:text-primary',
                          !isNumeric && 'cursor-not-allowed opacity-30 hover:border-border hover:text-text-muted',
                        )}
                      >
                        w
                      </button>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1">
                    {role && (
                      <span className="text-[9px] uppercase tracking-wide text-text-muted">{role}</span>
                    )}
                    {weightMode && isActive && (
                      <span className="text-[9px] font-medium text-primary">weighted</span>
                    )}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {previewRows.map((row, rIdx) => {
            const wi = wIdx != null ? toNumber(row[wIdx]) : null;
            return (
            <tr key={rIdx} className="hover:bg-primary/[0.03]">
              <td className="px-3 py-1.5 text-[10px] tabular-nums text-text-muted">{rIdx + 1}</td>
              {displayedHeaders.map((h) => {
                const cIdx = colIndex.get(h) ?? -1;
                const isMultiplier = h === multiplierCol;
                const isActive = weightMode && weightedCols.has(h);
                const raw = cIdx >= 0 ? (row[cIdx] ?? '') : '';
                if (isActive) {
                  const xi = toNumber(raw);
                  const factor = wi !== null && wi > 0 ? wi / 100 : null;
                  const weighted = xi !== null && factor !== null ? xi * factor : null;
                  return (
                    <td key={h} className="whitespace-nowrap bg-primary/5 px-3 py-1.5 text-right">
                      {weighted !== null ? (
                        <span className="flex flex-col items-end leading-tight">
                          <span className="font-semibold tabular-nums text-primary">{fmtNum(weighted, 3)}</span>
                          <span className="text-[9px] tabular-nums text-text-muted">{raw} × {fmtNum(factor as number, 2)}</span>
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
                      weightMode && isMultiplier && 'bg-accent/5 font-medium text-accent',
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
                      <span className="flex flex-col items-end leading-tight">
                        <span className="font-bold tabular-nums text-accent">{fmtNum(multiplierWeightSum)}</span>
                        <span className="text-[9px] text-text-muted">Σ(wᵢ/100)</span>
                      </span>
                    </td>
                  );
                }
                if (r && r.valid) {
                  return (
                    <td key={h} className="whitespace-nowrap px-3 py-2 text-right align-bottom">
                      <span className="flex flex-col items-end leading-tight">
                        <span className="font-bold tabular-nums text-primary">{fmtNum(r.weightedTotal)}</span>
                        <span className="text-[9px] text-text-muted">weighted total</span>
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
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
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
            {/* Multiplier selector */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-3">
              <div className="flex items-center gap-2 text-xs">
                <Scale className="h-4 w-4 text-accent" aria-hidden />
                <span className="font-medium text-text">Multiplier column (wᵢ)</span>
                <select
                  value={multiplierCol ?? ''}
                  onChange={(e) => {
                    const val = e.target.value || null;
                    setMultiplierOverride(val);
                    if (val) {
                      setWeightedCols((prev) => {
                        const next = new Set(prev);
                        next.delete(val);
                        return next;
                      });
                    }
                  }}
                  className="rounded-md border border-border bg-surface-card px-2 py-1 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                >
                  <option value="">— select —</option>
                  {headers
                    .filter((h) => numericSet.has(h))
                    .map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                </select>
              </div>
              {weightedCols.size > 0 && (
                <Button type="button" variant="ghost" size="sm" onClick={() => setWeightedCols(new Set())}>
                  Clear weights
                </Button>
              )}
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
                column header to weight it. Each cell then shows{' '}
                <span className="font-mono">xᵢ × wᵢ/100</span> and the column is totalled below; weighted
                mean = <span className="font-mono">Σ(xᵢ·wᵢ/100) ÷ Σ(wᵢ/100)</span>.
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

                {/* Formula reminder */}
                <div className="rounded-lg border border-border bg-surface-card px-4 py-3 font-mono text-xs text-text">
                  <div className="flex items-center gap-2">
                    <Sigma className="h-3.5 w-3.5 text-accent" aria-hidden />
                    weighted&nbsp;mean = Σ(xᵢ · wᵢ/100) ÷ Σ(wᵢ/100)
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-text-muted">
                    <Sigma className="h-3.5 w-3.5" aria-hidden />
                    weighted&nbsp;total = Σ(xᵢ · wᵢ/100)
                  </div>
                </div>

                <div className="overflow-auto rounded-lg border border-border bg-surface-card">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-left text-[10px] uppercase text-text-muted">
                        <th className="px-3 py-2">Column</th>
                        <th className="px-3 py-2 text-right">Rows used</th>
                        <th className="px-3 py-2 text-right">Σ(wᵢ/100)</th>
                        <th className="px-3 py-2 text-right">Weighted total</th>
                        <th className="px-3 py-2 text-right">Weighted mean</th>
                        <th className="px-3 py-2 text-right">Unweighted mean</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {results.map((r) => (
                        <tr key={r.column}>
                          <td className="px-3 py-2 font-medium text-text">{r.column}</td>
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
                                {fmtNum(r.weightedTotal)}
                              </td>
                              <td className="px-3 py-2 text-right font-semibold tabular-nums text-text">
                                {fmtNum(r.weightedMean, 3)}
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums text-text-muted">
                                {fmtNum(r.unweightedMean, 3)}
                              </td>
                            </>
                          ) : (
                            <td colSpan={5} className="px-3 py-2 text-warning">
                              <span className="flex items-center gap-1.5">
                                <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                                No valid (xᵢ, wᵢ) pairs — check the multiplier and column values.
                              </span>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                    {validResults.length > 1 && (
                      <tfoot>
                        <tr className="border-t-2 border-primary/30 bg-primary/5">
                          <td className="px-3 py-2 text-xs font-bold text-text">
                            Combined ({validResults.length} columns)
                          </td>
                          <td className="px-3 py-2 text-right text-text-muted">—</td>
                          <td className="px-3 py-2 text-right tabular-nums text-text-muted">
                            {fmtNum(multiplierWeightSum)}
                          </td>
                          <td className="px-3 py-2 text-right font-bold tabular-nums text-primary">
                            {fmtNum(combinedWeightedTotal)}
                          </td>
                          <td className="px-3 py-2 text-right text-text-muted">—</td>
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
