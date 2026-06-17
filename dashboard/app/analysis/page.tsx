'use client';

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import type { EChartsOption } from 'echarts';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  LabelList,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
} from 'recharts';
import {
  BarChart3,
  CheckCircle2,
  Database,
  FileText,
  Gauge,
  Loader2,
  Scale,
  SlidersHorizontal,
  TriangleAlert,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { EChart } from '@/components/charts/EChart';
import { formatIndiaTime } from '@/lib/datetime';
import {
  analysisApi,
  dashboardApi,
  type ActivityItem,
  type AnalysisResult,
  type DashboardSummary,
} from '@/lib/api';
import {
  buildDatasetAnalysisRows,
  groupImputationByMethod,
  groupValidationBySeverity,
  imputationMissingByColumn,
  outlierColumns,
  phaseCompletion,
  prettifyKey,
  scalarMetrics,
  statusDistribution,
  STATUS_META,
  RISK_COLOR,
  CHART_PALETTE_FALLBACK,
  weightedMeans,
  type AnalysisStatusKey,
  type DatasetAnalysisRow,
} from '@/lib/analysisInsights';

const AXIS_COLOR = '#94a3b8';
const GRID_COLOR = '#e2e8f0';
const PHASE_BAR_COLORS = ['#2563eb', '#7c3aed', '#0d9488', '#d97706'];

/** Shared, polished tooltip surface used across every Recharts chart. */
const CHART_TOOLTIP_STYLE: CSSProperties = {
  borderRadius: 10,
  border: '1px solid #e2e8f0',
  fontSize: 12,
  padding: '8px 10px',
  boxShadow: '0 6px 18px rgba(15, 23, 42, 0.10)',
};

type PhaseStatus = Awaited<ReturnType<typeof analysisApi.getPhaseStatus>>;

interface AnalysisDetailData {
  result: AnalysisResult;
  status: PhaseStatus | null;
}

const STATUS_BADGE: Record<AnalysisStatusKey, 'success' | 'warning' | 'danger' | 'muted'> = {
  complete: 'success',
  running: 'warning',
  failed: 'danger',
  none: 'muted',
};

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof BarChart3;
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{label}</p>
          <p className="mt-1.5 text-2xl font-bold text-text">{value}</p>
          {hint && <p className="mt-0.5 truncate text-xs text-text-muted">{hint}</p>}
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      </div>
    </Card>
  );
}

interface DonutDatum {
  id: string;
  label: string;
  count: number;
  color: string;
}

/** Polished donut (audit-dashboard style): ring + centre total + legend below. */
function DonutChart({
  data,
  height = 240,
  centerLabel = 'total',
}: {
  data: DonutDatum[];
  height?: number;
  centerLabel?: string;
}) {
  const total = data.reduce((sum, d) => sum + d.count, 0);
  return (
    <div>
      <div className="relative" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="count"
              nameKey="label"
              cx="50%"
              cy="50%"
              innerRadius={58}
              outerRadius={88}
              paddingAngle={2}
              stroke="none"
            >
              {data.map((entry) => (
                <Cell key={entry.id} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={CHART_TOOLTIP_STYLE}
              formatter={(value, name) => {
                const n = Number(value);
                const pct = total > 0 ? Math.round((n / total) * 100) : 0;
                return [`${n} · ${pct}%`, name];
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-bold text-text">{total}</span>
          <span className="text-[11px] uppercase tracking-wide text-text-muted">{centerLabel}</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {data.map((entry) => (
          <span key={entry.id} className="inline-flex items-center gap-1.5 text-xs text-text-muted">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
            {entry.label} · <span className="font-semibold text-text">{entry.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function AnalysisInsightsPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailCache, setDetailCache] = useState<Map<number, AnalysisDetailData>>(new Map());
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, a] = await Promise.all([
          dashboardApi.getSummary().catch(() => null),
          dashboardApi.getActivity(300),
        ]);
        if (cancelled) return;
        setSummary(s);
        setItems(a);
      } catch (e: unknown) {
        if (!cancelled) {
          const ax = e as { response?: { data?: { detail?: string } }; message?: string };
          setError(ax.response?.data?.detail || ax.message || 'Failed to load analysis insights');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo(() => buildDatasetAnalysisRows(items, summary), [items, summary]);
  const distribution = useMemo(() => statusDistribution(rows), [rows]);

  const columnsByDataset = useMemo(
    () =>
      rows
        .filter((r) => r.columnCount > 0)
        .slice()
        .sort((a, b) => b.columnCount - a.columnCount)
        .slice(0, 12)
        .map((r) => ({ name: r.name.length > 22 ? `${r.name.slice(0, 21)}…` : r.name, columns: r.columnCount, rows: r.rowCount })),
    [rows],
  );

  const selectedRow = useMemo(() => rows.find((r) => r.id === selectedId) ?? null, [rows, selectedId]);

  const loadDetail = useCallback(
    async (row: DatasetAnalysisRow) => {
      if (row.analysisId == null) return;
      const analysisId = row.analysisId;
      if (detailCache.has(analysisId)) return;
      setDetailLoading(true);
      setDetailError(null);
      try {
        const [result, status] = await Promise.all([
          analysisApi.getResults(analysisId, { includePhase3: true }),
          analysisApi.getPhaseStatus(analysisId).catch(() => null),
        ]);
        setDetailCache((prev) => new Map(prev).set(analysisId, { result, status }));
      } catch (e: unknown) {
        const ax = e as { response?: { data?: { detail?: string } }; message?: string };
        setDetailError(ax.response?.data?.detail || ax.message || 'Failed to load analysis result');
      } finally {
        setDetailLoading(false);
      }
    },
    [detailCache],
  );

  // Auto-select the most recent completed analysis once rows are available.
  useEffect(() => {
    if (selectedId != null) return;
    const first = rows.find((r) => r.analysisStatus === 'complete' && r.analysisId != null) ?? rows.find((r) => r.analysisId != null);
    if (first) {
      setSelectedId(first.id);
      void loadDetail(first);
    }
  }, [rows, selectedId, loadDetail]);

  const onSelect = (row: DatasetAnalysisRow) => {
    setSelectedId(row.id);
    void loadDetail(row);
  };

  const totals = useMemo(() => {
    const analysed = rows.filter((r) => r.analysisId != null).length;
    const complete = rows.filter((r) => r.analysisStatus === 'complete').length;
    const reports = rows.reduce((sum, r) => sum + r.reportCount, 0);
    return { datasets: rows.length, analysed, complete, reports };
  }, [rows]);

  const selectedDetail = selectedRow?.analysisId != null ? detailCache.get(selectedRow.analysisId) ?? null : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analysis"
        description="Per-dataset, per-phase analysis intelligence — validation, imputation, outliers, weighting and profiling — visualised across every dataset."
      />

      {error && <Alert variant="error">{error}</Alert>}

      {loading ? (
        <Card className="p-8 text-sm text-text-muted">Loading analysis insights…</Card>
      ) : rows.length === 0 ? (
        <Card className="p-8 text-center text-sm text-text-muted">
          No datasets yet. Upload a dataset and run an analysis to see phase-by-phase insights here.
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile icon={Database} label="Datasets" value={totals.datasets} hint="in your workspace" />
            <StatTile icon={BarChart3} label="Analyses run" value={totals.analysed} hint="datasets with an analysis" />
            <StatTile icon={CheckCircle2} label="Completed" value={totals.complete} hint="analysis status complete" />
            <StatTile icon={FileText} label="Report jobs" value={totals.reports} hint="generated from analyses" />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-1">
              <h3 className="mb-3 text-sm font-semibold text-text">Analysis status</h3>
              <DonutChart
                data={distribution.map((entry) => ({ id: entry.key, label: entry.label, count: entry.count, color: entry.color }))}
                centerLabel="datasets"
              />
            </Card>

            <Card className="xl:col-span-2">
              <h3 className="mb-3 text-sm font-semibold text-text">Schema width by dataset (columns)</h3>
              {columnsByDataset.length === 0 ? (
                <p className="py-12 text-center text-sm text-text-muted">No profiled datasets yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={Math.max(220, columnsByDataset.length * 30 + 24)}>
                  <BarChart data={columnsByDataset} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} horizontal={false} />
                    <XAxis type="number" tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID_COLOR }} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" width={150} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={CHART_TOOLTIP_STYLE} cursor={{ fill: 'rgba(37,99,235,0.06)' }} />
                    <Bar dataKey="columns" fill="#2563eb" radius={[0, 4, 4, 0]} barSize={16}>
                      <LabelList dataKey="columns" position="right" style={{ fill: AXIS_COLOR, fontSize: 11 }} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-1 p-0">
              <div className="border-b border-border px-4 py-3">
                <h3 className="text-sm font-semibold text-text">Datasets</h3>
                <p className="text-xs text-text-muted">Select one to inspect its phase calculations</p>
              </div>
              <div className="max-h-[640px] overflow-y-auto">
                {rows.map((row) => {
                  const active = row.id === selectedId;
                  return (
                    <button
                      key={row.id}
                      type="button"
                      onClick={() => onSelect(row)}
                      className={`flex w-full items-center justify-between gap-2 border-b border-border/50 px-4 py-3 text-left transition-colors last:border-0 ${active ? 'bg-primary/5 ring-1 ring-inset ring-primary/30' : 'hover:bg-surface'}`}
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-text">{row.name}</p>
                        <p className="mt-0.5 truncate text-xs text-text-muted">
                          {row.rowCount.toLocaleString('en-IN')} rows · {row.columnCount} cols
                        </p>
                      </div>
                      <Badge variant={STATUS_BADGE[row.analysisStatus]}>{STATUS_META[row.analysisStatus].label}</Badge>
                    </button>
                  );
                })}
              </div>
            </Card>

            <div className="lg:col-span-2">
              {!selectedRow ? (
                <Card className="p-8 text-center text-sm text-text-muted">Select a dataset to view its analysis.</Card>
              ) : selectedRow.analysisId == null ? (
                <Card className="p-8 text-center text-sm text-text-muted">
                  <SlidersHorizontal className="mx-auto mb-2 h-6 w-6 text-text-muted" aria-hidden />
                  No analysis has been run for <span className="font-semibold text-text">{selectedRow.name}</span> yet.
                </Card>
              ) : detailLoading && !selectedDetail ? (
                <Card className="flex items-center justify-center gap-2 p-12 text-sm text-text-muted">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading phase calculations…
                </Card>
              ) : detailError && !selectedDetail ? (
                <Alert variant="error">{detailError}</Alert>
              ) : selectedDetail ? (
                <DatasetAnalysisDetail row={selectedRow} detail={selectedDetail} />
              ) : null}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ChartCard({ title, icon: Icon, children, empty }: { title: string; icon: typeof Gauge; children: React.ReactNode; empty?: boolean }) {
  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-text-muted" aria-hidden />
        <h4 className="text-sm font-semibold text-text">{title}</h4>
      </div>
      {empty ? <p className="py-8 text-center text-xs text-text-muted">No data for this phase.</p> : children}
    </Card>
  );
}

function DatasetAnalysisDetail({ row, detail }: { row: DatasetAnalysisRow; detail: AnalysisDetailData }) {
  const { result, status } = detail;
  const phase3 = result.phase3 ?? {};

  const phases = useMemo(() => phaseCompletion(status), [status]);
  const severities = useMemo(() => groupValidationBySeverity(phase3.validation_candidates), [phase3.validation_candidates]);
  const methods = useMemo(() => groupImputationByMethod(phase3.imputation_candidates), [phase3.imputation_candidates]);
  const missing = useMemo(() => imputationMissingByColumn(phase3.imputation_candidates), [phase3.imputation_candidates]);
  const outliers = useMemo(() => outlierColumns(result.outliers), [result.outliers]);
  const weighted = useMemo(() => weightedMeans(result.weighted_profile), [result.weighted_profile]);
  const healthTiles = useMemo(
    () => scalarMetrics(result.health ?? result.profiling_summary, 8),
    [result.health, result.profiling_summary],
  );

  const outlierOption = useMemo<EChartsOption>(
    () => ({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        borderColor: '#e2e8f0',
        borderWidth: 1,
        textStyle: { fontSize: 12 },
        extraCssText: 'border-radius:10px;box-shadow:0 6px 18px rgba(15,23,42,0.10);',
        formatter: (p: unknown) => {
          const arr = p as Array<{ name: string; value: number; data: { risk?: string } }>;
          const first = arr[0];
          return `<strong>${first?.name ?? ''}</strong><br/>${first?.value ?? 0} flagged · ${first?.data?.risk ?? 'unknown'} risk`;
        },
      },
      grid: { left: 8, right: 16, top: 16, bottom: 64, containLabel: true },
      xAxis: {
        type: 'category',
        data: outliers.map((o) => o.column),
        axisLabel: { color: AXIS_COLOR, rotate: 38, interval: 0, width: 90, overflow: 'truncate' },
        axisLine: { lineStyle: { color: GRID_COLOR } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: AXIS_COLOR },
        splitLine: { lineStyle: { color: GRID_COLOR, type: 'dashed' } },
      },
      series: [
        {
          type: 'bar',
          data: outliers.map((o) => ({ value: o.count, risk: o.risk, itemStyle: { color: o.color, borderRadius: [4, 4, 0, 0] } })),
          barMaxWidth: 28,
        },
      ],
    }),
    [outliers],
  );

  const weightApplied = Boolean(result.weighted_profile?.applied);

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-base font-bold text-text">
              <Database className="h-4 w-4 text-text-muted" aria-hidden />
              {row.name}
            </p>
            <p className="mt-0.5 text-xs text-text-muted">
              Analysis #{row.analysisId} · {row.rowCount.toLocaleString('en-IN')} rows · {row.columnCount} columns · completed {formatIndiaTime(row.completedAt)}
            </p>
          </div>
          <Badge variant={STATUS_BADGE[row.analysisStatus]}>{STATUS_META[row.analysisStatus].label}</Badge>
        </div>

        {phases.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Pipeline phase completion</p>
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={phases} layout="vertical" margin={{ top: 0, right: 40, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} horizontal={false} />
                <XAxis type="number" domain={[0, 100]} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID_COLOR }} unit="%" />
                <YAxis type="category" dataKey="label" width={150} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={CHART_TOOLTIP_STYLE}
                  formatter={(value, _name, item) => {
                    const payload = (item?.payload ?? {}) as { reviewed?: number; total?: number };
                    return [`${value}%`, `${payload.reviewed ?? 0}/${payload.total ?? 0} reviewed`];
                  }}
                  cursor={{ fill: 'rgba(37,99,235,0.06)' }}
                />
                <Bar dataKey="pct" radius={[0, 4, 4, 0]} barSize={16}>
                  {phases.map((p, i) => (
                    <Cell key={p.key} fill={PHASE_BAR_COLORS[i % PHASE_BAR_COLORS.length]} />
                  ))}
                  <LabelList dataKey="pct" position="right" formatter={(v) => `${v}%`} style={{ fill: AXIS_COLOR, fontSize: 11 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ChartCard title="Validation issues by severity" icon={TriangleAlert} empty={severities.length === 0}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={severities} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
              <XAxis dataKey="severity" tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID_COLOR }} />
              <YAxis allowDecimals={false} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={false} width={32} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} cursor={{ fill: 'rgba(37,99,235,0.06)' }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} barSize={36}>
                {severities.map((s) => (
                  <Cell key={s.severity} fill={s.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Imputation methods recommended" icon={SlidersHorizontal} empty={methods.length === 0}>
          <DonutChart
            data={methods.map((m, i) => ({ id: m.method, label: m.method, count: m.count, color: CHART_PALETTE_FALLBACK[i % CHART_PALETTE_FALLBACK.length] }))}
            height={220}
            centerLabel="columns"
          />
        </ChartCard>

        <ChartCard title="Missing values by column" icon={BarChart3} empty={missing.length === 0}>
          <ResponsiveContainer width="100%" height={Math.max(180, missing.length * 26 + 24)}>
            <BarChart data={missing} layout="vertical" margin={{ top: 4, right: 28, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} horizontal={false} />
              <XAxis type="number" allowDecimals={false} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID_COLOR }} />
              <YAxis type="category" dataKey="column" width={120} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} cursor={{ fill: 'rgba(37,99,235,0.06)' }} />
              <Bar dataKey="missing" fill="#d97706" radius={[0, 4, 4, 0]} barSize={14}>
                <LabelList dataKey="missing" position="right" style={{ fill: AXIS_COLOR, fontSize: 11 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Outliers detected by column" icon={TriangleAlert} empty={outliers.length === 0}>
          <EChart option={outlierOption} height={240} ariaLabel="Outliers detected per column" />
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
            {(['high', 'medium', 'low'] as const).map((risk) => (
              <span key={risk} className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: RISK_COLOR[risk] }} />
                {risk} risk
              </span>
            ))}
          </div>
        </ChartCard>
      </div>

      {weightApplied && (
        <ChartCard title="Weighted numeric means" icon={Scale} empty={weighted.length === 0}>
          <p className="mb-2 text-xs text-text-muted">
            Weight column <span className="font-medium text-text">{result.weighted_profile?.weight_column ?? '—'}</span>
            {result.weighted_profile?.effective_sample_size != null && (
              <> · effective sample size <span className="font-medium text-text">{Math.round(result.weighted_profile.effective_sample_size).toLocaleString('en-IN')}</span></>
            )}
          </p>
          <ResponsiveContainer width="100%" height={Math.max(180, weighted.length * 28 + 24)}>
            <BarChart data={weighted} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} horizontal={false} />
              <XAxis type="number" tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID_COLOR }} />
              <YAxis type="category" dataKey="column" width={140} tick={{ fill: AXIS_COLOR, fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} cursor={{ fill: 'rgba(13,148,136,0.06)' }} />
              <Bar dataKey="value" fill="#0d9488" radius={[0, 4, 4, 0]} barSize={16}>
                <LabelList dataKey="value" position="right" formatter={(v) => { const n = Number(v); return Number.isInteger(n) ? String(n) : n.toFixed(2); }} style={{ fill: AXIS_COLOR, fontSize: 11 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {healthTiles.length > 0 && (
        <Card>
          <div className="mb-3 flex items-center gap-2">
            <Gauge className="h-4 w-4 text-text-muted" aria-hidden />
            <h4 className="text-sm font-semibold text-text">Dataset health & profiling</h4>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {healthTiles.map((tile) => (
              <div key={tile.label} className="rounded-lg border border-border bg-surface px-3 py-2.5">
                <p className="truncate text-[11px] uppercase tracking-wide text-text-muted">{prettifyKey(tile.label)}</p>
                <p className="mt-1 truncate text-lg font-semibold text-text">{tile.value}</p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
