'use client';

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from 'react';
import { Loader2, Save, TrendingUp } from 'lucide-react';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import AnomalyDetailDrawer from '@/components/analysis/AnomalyDetailDrawer';
import type {
  AnalysisResult,
  AnomalyCandidate,
  AnomalyColumnBlock,
  OutlierRowDecision,
} from '@/lib/api';
import { analysisApi } from '@/lib/api';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/cn';

type UiDecision = 'KEEP' | 'DELETE_ROW' | 'DELETE_VALUE' | 'EDIT_VALUE' | 'NORMALIZE';

const DECISION_OPTIONS: { value: UiDecision; label: string; api: OutlierRowDecision }[] = [
  { value: 'KEEP', label: 'Keep', api: 'KEEP' },
  { value: 'DELETE_ROW', label: 'Delete row', api: 'DELETE_ROW' },
  { value: 'DELETE_VALUE', label: 'Convert to missing', api: 'DELETE_VALUE' },
  { value: 'EDIT_VALUE', label: 'Ignore', api: 'EDIT_VALUE' },
  { value: 'NORMALIZE', label: 'Normalize', api: 'NORMALIZE' },
];

const SEVERITY_ORDER = ['EXTREME', 'HIGH', 'MEDIUM', 'LOW'] as const;

export interface AnomalyReviewTableHandle {
  saveDecisions: () => Promise<{ saved: number }>;
  allReviewed: () => boolean;
}

interface Props {
  column: string;
  analysisId: number;
  results: AnalysisResult;
  block?: AnomalyColumnBlock;
  candidates: AnomalyCandidate[];
  domain?: string;
  onSaved?: () => void;
  onProgress?: (reviewed: number, total: number) => void;
}

function sevKey(s: string | undefined): string {
  return (s ?? 'LOW').toUpperCase();
}

function rowKey(c: AnomalyCandidate): string {
  return `${c.column}-${c.row}`;
}

function uiFromApi(d: string): UiDecision {
  const u = d.toUpperCase();
  if (u === 'DELETE_VALUE') return 'DELETE_VALUE';
  if (u === 'DELETE_ROW') return 'DELETE_ROW';
  if (u === 'EDIT_VALUE') return 'EDIT_VALUE';
  if (u === 'NORMALIZE') return 'NORMALIZE';
  return 'KEEP';
}

const AnomalyReviewTable = forwardRef<AnomalyReviewTableHandle, Props>(function AnomalyReviewTable(
  { column, analysisId, results, block, candidates, domain, onSaved, onProgress },
  ref,
) {
  const method = String(block?.method_selected ?? 'Z_SCORE').toUpperCase();
  const methodLabel = method === 'IQR' ? 'IQR' : 'Z-Score';
  const gof = block?.goodness_of_fit;

  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [decisionFilter, setDecisionFilter] = useState<string>('all');
  const [decisions, setDecisions] = useState<Record<string, UiDecision>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkDecision, setBulkDecision] = useState<UiDecision>('KEEP');
  const [detail, setDetail] = useState<AnomalyCandidate | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedCount, setSavedCount] = useState(0);

  useEffect(() => {
    analysisApi.getOutlierDecisions(analysisId, column).then((rows) => {
      if (!Array.isArray(rows)) return;
      const loaded: Record<string, UiDecision> = {};
      for (const r of rows as Array<{ row_index: number; decision: string }>) {
        loaded[`${column}-${r.row_index}`] = uiFromApi(r.decision);
      }
      if (Object.keys(loaded).length) setDecisions(loaded);
    }).catch(() => {});
  }, [analysisId, column]);

  const severityCounts = useMemo(() => {
    const counts: Record<string, number> = { EXTREME: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    for (const c of candidates) {
      const k = sevKey(c.severity);
      if (k in counts) counts[k] += 1;
      else counts.LOW += 1;
    }
    return counts;
  }, [candidates]);

  const filtered = useMemo(() => {
    return candidates.filter((c) => {
      const sev = sevKey(c.severity);
      if (severityFilter !== 'all' && sev !== severityFilter) return false;
      const key = rowKey(c);
      const decided = Boolean(decisions[key]);
      const d = decisions[key];
      if (decisionFilter === 'undecided' && decided) return false;
      if (decisionFilter === 'reviewed' && !decided) return false;
      if (decisionFilter === 'accepted' && d !== 'KEEP') return false;
      if (decisionFilter === 'removed' && d !== 'DELETE_ROW') return false;
      if (decisionFilter === 'missing' && d !== 'DELETE_VALUE') return false;
      if (decisionFilter === 'ignored' && d !== 'EDIT_VALUE') return false;
      return true;
    });
  }, [candidates, severityFilter, decisionFilter, decisions]);

  const filteredKeys = useMemo(() => filtered.map(rowKey), [filtered]);
  const reviewedCount = candidates.filter((c) => decisions[rowKey(c)]).length;
  const totalCount = candidates.length;
  const progressPct = totalCount ? Math.round((reviewedCount / totalCount) * 100) : 100;

  useEffect(() => {
    onProgress?.(reviewedCount, totalCount);
  }, [reviewedCount, totalCount, onProgress]);

  const buildPayload = (keys?: string[]) =>
    candidates
      .filter((c) => !keys || keys.includes(rowKey(c)))
      .filter((c) => decisions[rowKey(c)])
      .map((c) => ({
        row_index: c.row,
        method: c.method,
        methodology: methodLabel,
        severity: c.severity,
        confidence: c.confidence,
        decision: decisions[rowKey(c)],
        old_value: c.value as string | number | null,
        new_value: null,
      }));

  const handleSave = async () => {
    const payload = buildPayload();
    if (!payload.length) {
      toast.error('No decisions to save');
      return { saved: 0 };
    }
    setSaving(true);
    try {
      const res = await analysisApi.saveOutlierDecisions(analysisId, column, payload);
      const count = Number(res.saved ?? payload.length);
      if (res.success === false) throw new Error('Save not confirmed');
      setSavedCount(count);
      toast.success(`Saved ${count} anomaly decision(s)`);
      onSaved?.();
      return { saved: count };
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save');
      throw err;
    } finally {
      setSaving(false);
    }
  };

  useImperativeHandle(ref, () => ({
    saveDecisions: handleSave,
    allReviewed: () => totalCount === 0 || reviewedCount >= totalCount,
  }));

  const applyBulk = (keys: string[], decision: UiDecision) => {
    if (!keys.length) return;
    setDecisions((prev) => {
      const next = { ...prev };
      keys.forEach((k) => { next[k] = decision; });
      return next;
    });
    toast.success(`Applied to ${keys.length} row(s)`);
  };

  const clusterName =
    results.clusters?.find((cl) =>
      Array.isArray(cl.columns) && (cl.columns as string[]).includes(column),
    )?.domain as string | undefined;

  if (!totalCount) return null;

  return (
    <>
      <Card title={`Anomaly review (${totalCount})`} description={`${methodLabel} detections for ${column}`}>
        {gof && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4 text-xs">
            {[
              { l: 'Mean', v: gof.mean },
              { l: 'Median', v: gof.median },
              { l: 'Std', v: gof.standard_deviation },
              { l: 'Anomalies', v: totalCount },
            ].map(({ l, v }) => (
              <div key={l} className="rounded border border-border p-2">
                <p className="text-text-muted uppercase text-[10px]">{l}</p>
                <p className="font-mono font-semibold">{v != null ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'}</p>
              </div>
            ))}
          </div>
        )}

        <div className="mb-4">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-text-muted">Reviewed: {reviewedCount} / {totalCount}</span>
            <span className="font-mono">Remaining: {totalCount - reviewedCount} · {progressPct}%</span>
          </div>
          <div className="h-2 rounded-full bg-border overflow-hidden">
            <div className="h-full bg-success transition-all" style={{ width: `${progressPct}%` }} />
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 mb-3">
          {(['all', ...SEVERITY_ORDER] as const).map((s) => {
            const count = s === 'all' ? totalCount : severityCounts[s] ?? 0;
            if (s !== 'all' && count === 0) return null;
            return (
              <button
                key={s}
                type="button"
                onClick={() => setSeverityFilter(s)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-medium border capitalize',
                  severityFilter === s ? 'bg-accent text-white border-accent' : 'border-border text-text-muted',
                )}
              >
                {s === 'all' ? `All (${count})` : `${s} (${count})`}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap gap-1.5 mb-4">
          {[
            ['all', 'All'],
            ['undecided', 'Undecided'],
            ['reviewed', 'Reviewed'],
            ['accepted', 'Accepted'],
            ['removed', 'Removed'],
            ['missing', 'Missing'],
            ['ignored', 'Ignored'],
          ].map(([v, label]) => (
            <button
              key={v}
              type="button"
              onClick={() => setDecisionFilter(v)}
              className={cn(
                'px-2 py-1 rounded text-[10px] font-medium border',
                decisionFilter === v ? 'bg-primary/10 border-primary text-primary' : 'border-border text-text-muted',
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 mb-4 p-3 rounded-lg bg-border/20 border border-border/60">
          <span className="text-xs text-text-muted">{selected.size} selected</span>
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set(filteredKeys))}>Select all</Button>
          {SEVERITY_ORDER.map((s) => severityCounts[s] > 0 && (
            <Button key={s} variant="ghost" size="sm" onClick={() => {
              const keys = filtered.filter((c) => sevKey(c.severity) === s).map(rowKey);
              setSelected(new Set(keys));
            }}>All {s}</Button>
          ))}
          <Button variant="ghost" size="sm" onClick={() => applyBulk(filteredKeys, 'KEEP')}>Keep all column</Button>
          <Button variant="ghost" size="sm" onClick={() => applyBulk(filteredKeys, 'DELETE_ROW')}>Delete all column</Button>
          <Button variant="ghost" size="sm" onClick={() => applyBulk(filteredKeys, 'DELETE_VALUE')}>Convert all to missing</Button>
          <div className="flex items-center gap-2 ml-auto">
            <select value={bulkDecision} onChange={(e) => setBulkDecision(e.target.value as UiDecision)} className="text-xs rounded border px-2 py-1 bg-surface-card">
              {DECISION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <Button variant="secondary" size="sm" onClick={() => applyBulk([...selected], bulkDecision)} disabled={!selected.size}>Apply</Button>
            <Button variant="secondary" size="sm" onClick={handleSave} disabled={saving} className="gap-1">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {saving ? 'Saving…' : savedCount ? `Saved (${savedCount})` : 'Save decisions'}
            </Button>
          </div>
        </div>

        <div className="overflow-x-auto max-h-[28rem]">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface-card z-10">
              <tr className="border-b border-border text-left text-xs uppercase text-text-muted">
                <th className="pb-2 pr-2 w-8">
                  <input
                    type="checkbox"
                    checked={filteredKeys.length > 0 && filteredKeys.every((k) => selected.has(k))}
                    onChange={(e) => setSelected(e.target.checked ? new Set(filteredKeys) : new Set())}
                    aria-label="Select all"
                  />
                </th>
                <th className="pb-2 pr-3">Row</th>
                <th className="pb-2 pr-3">Value</th>
                <th className="pb-2 pr-3">Severity</th>
                <th className="pb-2 pr-3">Method</th>
                <th className="pb-2">Decision</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => {
                const key = rowKey(c);
                const decision = decisions[key];
                return (
                  <tr
                    key={key}
                    className={cn('border-b border-border/60 cursor-pointer hover:bg-border/20', selected.has(key) && 'bg-accent/5')}
                    onClick={() => setDetail(c)}
                  >
                    <td className="py-2 pr-2" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={selected.has(key)} onChange={() => {
                        setSelected((prev) => {
                          const next = new Set(prev);
                          if (next.has(key)) next.delete(key); else next.add(key);
                          return next;
                        });
                      }} />
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">{c.row}</td>
                    <td className="py-2 pr-3 font-mono text-xs font-medium">{String(c.value ?? '—')}</td>
                    <td className="py-2 pr-3"><Badge variant="warning">{sevKey(c.severity)}</Badge></td>
                    <td className="py-2 pr-3 text-text-muted text-xs">{methodLabel}</td>
                    <td className="py-2" onClick={(e) => e.stopPropagation()}>
                      <select
                        value={decision ?? ''}
                        onChange={(e) => setDecisions((p) => ({ ...p, [key]: e.target.value as UiDecision }))}
                        className="text-xs rounded border px-2 py-1 bg-surface-card min-w-[130px]"
                      >
                        <option value="">Undecided</option>
                        {DECISION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <AnomalyDetailDrawer
        candidate={detail}
        column={column}
        methodLabel={methodLabel}
        domain={domain}
        cluster={clusterName}
        onClose={() => setDetail(null)}
      />
    </>
  );
});

export default AnomalyReviewTable;
