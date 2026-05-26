'use client';

import { useState, useMemo } from 'react';
import type { AnalysisResult, AnomalyCandidate, AnomalyExplain } from '@/lib/api';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import {
  TrendingUp, Zap, CheckCircle2, AlertTriangle, ChevronDown,
  ChevronRight, Info, Wand2, Layers, Filter,
} from 'lucide-react';

export type AnomalyDecision = Decision;

interface Props {
  column: string;
  results: AnalysisResult;
  className?: string;
  decisions?: Record<number, Decision>;
  onDecisionsChange?: (decisions: Record<number, Decision>) => void;
}

type Decision = 'keep' | 'remove_value' | 'remove_row' | 'treat_missing' | 'mark_valid';

const DECISIONS: { value: Decision; label: string; short: string; colorActive: string; colorIdle: string }[] = [
  { value: 'keep',          label: 'Keep',             short: 'Keep',    colorActive: 'bg-border text-text border-border',            colorIdle: 'border-border text-text-muted hover:bg-border/50' },
  { value: 'remove_value',  label: 'Remove value',     short: 'Rm val',  colorActive: 'bg-warning text-white border-warning',         colorIdle: 'border-warning/50 text-warning hover:bg-warning/10' },
  { value: 'remove_row',    label: 'Remove row',       short: 'Rm row',  colorActive: 'bg-danger text-white border-danger',           colorIdle: 'border-danger/50 text-danger hover:bg-danger/10' },
  { value: 'treat_missing', label: 'Treat as missing', short: 'Missing', colorActive: 'bg-primary text-white border-primary',         colorIdle: 'border-primary/50 text-primary hover:bg-primary/10' },
  { value: 'mark_valid',    label: 'Mark valid',       short: 'Valid',   colorActive: 'bg-success text-white border-success',         colorIdle: 'border-success/50 text-success hover:bg-success/10' },
];

function sevVariant(s: string): 'danger' | 'warning' | 'muted' {
  const lc = (s ?? '').toLowerCase();
  return lc === 'extreme' ? 'danger' : lc === 'medium' ? 'warning' : 'muted';
}
function sevOrder(s: string): number {
  const lc = (s ?? '').toLowerCase();
  return lc === 'extreme' ? 0 : lc === 'medium' ? 1 : 2;
}

interface RowEntry {
  row: number;
  value: unknown;
  zscore: AnomalyCandidate | null;
  iqr:    AnomalyCandidate | null;
  maxSeverity: string;
  /** recommended action derived from confidence + both method metrics */
  recommended: Decision;
}

/** Derive a smart recommended action from severity + both method signals */
function deriveRecommendation(entry: Omit<RowEntry, 'recommended'>): Decision {
  const sev = (entry.maxSeverity ?? '').toLowerCase();
  const zMetric = entry.zscore && typeof entry.zscore.explain === 'object'
    ? Math.abs(Number((entry.zscore.explain as AnomalyExplain).metric ?? 0)) : 0;
  const iqrMetric = entry.iqr && typeof entry.iqr.explain === 'object'
    ? Math.abs(Number((entry.iqr.explain as AnomalyExplain).metric ?? 0)) : 0;
  const bothAgree = entry.zscore && entry.iqr;

  if (sev === 'extreme' && bothAgree) return 'remove_value';
  if (sev === 'extreme' && iqrMetric > 3) return 'remove_value';
  if (sev === 'extreme' && zMetric > 4) return 'remove_value';
  if (sev === 'extreme') return 'treat_missing';
  if (sev === 'medium' && bothAgree) return 'treat_missing';
  if (sev === 'medium') return 'treat_missing';
  return 'keep';
}

// ── Compact bell curve ──────────────────────────────────────────────────────
function MiniCurve({ candidates }: { candidates: AnomalyCandidate[] }) {
  const W = 260, H = 70, PAD = 16;
  const gauss = (x: number) => Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
  const yPeak = gauss(0);
  const toSVG = (x: number, y: number): [number, number] => [
    PAD + ((x + 4.5) / 9) * (W - 2 * PAD),
    (H - PAD) - (y / yPeak) * (H - 2 * PAD),
  ];
  const path = Array.from({ length: 91 }, (_, i) => {
    const x = -4.5 + i * 0.1;
    const [sx, sy] = toSVG(x, gauss(x));
    return `${i === 0 ? 'M' : 'L'} ${sx.toFixed(1)} ${sy.toFixed(1)}`;
  }).join(' ');
  const [, baseY] = toSVG(0, 0);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full">
      {[[-4.5, -3], [3, 4.5]].map(([a, b], i) => {
        const pts = Array.from({ length: 16 }, (_, j) => {
          const x = a + (j / 15) * (b - a);
          const [sx, sy] = toSVG(x, gauss(x));
          return `${j === 0 ? 'M' : 'L'} ${sx.toFixed(1)} ${sy.toFixed(1)}`;
        });
        const [ax] = toSVG(a, 0); const [bx] = toSVG(b, 0);
        return <path key={i} d={pts.join(' ') + ` L ${bx.toFixed(1)} ${baseY.toFixed(1)} L ${ax.toFixed(1)} ${baseY.toFixed(1)} Z`} fill="#ef4444" fillOpacity={0.15} />;
      })}
      <path d={path} fill="none" stroke="#6366f1" strokeWidth="1.5" />
      <line x1={PAD} y1={baseY} x2={W - PAD} y2={baseY} stroke="#334155" strokeWidth="1" />
      {[-3, 3].map(z => { const [sx] = toSVG(z, 0); return <line key={z} x1={sx} y1={PAD} x2={sx} y2={baseY} stroke="#ef4444" strokeWidth="1" strokeDasharray="2,2" />; })}
      {candidates.map((c, i) => {
        const m = typeof c.explain === 'object' ? (c.explain as AnomalyExplain).metric : null;
        if (m == null) return null;
        const z = Math.min(Math.abs(Number(m)), 4.5);
        const [sx, sy] = toSVG(z, gauss(z));
        return <circle key={i} cx={sx} cy={sy} r="3.5" fill={sevVariant(c.severity) === 'danger' ? '#ef4444' : '#f59e0b'} stroke="#0d1117" strokeWidth="1" />;
      })}
    </svg>
  );
}

function MiniBoxPlot({ candidates }: { candidates: AnomalyCandidate[] }) {
  const W = 260, H = 70, midY = 38, boxH = 20, PAD = 20;
  const excesses = candidates.map(c => typeof c.explain === 'object' ? Math.abs(Number((c.explain as AnomalyExplain).metric ?? 0)) : 0);
  const maxEx = Math.max(...excesses, 2);
  const fenceX = W / 2;
  const toX = (ex: number) => fenceX + Math.min(ex / (maxEx + 0.5), 1) * ((W - PAD) - fenceX);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full">
      <line x1={PAD} y1={midY} x2={fenceX - PAD} y2={midY} stroke="#475569" strokeWidth="1.5" />
      <rect x={PAD + 10} y={midY - boxH / 2} width={fenceX - PAD - 10 - PAD} height={boxH} fill="#1e293b" stroke="#6366f1" strokeWidth="1.5" rx="3" />
      <line x1={fenceX} y1={midY - 15} x2={fenceX} y2={midY + 15} stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="3,3" />
      {candidates.map((c, i) => {
        const ex = typeof c.explain === 'object' ? Math.abs(Number((c.explain as AnomalyExplain).metric ?? 0)) : 0.5;
        const x = toX(ex); const jitter = ((i % 3) - 1) * 6;
        return <circle key={i} cx={x} cy={midY + jitter} r="3.5" fill={sevVariant(c.severity) === 'danger' ? '#ef4444' : '#f59e0b'} stroke="#0d1117" strokeWidth="1" />;
      })}
    </svg>
  );
}

// ── Single row handler ──────────────────────────────────────────────────────
function RowHandler({ entry, decision, onDecide }: {
  entry: RowEntry;
  decision: Decision | null;
  onDecide: (d: Decision) => void;
}) {
  const [open, setOpen] = useState(false);
  const [tab,  setTab]  = useState<'zscore' | 'iqr'>(entry.zscore ? 'zscore' : 'iqr');

  const sev     = sevVariant(entry.maxSeverity);
  const active  = tab === 'zscore' ? entry.zscore : entry.iqr;
  const explain = active && typeof active.explain === 'object' ? active.explain as AnomalyExplain : null;
  const metric  = explain?.metric != null ? Number(explain.metric) : null;
  const decided = decision ?? null;

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden transition-all',
      decided          ? 'border-border/50 opacity-80'           :
      sev === 'danger' ? 'border-danger/40 bg-danger/5'          :
      sev === 'warning'? 'border-warning/30 bg-warning/5'        :
                         'border-border bg-surface',
    )}>
      <button type="button" onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-black/5 transition-colors">
        <div className={cn('w-2 h-2 rounded-full shrink-0',
          sev === 'danger' ? 'bg-danger' : sev === 'warning' ? 'bg-warning' : 'bg-text-muted')} />

        <div className="flex-1 flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0 text-xs">
          <span className="font-mono font-semibold text-text">Row {entry.row}</span>
          <span className="text-text-muted">
            value: <span className="font-mono font-semibold text-text">{String(entry.value ?? 'null')}</span>
          </span>

          {/* Inline Z + IQR metrics */}
          {entry.zscore && (
            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold border border-indigo-400/30 bg-indigo-500/10 text-indigo-300">
              <TrendingUp className="h-2.5 w-2.5" />
              z={Math.abs(Number((entry.zscore.explain as AnomalyExplain | null)?.metric ?? 0)).toFixed(2)}
            </span>
          )}
          {entry.iqr && (
            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold border border-amber-400/30 bg-amber-500/10 text-amber-300">
              <Zap className="h-2.5 w-2.5" />
              iqr×{Math.abs(Number((entry.iqr.explain as AnomalyExplain | null)?.metric ?? 0)).toFixed(2)}
            </span>
          )}

          <Badge variant={sev} className="text-[10px]">{(entry.maxSeverity ?? '').toUpperCase()}</Badge>
        </div>

        {/* Decision chip shown in trigger */}
        {decided ? (
          <span className={cn('shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold border',
            DECISIONS.find(d => d.value === decided)?.colorActive)}>
            ✓ {DECISIONS.find(d => d.value === decided)?.short}
          </span>
        ) : (
          <span className="shrink-0 text-[10px] text-text-muted italic">
            Rec: {DECISIONS.find(d => d.value === entry.recommended)?.short}
          </span>
        )}
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-muted" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-text-muted" />}
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-border/30">
          {/* Method tabs */}
          <div className="flex items-center gap-2 mt-3">
            {entry.zscore && (
              <button type="button" onClick={() => setTab('zscore')}
                className={cn('flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all',
                  tab === 'zscore' ? 'bg-indigo-600 text-white border-indigo-600' : 'border-indigo-400/30 text-indigo-400 hover:bg-indigo-500/10')}>
                <TrendingUp className="h-3 w-3" />
                Z-Score · {Math.abs(Number((entry.zscore.explain as AnomalyExplain | null)?.metric ?? 0)).toFixed(3)}
              </button>
            )}
            {entry.iqr && (
              <button type="button" onClick={() => setTab('iqr')}
                className={cn('flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all',
                  tab === 'iqr' ? 'bg-amber-500 text-white border-amber-500' : 'border-amber-400/30 text-amber-400 hover:bg-amber-500/10')}>
                <Zap className="h-3 w-3" />
                IQR ×{Math.abs(Number((entry.iqr.explain as AnomalyExplain | null)?.metric ?? 0)).toFixed(3)}
              </button>
            )}
            {entry.zscore && entry.iqr
              ? <span className="ml-auto text-[10px] text-warning">Both methods agree</span>
              : <span className="ml-auto text-[10px] text-text-muted">{entry.zscore ? 'Z-Score only' : 'IQR only'}</span>}
          </div>

          {/* Stats + explain for active method */}
          {active && (
            <div className="space-y-2.5">
              <div className="grid grid-cols-4 gap-2">
                {[
                  { l: 'Row',        v: String(active.row) },
                  { l: 'Value',      v: String(active.value ?? 'null') },
                  { l: 'Confidence', v: `${(active.confidence * 100).toFixed(0)}%` },
                  { l: 'Severity',   v: (active.severity ?? '—').toUpperCase() },
                ].map(({ l, v }) => (
                  <div key={l} className="rounded-lg border border-border p-2 bg-surface">
                    <p className="text-[9px] uppercase text-text-muted">{l}</p>
                    <p className="font-mono font-semibold text-xs text-text mt-0.5">{v}</p>
                  </div>
                ))}
              </div>
              <div className="h-1.5 rounded-full bg-border overflow-hidden">
                <div className={cn('h-full rounded-full', active.confidence >= 0.8 ? 'bg-danger' : active.confidence >= 0.5 ? 'bg-warning' : 'bg-text-muted')}
                  style={{ width: `${active.confidence * 100}%` }} />
              </div>
              {explain && (
                <div className="flex items-start gap-2 rounded-lg bg-[#0d1117] border border-border/40 p-2.5 text-xs">
                  <Info className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
                  <div className="text-slate-400 flex flex-wrap gap-3">
                    {tab === 'zscore' && metric != null && (
                      <><span>|z| = <strong className="text-slate-200 font-mono">{metric.toFixed(3)}</strong></span>
                      <span>{metric >= 3 ? '→ beyond 3σ (extreme)' : '→ 2–3σ warning zone'}</span></>
                    )}
                    {tab === 'iqr' && metric != null && (
                      <><span>IQR excess = <strong className="text-slate-200 font-mono">{metric.toFixed(3)}×</strong></span>
                      <span>{metric > 1.5 ? '→ far beyond outer fence' : '→ beyond fence'}</span></>
                    )}
                    {explain.isolation_forest && <span className="text-amber-300">+ Isolation Forest</span>}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Decision chips — recommended pre-highlighted */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-xs font-semibold text-text">Action for Row {entry.row}</p>
              {!decided && (
                <button type="button" onClick={() => onDecide(entry.recommended)}
                  className="text-[10px] text-primary hover:underline flex items-center gap-0.5">
                  <Wand2 className="h-3 w-3" />Apply recommended ({DECISIONS.find(d => d.value === entry.recommended)?.label})
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {DECISIONS.map(({ value, label, colorActive, colorIdle }) => (
                <button key={value} type="button" onClick={() => onDecide(value)}
                  className={cn('px-2.5 py-1 rounded-lg text-xs font-medium border transition-all',
                    decided === value ? colorActive : colorIdle)}>
                  {decided === value && '✓ '}{label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Severity group with bulk actions ────────────────────────────────────────
function SeverityGroup({
  label, variant, entries, decisions, onDecideAll, children,
}: {
  label: string;
  variant: 'danger' | 'warning' | 'muted';
  entries: RowEntry[];
  decisions: Record<number, Decision>;
  onDecideAll: (d: Decision) => void;
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const doneCount = entries.filter(e => decisions[e.row] != null).length;
  const allDone = doneCount === entries.length;

  return (
    <div className={cn('rounded-xl border overflow-hidden',
      variant === 'danger'  ? 'border-danger/30'  :
      variant === 'warning' ? 'border-warning/30' : 'border-border')}>
      {/* Group header */}
      <div className={cn('flex items-center justify-between gap-3 px-4 py-2.5',
        variant === 'danger'  ? 'bg-danger/10'  :
        variant === 'warning' ? 'bg-warning/10' : 'bg-surface')}>
        <button type="button" onClick={() => setCollapsed(c => !c)}
          className="flex items-center gap-2 flex-1 min-w-0">
          {collapsed ? <ChevronRight className="h-3.5 w-3.5 text-text-muted" /> : <ChevronDown className="h-3.5 w-3.5 text-text-muted" />}
          <Badge variant={variant}>{label}</Badge>
          <span className="text-xs text-text-muted">{entries.length} row{entries.length > 1 ? 's' : ''}</span>
          {allDone && <Badge variant="success" className="text-[10px]">All decided</Badge>}
          {!allDone && doneCount > 0 && <span className="text-[10px] text-text-muted">{doneCount}/{entries.length} decided</span>}
        </button>

        {/* Bulk action buttons */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[10px] text-text-muted hidden sm:block">Apply to all:</span>
          {DECISIONS.filter(d => d.value !== 'keep' && d.value !== 'mark_valid').map(({ value, short, colorIdle }) => (
            <button key={value} type="button" onClick={() => onDecideAll(value)}
              className={cn('px-2 py-0.5 rounded text-[10px] font-semibold border transition-all', colorIdle)}>
              {short}
            </button>
          ))}
        </div>
      </div>

      {!collapsed && <div className="p-3 space-y-2">{children}</div>}
    </div>
  );
}

// ── Main ────────────────────────────────────────────────────────────────────
export default function AnomalyPanel({
  column,
  results,
  className,
  decisions: controlledDecisions,
  onDecisionsChange,
}: Props) {
  const [internalDecisions, setInternalDecisions] = useState<Record<number, Decision>>({});
  const [filter, setFilter] = useState<'all' | 'undecided' | 'decided'>('all');

  const decisions = controlledDecisions ?? internalDecisions;
  const setDecisions = (updater: Record<number, Decision> | ((prev: Record<number, Decision>) => Record<number, Decision>)) => {
    const next = typeof updater === 'function' ? updater(decisions) : updater;
    if (onDecisionsChange) onDecisionsChange(next);
    else setInternalDecisions(next);
  };

  const allCandidates = (
    (results.phase3 as { anomaly_candidates?: AnomalyCandidate[] } | undefined)
      ?.anomaly_candidates ?? []
  ).filter(c => c.column === column);

  const zscoreCandidates = allCandidates.filter(c => (c.method ?? '').toUpperCase().includes('Z'));
  const iqrCandidates    = allCandidates.filter(c => (c.method ?? '').toUpperCase() === 'IQR');

  const rowEntries = useMemo((): RowEntry[] => {
    const map = new Map<number, Omit<RowEntry, 'recommended'>>();
    for (const c of zscoreCandidates) map.set(c.row, { row: c.row, value: c.value, zscore: c, iqr: null, maxSeverity: c.severity });
    for (const c of iqrCandidates) {
      const ex = map.get(c.row);
      if (ex) { ex.iqr = c; if (sevOrder(c.severity) < sevOrder(ex.maxSeverity)) ex.maxSeverity = c.severity; }
      else map.set(c.row, { row: c.row, value: c.value, zscore: null, iqr: c, maxSeverity: c.severity });
    }
    return [...map.values()]
      .map(e => ({ ...e, recommended: deriveRecommendation(e) }))
      .sort((a, b) => sevOrder(a.maxSeverity) - sevOrder(b.maxSeverity) || a.row - b.row);
  }, [zscoreCandidates, iqrCandidates]);

  const perCol = ((results.phase3 as { anomaly_results?: Record<string, unknown>[] } | undefined)
    ?.anomaly_results ?? []).find(r => (r as { column?: string }).column === column) as Record<string, unknown> | undefined;
  const distHint = (perCol?.distribution_hint as Record<string, number | undefined> | undefined) ?? {};
  const recommended = String(perCol?.recommended ?? '').toUpperCase();
  const zConf = Number(perCol?.z_score_confidence ?? 0);
  const iqrConf = Number(perCol?.iqr_confidence ?? 0);

  const decideRow  = (row: number, d: Decision) => setDecisions(p => ({ ...p, [row]: d }));
  const decideGroup = (rows: RowEntry[], d: Decision) =>
    setDecisions(p => { const n = { ...p }; rows.forEach(r => { n[r.row] = d; }); return n; });
  const applyAllRecommended = () =>
    setDecisions(p => { const n = { ...p }; rowEntries.forEach(r => { n[r.row] = r.recommended; }); return n; });

  const decidedCount = Object.keys(decisions).length;
  const totalCount   = rowEntries.length;
  const allDone      = decidedCount === totalCount && totalCount > 0;

  const extremeRows = rowEntries.filter(r => sevVariant(r.maxSeverity) === 'danger');
  const mediumRows  = rowEntries.filter(r => sevVariant(r.maxSeverity) === 'warning');
  const lowRows     = rowEntries.filter(r => sevVariant(r.maxSeverity) === 'muted');

  const applyFilter = (rows: RowEntry[]) =>
    filter === 'undecided' ? rows.filter(r => !decisions[r.row]) :
    filter === 'decided'   ? rows.filter(r =>  decisions[r.row]) : rows;

  if (rowEntries.length === 0) {
    return (
      <Card className={cn('border-success/30 bg-success/5', className)}>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-6 w-6 text-success shrink-0" />
          <div>
            <p className="font-semibold text-text">No anomalies detected</p>
            <p className="text-sm text-text-muted mt-0.5">Z-Score and IQR found no outliers in <strong>{column}</strong>.</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <div className={cn('space-y-4', className)}>

      {/* ── Smart recommendation banner ── */}
      <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <Wand2 className="h-4 w-4 text-primary shrink-0" />
            <div>
              <p className="font-semibold text-text text-sm">Smart recommendations ready</p>
              <p className="text-xs text-text-muted mt-0.5">
                Based on confidence scores and both detection methods.
                {recommended && <> Recommended method: <strong>{recommended}</strong>.</>}
              </p>
            </div>
          </div>
          <button type="button" onClick={applyAllRecommended}
            className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-primary text-white border border-primary hover:bg-primary/90 transition-all">
            <Wand2 className="h-3.5 w-3.5" />Apply all ({totalCount})
          </button>
        </div>

        {/* Recommendation breakdown */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {DECISIONS.map(({ value, label, colorActive }) => {
            const count = rowEntries.filter(r => r.recommended === value).length;
            if (!count) return null;
            return (
              <div key={value} className="rounded-lg border border-border p-2.5 bg-surface/50">
                <p className="text-[10px] text-text-muted uppercase tracking-wide">Rec: {label}</p>
                <p className="font-mono font-bold text-sm text-text mt-0.5">{count} row{count > 1 ? 's' : ''}</p>
                <button type="button" onClick={() => {
                    const targets = rowEntries.filter(r => r.recommended === value);
                    decideGroup(targets, value);
                  }}
                  className={cn('mt-1.5 w-full px-2 py-0.5 rounded text-[10px] font-semibold border transition-all', colorActive)}>
                  Apply
                </button>
              </div>
            );
          })}
        </div>

        {/* Distribution stats */}
        {Object.keys(distHint).length > 0 && (
          <div className="flex flex-wrap gap-4 text-xs mt-3 pt-3 border-t border-border/30">
            {distHint.skewness      != null && <span className="text-text-muted">Skewness: <strong className="font-mono text-text">{Number(distHint.skewness).toFixed(3)}</strong></span>}
            {distHint.normality_score != null && <span className="text-text-muted">Normality: <strong className="font-mono text-text">{(Number(distHint.normality_score) * 100).toFixed(0)}%</strong></span>}
            <span className="text-text-muted">Z-Score fit: <strong className="font-mono text-text">{(zConf * 100).toFixed(0)}%</strong></span>
            <span className="text-text-muted">IQR fit: <strong className="font-mono text-text">{(iqrConf * 100).toFixed(0)}%</strong></span>
          </div>
        )}
      </div>

      {/* ── Distribution charts ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="rounded-lg border border-border/40 bg-[#0d1117] overflow-hidden">
          <div className="px-3 py-1.5 border-b border-border/20 flex items-center gap-1.5">
            <TrendingUp className="h-3 w-3 text-indigo-400" />
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
              Z-Score · {zscoreCandidates.length} flagged
            </span>
          </div>
          <MiniCurve candidates={zscoreCandidates} />
        </div>
        <div className="rounded-lg border border-border/40 bg-[#0d1117] overflow-hidden">
          <div className="px-3 py-1.5 border-b border-border/20 flex items-center gap-1.5">
            <Zap className="h-3 w-3 text-amber-400" />
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
              IQR · {iqrCandidates.length} flagged
            </span>
          </div>
          <MiniBoxPlot candidates={iqrCandidates} />
        </div>
      </div>

      {/* ── Progress + filter ── */}
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-text-muted">Progress</span>
            <span className="font-mono font-semibold text-text">{decidedCount} / {totalCount}</span>
          </div>
          <div className="h-1.5 rounded-full bg-border overflow-hidden">
            <div className="h-full rounded-full bg-success transition-all" style={{ width: `${(decidedCount / totalCount) * 100}%` }} />
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Filter className="h-3.5 w-3.5 text-text-muted" />
          {(['all', 'undecided', 'decided'] as const).map(f => (
            <button key={f} type="button" onClick={() => setFilter(f)}
              className={cn('px-2 py-1 rounded text-[10px] font-medium border transition-all capitalize',
                filter === f ? 'bg-accent text-white border-accent' : 'border-border text-text-muted hover:bg-border/50')}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* ── Grouped severity rows ── */}
      <div className="space-y-3">
        {extremeRows.length > 0 && (
          <SeverityGroup label="EXTREME" variant="danger" entries={extremeRows} decisions={decisions} onDecideAll={d => decideGroup(extremeRows, d)}>
            {applyFilter(extremeRows).map(e => (
              <RowHandler key={e.row} entry={e} decision={decisions[e.row] ?? null} onDecide={d => decideRow(e.row, d)} />
            ))}
            {applyFilter(extremeRows).length === 0 && <p className="text-xs text-text-muted text-center py-2">No rows match filter.</p>}
          </SeverityGroup>
        )}
        {mediumRows.length > 0 && (
          <SeverityGroup label="MEDIUM" variant="warning" entries={mediumRows} decisions={decisions} onDecideAll={d => decideGroup(mediumRows, d)}>
            {applyFilter(mediumRows).map(e => (
              <RowHandler key={e.row} entry={e} decision={decisions[e.row] ?? null} onDecide={d => decideRow(e.row, d)} />
            ))}
            {applyFilter(mediumRows).length === 0 && <p className="text-xs text-text-muted text-center py-2">No rows match filter.</p>}
          </SeverityGroup>
        )}
        {lowRows.length > 0 && (
          <SeverityGroup label="LOW" variant="muted" entries={lowRows} decisions={decisions} onDecideAll={d => decideGroup(lowRows, d)}>
            {applyFilter(lowRows).map(e => (
              <RowHandler key={e.row} entry={e} decision={decisions[e.row] ?? null} onDecide={d => decideRow(e.row, d)} />
            ))}
            {applyFilter(lowRows).length === 0 && <p className="text-xs text-text-muted text-center py-2">No rows match filter.</p>}
          </SeverityGroup>
        )}
      </div>

      {/* ── All done ── */}
      {allDone && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-success/40 bg-success/5">
          <CheckCircle2 className="h-5 w-5 text-success shrink-0" />
          <div>
            <p className="font-semibold text-text text-sm">All {totalCount} anomalies reviewed</p>
            <p className="text-xs text-text-muted mt-0.5">
              {Object.values(decisions).filter(d => d === 'remove_value').length} remove value ·{' '}
              {Object.values(decisions).filter(d => d === 'remove_row').length} remove row ·{' '}
              {Object.values(decisions).filter(d => d === 'treat_missing').length} treat as missing ·{' '}
              {Object.values(decisions).filter(d => d === 'keep' || d === 'mark_valid').length} kept
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
