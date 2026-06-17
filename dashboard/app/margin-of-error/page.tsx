'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Info,
  RotateCcw,
  Sigma,
  Target,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import FileDropzone from '@/components/upload/FileDropzone';
import { parseCsv, toNumber, detectNumericColumns, type ParsedCsv } from '@/lib/csv';
import {
  computeWeightedMoE,
  CONFIDENCE_LEVELS,
  MOE_EXAMPLE,
  type ConfidenceLevel,
  type MoEPair,
  type MoEResult,
  type WeightMode,
} from '@/lib/marginOfError';

const COMPUTE_CAP = 200_000; // hard row cap for browser-side aggregation

const MULTIPLIER_PATTERNS: RegExp[] = [
  /^multiplier$/i, /multiplier/i, /^mlt$/i, /^wt$/i, /^wgt$/i,
  /^weight$/i, /weight/i, /survey[_\s-]?weight/i,
];

function detectWeightColumn(headers: string[], numeric: Set<string>): string | null {
  for (const pat of MULTIPLIER_PATTERNS) {
    const hit = headers.find((h) => numeric.has(h) && pat.test(h.trim()));
    if (hit) return hit;
  }
  return null;
}

function fmt(n: number, maxFrac = 2): string {
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('en-IN', { maximumFractionDigits: maxFrac });
}

function pct(n: number, maxFrac = 2): string {
  if (!Number.isFinite(n)) return '—';
  return `${(n * 100).toLocaleString('en-IN', { maximumFractionDigits: maxFrac })}%`;
}

const CONFIDENCE_LABEL: Record<ConfidenceLevel, string> = {
  0.9: '90%',
  0.95: '95%',
  0.99: '99%',
};

const WEIGHT_MODE_META: Record<WeightMode, { label: string; blurb: string }> = {
  frequency: {
    label: 'Frequency / population counts',
    blurb: 'Each weight is the number of population units a row represents (matches the statsmodels DescrStatsW reference).',
  },
  sampling: {
    label: 'Survey sampling weights',
    blurb: 'Each weight is an inverse selection probability; uncertainty is driven by the number of sampled rows (design-based, more conservative).',
  },
};

export default function MarginOfErrorPage() {
  const [parsed, setParsed] = useState<ParsedCsv | null>(null);
  const [sourceName, setSourceName] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);

  const [valueCol, setValueCol] = useState<string>('');
  const [weightCol, setWeightCol] = useState<string>('');
  const [confidence, setConfidence] = useState<ConfidenceLevel>(0.95);
  const [mode, setMode] = useState<WeightMode>('frequency');

  const numericSet = useMemo(() => (parsed ? detectNumericColumns(parsed) : new Set<string>()), [parsed]);
  const numericColumns = useMemo(
    () => (parsed ? parsed.headers.filter((h) => numericSet.has(h)) : []),
    [parsed, numericSet],
  );

  // When a new file/example loads, auto-pick sensible weight + value columns.
  useEffect(() => {
    if (!parsed) return;
    const detectedWeight = detectWeightColumn(parsed.headers, numericSet) ?? '';
    const firstValue = parsed.headers.find((h) => numericSet.has(h) && h !== detectedWeight) ?? '';
    setWeightCol(detectedWeight);
    setValueCol(firstValue);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed]);

  const colIndex = useMemo(() => {
    const map = new Map<string, number>();
    parsed?.headers.forEach((h, i) => map.set(h, i));
    return map;
  }, [parsed]);

  const pairsFor = useMemo(
    () =>
      (column: string): MoEPair[] => {
        if (!parsed) return [];
        const xi = colIndex.get(column);
        const wi = colIndex.get(weightCol);
        if (xi == null || wi == null) return [];
        return parsed.rows.map((r) => ({ value: toNumber(r[xi]), weight: toNumber(r[wi]) }));
      },
    [parsed, colIndex, weightCol],
  );

  const result: MoEResult | null = useMemo(() => {
    if (!parsed || !valueCol || !weightCol || valueCol === weightCol) return null;
    return computeWeightedMoE(pairsFor(valueCol), confidence, mode);
  }, [parsed, valueCol, weightCol, confidence, mode, pairsFor]);

  // Per-column roll-up (every numeric column vs the chosen weight).
  const columnResults = useMemo(() => {
    if (!parsed || !weightCol) return [];
    return numericColumns
      .filter((c) => c !== weightCol)
      .map((c) => ({ column: c, res: computeWeightedMoE(pairsFor(c), confidence, mode) }));
  }, [parsed, weightCol, numericColumns, pairsFor, confidence, mode]);

  const readFile = async (file: File) => {
    setReading(true);
    setError(null);
    try {
      const text = await file.text();
      const result = parseCsv(text, COMPUTE_CAP);
      if (!result.headers.length) {
        setError('Could not read any columns from this file.');
        setParsed(null);
      } else {
        setParsed(result);
        setSourceName(file.name);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to read the CSV file.');
      setParsed(null);
    } finally {
      setReading(false);
    }
  };

  const loadExample = () => {
    setParsed({
      headers: MOE_EXAMPLE.headers,
      rows: MOE_EXAMPLE.rows,
      totalDataRows: MOE_EXAMPLE.rows.length,
      truncated: false,
    });
    setSourceName('Worked example (income × survey_weight)');
    setError(null);
  };

  const reset = () => {
    setParsed(null);
    setSourceName('');
    setError(null);
    setValueCol('');
    setWeightCol('');
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Margin of Error"
        description="Weighted survey estimates with their margin of error and confidence interval — one value column against one multiplier (weight) column, using the statsmodels DescrStatsW methodology."
      />

      {error && <Alert variant="error">{error}</Alert>}

      {!parsed ? (
        <Card className="space-y-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Target className="h-5 w-5" aria-hidden />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text">Load a dataset to begin</h3>
              <p className="mt-1 text-sm text-text-muted">
                Upload a CSV containing your value column (e.g. income) and a multiplier / survey-weight
                column. Everything is computed in your browser — no data leaves this page.
              </p>
            </div>
          </div>
          <FileDropzone onDrop={(files) => files[0] && readFile(files[0])} uploading={reading} />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-text-muted">Supported: CSV with a header row.</p>
            <Button variant="secondary" size="sm" onClick={loadExample}>
              <Sigma className="h-4 w-4" aria-hidden />
              Load worked example
            </Button>
          </div>
        </Card>
      ) : (
        <>
          {/* Source + controls */}
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="flex items-center gap-2 text-sm font-medium text-text">
                <Database className="h-4 w-4 text-text-muted" aria-hidden />
                {sourceName}
                <span className="rounded bg-surface px-1.5 py-0.5 text-xs text-text-muted">
                  {parsed.totalDataRows.toLocaleString('en-IN')} rows
                </span>
              </p>
              <Button variant="ghost" size="sm" onClick={reset}>
                <RotateCcw className="h-4 w-4" aria-hidden />
                Use a different file
              </Button>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-text-muted">Value column</span>
                <select
                  value={valueCol}
                  onChange={(e) => setValueCol(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-primary/40"
                >
                  <option value="" disabled>Select a column…</option>
                  {numericColumns.filter((c) => c !== weightCol).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-text-muted">Weight / multiplier column</span>
                <select
                  value={weightCol}
                  onChange={(e) => setWeightCol(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-primary/40"
                >
                  <option value="" disabled>Select a column…</option>
                  {numericColumns.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>

              <div>
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-text-muted">Confidence level</span>
                <div className="flex gap-1.5">
                  {CONFIDENCE_LEVELS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setConfidence(c)}
                      className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${confidence === c ? 'bg-primary text-white' : 'bg-surface text-text-muted hover:bg-surface-card'}`}
                    >
                      {CONFIDENCE_LABEL[c]}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-text-muted">Weights are…</span>
                <div className="flex flex-col gap-1.5">
                  {(['frequency', 'sampling'] as WeightMode[]).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setMode(m)}
                      title={WEIGHT_MODE_META[m].blurb}
                      className={`rounded-lg px-3 py-1.5 text-left text-xs font-medium transition-colors ${mode === m ? 'bg-primary text-white' : 'bg-surface text-text-muted hover:bg-surface-card'}`}
                    >
                      {WEIGHT_MODE_META[m].label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <p className="mt-2 text-xs text-text-muted">{WEIGHT_MODE_META[mode].blurb}</p>
          </Card>

          {!valueCol || !weightCol ? (
            <Card className="p-8 text-center text-sm text-text-muted">
              Select a value column and a weight column to compute the margin of error.
            </Card>
          ) : valueCol === weightCol ? (
            <Alert variant="warning">The value column and weight column must be different.</Alert>
          ) : result && !result.valid ? (
            <Alert variant="warning">{result.reason}</Alert>
          ) : result ? (
            <>
              <ResultHeadline result={result} valueCol={valueCol} confidence={confidence} />
              <SecondaryMetrics result={result} />
              <MitigationsPanel result={result} mode={mode} />
              <ColumnTable rows={columnResults} weightCol={weightCol} confidence={confidence} />
              <MethodologyNote />
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold text-text">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-text-muted">{hint}</p>}
    </div>
  );
}

function ResultHeadline({
  result,
  valueCol,
  confidence,
}: {
  result: MoEResult;
  valueCol: string;
  confidence: ConfidenceLevel;
}) {
  const q = result.quality;
  return (
    <Card>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.1fr_1fr]">
        {/* Estimate + MoE */}
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-text">
              Weighted estimate of <span className="text-primary">{valueCol}</span>
            </h3>
            <Badge variant={q.key === 'good' ? 'success' : q.key === 'caution' ? 'warning' : q.key === 'unreliable' ? 'danger' : 'muted'}>
              {q.label}
            </Badge>
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-x-3 gap-y-1">
            <span className="text-4xl font-bold text-text">{fmt(result.weightedMean)}</span>
            <span className="pb-1 text-xl font-semibold text-text-muted">± {fmt(result.marginOfError)}</span>
          </div>
          <p className="mt-1 text-sm text-text-muted">
            {CONFIDENCE_LABEL[confidence]} confidence · margin of error is{' '}
            <span className="font-medium text-text">{pct(result.relativeMoE)}</span> of the estimate
          </p>
          <p className="mt-3 text-sm text-text">
            We are {CONFIDENCE_LABEL[confidence]} confident the true weighted mean lies between{' '}
            <span className="font-semibold">{fmt(result.lower)}</span> and{' '}
            <span className="font-semibold">{fmt(result.upper)}</span>.
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Normal approximation (z = {fmt(result.zCritical, 3)}): ± {fmt(result.marginOfErrorZ)}
          </p>
        </div>

        {/* Confidence-interval visual */}
        <ConfidenceIntervalBar result={result} />
      </div>
    </Card>
  );
}

function ConfidenceIntervalBar({ result }: { result: MoEResult }) {
  // Symmetric interval → estimate sits at the centre; whiskers span ±MoE.
  return (
    <div className="flex flex-col justify-center rounded-xl border border-border bg-surface p-4">
      <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-text-muted">Confidence interval</p>
      <div className="relative mx-2 h-16">
        {/* baseline */}
        <div className="absolute left-0 right-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-border" />
        {/* CI band */}
        <div className="absolute left-[8%] right-[8%] top-1/2 h-2 -translate-y-1/2 rounded-full bg-primary/20" />
        {/* end caps */}
        <div className="absolute left-[8%] top-1/2 h-6 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded bg-primary/60" />
        <div className="absolute right-[8%] top-1/2 h-6 w-0.5 translate-x-1/2 -translate-y-1/2 rounded bg-primary/60" />
        {/* estimate marker */}
        <div className="absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-primary shadow" />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <div className="text-left">
          <p className="text-text-muted">Lower</p>
          <p className="font-semibold text-text">{fmt(result.lower)}</p>
        </div>
        <div className="text-center">
          <p className="text-text-muted">Estimate</p>
          <p className="font-semibold text-primary">{fmt(result.weightedMean)}</p>
        </div>
        <div className="text-right">
          <p className="text-text-muted">Upper</p>
          <p className="font-semibold text-text">{fmt(result.upper)}</p>
        </div>
      </div>
    </div>
  );
}

function SecondaryMetrics({ result }: { result: MoEResult }) {
  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <Sigma className="h-4 w-4 text-text-muted" aria-hidden />
        <h3 className="text-sm font-semibold text-text">Statistical detail</h3>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Metric label="Standard error" value={fmt(result.standardError)} hint={`df = ${fmt(result.df, 0)}`} />
        <Metric label="Relative SE" value={pct(result.rse)} hint="SE ÷ estimate" />
        <Metric label="Weighted std dev" value={fmt(result.weightedStd)} hint="ddof = 1" />
        <Metric label="t critical" value={fmt(result.tCritical, 4)} hint={`z = ${fmt(result.zCritical, 4)}`} />
        <Metric label="Σ weights" value={fmt(result.sumWeights, 0)} hint={`${fmt(result.rowsUsed, 0)} rows used`} />
        <Metric label="Effective sample (nₑff)" value={fmt(result.effectiveSampleSize, 1)} hint="Kish formula" />
        <Metric label="Design effect" value={fmt(result.designEffect, 2)} hint="rows ÷ nₑff" />
        <Metric label="Rows excluded" value={fmt(result.rowsSkipped, 0)} hint="missing / non-positive weight" />
      </div>
    </Card>
  );
}

interface Mitigation {
  level: 'info' | 'warning' | 'danger';
  text: string;
}

function buildMitigations(result: MoEResult, mode: WeightMode): Mitigation[] {
  const out: Mitigation[] = [];
  if (result.quality.key === 'unreliable') {
    out.push({ level: 'danger', text: `Estimate is unreliable (RSE ${pct(result.rse)}). Do not publish without aggregation or a larger sample.` });
  } else if (result.quality.key === 'caution') {
    out.push({ level: 'warning', text: `Use with caution (RSE ${pct(result.rse)}). Consider combining categories to improve precision.` });
  }
  if (result.rowsSkipped > 0) {
    out.push({ level: 'info', text: `${fmt(result.rowsSkipped, 0)} row(s) excluded — missing value or non-positive weight${result.nonPositiveWeights > 0 ? ` (${fmt(result.nonPositiveWeights, 0)} with weight ≤ 0)` : ''}.` });
  }
  if (result.uniformWeights) {
    out.push({ level: 'info', text: 'All weights are equal, so the weighted estimate equals the simple (unweighted) mean.' });
  }
  if (Number.isFinite(result.effectiveSampleSize) && result.effectiveSampleSize < 30) {
    out.push({ level: 'warning', text: `Low effective sample size (nₑff = ${fmt(result.effectiveSampleSize, 1)}). The interval is wide and sensitive to individual rows.` });
  }
  if (result.df < 5) {
    out.push({ level: 'warning', text: `Only ${fmt(result.df, 0)} degrees of freedom — the t-interval is broad and approximate.` });
  }
  if (mode === 'frequency' && Number.isFinite(result.designEffect) && result.designEffect > 1.5) {
    out.push({ level: 'warning', text: `Weights vary considerably (design effect ${fmt(result.designEffect, 2)}). If these are survey sampling weights, switch to "Survey sampling weights" — the design-based margin would be about ± ${fmt(inflate(result), 0)}.` });
  }
  if (mode === 'sampling') {
    out.push({ level: 'info', text: 'Design-based mode: uncertainty reflects the number of sampled rows, not the population total the weights sum to.' });
  }
  if (out.length === 0) {
    out.push({ level: 'info', text: 'No data-quality concerns detected for this estimate.' });
  }
  return out;
}

/** Approximate design-based MoE for the cross-check hint (uses stored sampling SE). */
function inflate(result: MoEResult): number {
  return result.tCritical * result.seSampling;
}

function MitigationsPanel({ result, mode }: { result: MoEResult; mode: WeightMode }) {
  const items = buildMitigations(result, mode);
  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-text-muted" aria-hidden />
        <h3 className="text-sm font-semibold text-text">Mitigations &amp; data-quality checks</h3>
      </div>
      <ul className="space-y-2">
        {items.map((m, i) => {
          const Icon = m.level === 'danger' ? AlertTriangle : m.level === 'warning' ? AlertTriangle : m.level === 'info' && result.quality.key === 'good' ? CheckCircle2 : Info;
          const color = m.level === 'danger' ? 'text-danger' : m.level === 'warning' ? 'text-warning' : 'text-text-muted';
          return (
            <li key={i} className="flex items-start gap-2 text-sm text-text">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${color}`} aria-hidden />
              <span>{m.text}</span>
            </li>
          );
        })}
      </ul>
      {/* Cross-check: show the other interpretation's margin so officers see the gap. */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">Frequency-weight margin</p>
          <p className="mt-1 text-sm font-semibold text-text">± {fmt(result.tCritical * result.seFrequency)}</p>
          <p className="text-[11px] text-text-muted">SE {fmt(result.seFrequency)} · treats weights as counts</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">Design-based margin (sampling)</p>
          <p className="mt-1 text-sm font-semibold text-text">± {fmt(result.tCritical * result.seSampling)}</p>
          <p className="text-[11px] text-text-muted">SE {fmt(result.seSampling)} · Hájek linearization</p>
        </div>
      </div>
    </Card>
  );
}

function ColumnTable({
  rows,
  weightCol,
  confidence,
}: {
  rows: Array<{ column: string; res: MoEResult }>;
  weightCol: string;
  confidence: ConfidenceLevel;
}) {
  if (rows.length <= 1) return null;
  return (
    <Card className="p-0">
      <div className="border-b border-border px-5 py-3">
        <h3 className="text-sm font-semibold text-text">Every numeric column × {weightCol}</h3>
        <p className="text-xs text-text-muted">{CONFIDENCE_LABEL[confidence]} confidence · same weight and interpretation as above</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
              <th className="px-5 py-2.5 font-medium">Column</th>
              <th className="px-5 py-2.5 font-medium text-right">Estimate</th>
              <th className="px-5 py-2.5 font-medium text-right">± Margin</th>
              <th className="px-5 py-2.5 font-medium text-right">95% interval</th>
              <th className="px-5 py-2.5 font-medium text-right">RSE</th>
              <th className="px-5 py-2.5 font-medium">Quality</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ column, res }) => (
              <tr key={column} className="border-b border-border/40 last:border-0">
                <td className="px-5 py-2.5 font-medium text-text">{column}</td>
                {res.valid ? (
                  <>
                    <td className="px-5 py-2.5 text-right text-text">{fmt(res.weightedMean)}</td>
                    <td className="px-5 py-2.5 text-right text-text">± {fmt(res.marginOfError)}</td>
                    <td className="px-5 py-2.5 text-right text-text-muted">[{fmt(res.lower)}, {fmt(res.upper)}]</td>
                    <td className="px-5 py-2.5 text-right text-text-muted">{pct(res.rse)}</td>
                    <td className="px-5 py-2.5">
                      <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: res.quality.color }}>
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: res.quality.color }} />
                        {res.quality.label}
                      </span>
                    </td>
                  </>
                ) : (
                  <td colSpan={5} className="px-5 py-2.5 text-text-muted">{res.reason}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function MethodologyNote() {
  return (
    <Card className="bg-surface/60">
      <div className="mb-2 flex items-center gap-2">
        <Info className="h-4 w-4 text-text-muted" aria-hidden />
        <h3 className="text-sm font-semibold text-text">How this is calculated</h3>
      </div>
      <ul className="space-y-1.5 text-sm text-text-muted">
        <li>
          Weighted mean <code className="text-text">x̄_w = Σ(wᵢ·xᵢ) / Σwᵢ</code> and standard error{' '}
          <code className="text-text">SE = √( Σwᵢ(xᵢ − x̄_w)² / (N·(N−1)) )</code>, N = Σwᵢ — the
          statsmodels <code className="text-text">DescrStatsW(ddof=1)</code> result.
        </li>
        <li>
          Margin of error = <code className="text-text">t<sub>(df, 1−α/2)</sub> × SE</code>; the confidence
          interval matches <code className="text-text">tconfint_mean(alpha)</code>. The z-based margin
          (<code className="text-text">1.96 × SE</code> at 95%) is shown for reference.
        </li>
        <li>
          <span className="font-medium text-text">Frequency weights</span> use df = Σw − 1.{' '}
          <span className="font-medium text-text">Survey sampling weights</span> use a design-based
          (Hájek) SE with df = n − 1, reflecting the number of sampled rows.
        </li>
        <li>
          Quality bands follow standard practice on relative standard error: &lt; 16.6% reliable, 16.6–33.3%
          use with caution, &gt; 33.3% unreliable.
        </li>
      </ul>
    </Card>
  );
}
