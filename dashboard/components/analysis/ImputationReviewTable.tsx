'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { AnalysisResult } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import {
  resolveImputationBlock,
  resolveImputationCandidate,
  resolveMissingCount,
} from '@/lib/outlierColumnUtils';
import Card from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import ImputationDetailDrawer from '@/components/analysis/ImputationDetailDrawer';
import { cn } from '@/lib/cn';
import { CheckCircle2, Loader2, Save, Info } from 'lucide-react';
import { toast } from '@/lib/toast';

interface Props {
  column: string;
  analysisId: number;
  results: AnalysisResult;
  className?: string;
  onSaved?: () => void;
}

const METHODS = ['mean', 'median', 'mode', 'knn'] as const;
const PAGE_SIZE = 25;
const FETCH_LIMIT = 100;

const METHOD_DESCRIPTIONS: Record<string, string> = {
  mean: 'Replace missing values with the column mean.',
  median: 'Replace with the median — robust to skew and outliers.',
  mode: 'Replace with the most frequent value.',
  knn: 'k-NN imputation using similar rows.',
};

type RowDecision = 'ACCEPT' | 'KEEP_MISSING' | 'REJECT' | 'OVERRIDE';

const DECISION_OPTIONS: { value: RowDecision; label: string }[] = [
  { value: 'ACCEPT', label: 'Accept imputation' },
  { value: 'KEEP_MISSING', label: 'Keep missing' },
  { value: 'REJECT', label: 'Reject row' },
  { value: 'OVERRIDE', label: 'Override value' },
];

type MissingRow = {
  row_index: number;
  missing_column: string;
  original_value: null;
  recommended_value: unknown;
  confidence: number;
  method: string;
  reason: string;
  context: Record<string, unknown>;
};

function formatValue(val: unknown): string {
  if (val === null || val === undefined) return 'NULL';
  if (typeof val === 'number') return Number.isInteger(val) ? String(val) : val.toFixed(2);
  return String(val);
}

export default function ImputationReviewTable({ column, analysisId, results, className, onSaved }: Props) {
  const candidate = resolveImputationCandidate(column, results);
  const block = resolveImputationBlock(column, results);

  const health = results.health as { rows?: number } | undefined;
  const missingCount = resolveMissingCount(column, results);
  const totalRows = health?.rows ?? 0;
  const missingPct = totalRows > 0 ? (missingCount / totalRows) * 100 : 0;

  const methodScores = useMemo(() => {
    const raw = (candidate?.method_scores as Record<string, number> | undefined) ?? {};
    if (Object.keys(raw).length) return raw;
    const fromBlock = block as { mean?: number; median?: number; mode?: number; knn?: number } | undefined;
    if (fromBlock) {
      return {
        mean: fromBlock.mean ?? 0,
        median: fromBlock.median ?? 0,
        mode: fromBlock.mode ?? 0,
        knn: fromBlock.knn ?? 0,
      };
    }
    return {};
  }, [candidate, block]);

  const recommended = String(candidate?.recommended_method ?? block?.recommended ?? 'median').toLowerCase();
  const confidence = Number(candidate?.confidence ?? block?.confidence ?? 0);

  const scoresList = useMemo(() => {
    const ranked = (block?.ranked_methods as Array<{ method: string; score: number; reason?: string }>) ?? [];
    if (ranked.length) {
      return ranked.map((r) => ({
        method: String(r.method).toLowerCase(),
        score: Number(r.score ?? methodScores[String(r.method).toLowerCase()] ?? 0),
        reason: r.reason,
      }));
    }
    return METHODS.map((m) => ({
      method: m,
      score: Number(methodScores[m] ?? 0),
      reason: METHOD_DESCRIPTIONS[m],
    })).sort((a, b) => b.score - a.score);
  }, [block, methodScores]);

  const [selectedMethod, setSelectedMethod] = useState<string>(recommended);
  const [missingRows, setMissingRows] = useState<MissingRow[]>([]);
  const [rowDecisions, setRowDecisions] = useState<Record<number, RowDecision>>({});
  const [overrideValues, setOverrideValues] = useState<Record<number, string>>({});
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());
  const [bulkDecision, setBulkDecision] = useState<RowDecision>('ACCEPT');
  const [page, setPage] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const loadAllMissingRows = useCallback(async (method: string) => {
    setLoadingRows(true);
    setLoadError(null);
    try {
      let offset = 0;
      let total = missingCount;
      const all: MissingRow[] = [];
      do {
        const payload = await analysisApi.getImputationMissingRows(analysisId, column, {
          method,
          offset,
          limit: FETCH_LIMIT,
        });
        total = payload.total_missing ?? missingCount;
        all.push(...(payload.rows ?? []));
        offset += FETCH_LIMIT;
      } while (offset < total);
      setMissingRows(all);
      setRowDecisions((prev) => {
        const next = { ...prev };
        for (const row of all) {
          if (!next[row.row_index]) next[row.row_index] = 'ACCEPT';
        }
        return next;
      });
      if (total > 0 && all.length === 0) {
        setLoadError('Could not load row context for missing values. Check dataset storage or save column-level decision.');
      }
    } catch (err) {
      setMissingRows([]);
      setLoadError(err instanceof Error ? err.message : 'Failed to load missing rows');
    } finally {
      setLoadingRows(false);
    }
  }, [analysisId, column, missingCount]);

  useEffect(() => {
    if (missingCount === 0) return;
    setPage(0);
    setSaved(false);
    void loadAllMissingRows(selectedMethod);
  }, [missingCount, selectedMethod, loadAllMissingRows]);

  const pageRows = useMemo(() => {
    const start = page * PAGE_SIZE;
    return missingRows.slice(start, start + PAGE_SIZE);
  }, [missingRows, page]);

  const totalPages = Math.max(1, Math.ceil(missingRows.length / PAGE_SIZE));
  const reviewedCount = missingRows.filter((r) => rowDecisions[r.row_index]).length;

  const applyBulk = (rowIndexes: number[], decision: RowDecision) => {
    if (!rowIndexes.length) return;
    setRowDecisions((prev) => {
      const next = { ...prev };
      rowIndexes.forEach((idx) => { next[idx] = decision; });
      return next;
    });
    toast.success(`Applied to ${rowIndexes.length} row(s)`);
  };

  const buildSavePayload = () => {
    if (missingRows.length === 0) {
      return [{
        column,
        method: selectedMethod,
        decision: 'ACCEPT',
        confidence,
      }];
    }
    return missingRows.map((row) => {
      const decision = rowDecisions[row.row_index] ?? 'ACCEPT';
      const base = {
        row_index: row.row_index,
        column,
        method: selectedMethod,
        decision,
        original_value: null,
        confidence: row.confidence,
      };
      if (decision === 'OVERRIDE') {
        return {
          ...base,
          imputed_value: overrideValues[row.row_index] ?? row.recommended_value,
        };
      }
      if (decision === 'ACCEPT') {
        return { ...base, imputed_value: row.recommended_value };
      }
      return base;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const decisions = buildSavePayload();
      const res = await analysisApi.saveImputationDecisions(analysisId, column, selectedMethod, decisions);
      if (res.success === false) throw new Error('Save failed');
      setSaved(true);
      toast.success(`Saved ${decisions.length} missing-value decisions for ${column}`);
      onSaved?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!candidate && missingCount === 0) {
    return (
      <Card className={cn('border-success/30 bg-success/5', className)}>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-6 w-6 text-success shrink-0" />
          <div>
            <p className="font-semibold text-text">✓ No missing values</p>
            <p className="text-sm text-text-muted mt-0.5">Column automatically approved.</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card title="Missing value intelligence" className={className}>
      <div className="grid grid-cols-3 gap-3 mb-4 text-sm">
        <div className="rounded border p-3"><p className="text-xs text-text-muted">Missing</p><p className="text-xl font-bold">{missingCount}</p></div>
        <div className="rounded border p-3"><p className="text-xs text-text-muted">Ratio</p><p className="text-xl font-bold">{missingPct.toFixed(1)}%</p></div>
        <div className="rounded border p-3"><p className="text-xs text-text-muted">Confidence</p><p className="text-xl font-bold">{(confidence * 100).toFixed(0)}%</p></div>
      </div>

      <div className="space-y-2 mb-4">
        {scoresList.map((s) => {
          const isRec = s.method === recommended;
          const isSel = selectedMethod === s.method;
          return (
            <button key={s.method} type="button" onClick={() => setSelectedMethod(s.method)}
              className={cn('w-full text-left rounded-xl border p-3', isSel ? 'border-accent bg-accent/10' : 'border-border hover:bg-border/30')}>
              <div className="flex justify-between items-center capitalize">
                <span className="font-semibold">{s.method}</span>
                <div className="flex gap-2">
                  {isRec && <Badge variant="success">Recommended</Badge>}
                  <Badge variant={s.score >= 0.8 ? 'success' : s.score >= 0.5 ? 'warning' : 'danger'}>
                    {(s.score * 100).toFixed(0)}%
                  </Badge>
                </div>
              </div>
              <p className="text-xs text-text-muted mt-1">{s.reason ?? METHOD_DESCRIPTIONS[s.method]}</p>
            </button>
          );
        })}
        <Button variant="ghost" size="sm" onClick={() => setDrawerOpen(true)}>Explain methods</Button>
      </div>

      {loadError && (
        <Alert variant="warning" title="Row context unavailable" className="mb-4">
          {loadError} You can still save a column-level decision using the button below.
        </Alert>
      )}

      <div className="mb-4">
        <div className="flex justify-between text-xs mb-1">
          <span className="text-text-muted">
            Missing rows reviewed: {reviewedCount} / {missingRows.length || missingCount}
          </span>
          {missingRows.length > PAGE_SIZE && (
            <span className="font-mono">Page {page + 1} / {totalPages}</span>
          )}
        </div>
        {loadingRows ? (
          <div className="space-y-2" aria-busy="true" aria-label="Loading missing rows">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 mb-3 p-3 rounded-lg bg-border/20 border border-border/60">
              <span className="text-xs text-text-muted">{selectedRows.size} selected</span>
              <Button variant="ghost" size="sm" onClick={() => setSelectedRows(new Set(pageRows.map((r) => r.row_index)))}>
                Select page
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setSelectedRows(new Set(missingRows.map((r) => r.row_index)))}>
                Select all
              </Button>
              <Button variant="ghost" size="sm" onClick={() => applyBulk(missingRows.map((r) => r.row_index), 'ACCEPT')}>
                Accept all recommended
              </Button>
              <Button variant="ghost" size="sm" onClick={() => applyBulk(missingRows.map((r) => r.row_index), 'KEEP_MISSING')}>
                Keep all missing
              </Button>
              <Button variant="ghost" size="sm" onClick={() => applyBulk(missingRows.map((r) => r.row_index), 'REJECT')}>
                Reject all rows
              </Button>
              <div className="flex items-center gap-2 ml-auto">
                <select
                  value={bulkDecision}
                  onChange={(e) => setBulkDecision(e.target.value as RowDecision)}
                  className="text-xs rounded border px-2 py-1 bg-surface-card"
                >
                  {DECISION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => applyBulk([...selectedRows], bulkDecision)}
                  disabled={!selectedRows.size}
                >
                  Apply to selected
                </Button>
              </div>
            </div>

            <div className="overflow-x-auto max-h-[32rem] space-y-3">
              {pageRows.map((row) => {
                const decision = rowDecisions[row.row_index] ?? 'ACCEPT';
                return (
                  <div key={row.row_index} className="rounded-lg border border-border/60 p-3 text-xs">
                    <div className="flex items-start gap-2 mb-2">
                      <input
                        type="checkbox"
                        checked={selectedRows.has(row.row_index)}
                        onChange={() => {
                          setSelectedRows((prev) => {
                            const n = new Set(prev);
                            if (n.has(row.row_index)) n.delete(row.row_index);
                            else n.add(row.row_index);
                            return n;
                          });
                        }}
                      />
                      <div className="flex-1">
                        <p className="font-mono font-semibold text-sm">Row {row.row_index}</p>
                        <p className="text-text-muted mt-0.5">
                          {column} = <strong>NULL</strong>
                          {' → '}
                          Recommended: <strong>{formatValue(row.recommended_value)}</strong>
                          {' · '}
                          Confidence: {(row.confidence * 100).toFixed(0)}%
                        </p>
                      </div>
                      <select
                        value={decision}
                        onChange={(e) => setRowDecisions((p) => ({
                          ...p,
                          [row.row_index]: e.target.value as RowDecision,
                        }))}
                        className="text-xs rounded border px-2 py-1 bg-surface-card min-w-[140px]"
                      >
                        {DECISION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </div>
                    {decision === 'OVERRIDE' && (
                      <input
                        type="text"
                        value={overrideValues[row.row_index] ?? formatValue(row.recommended_value)}
                        onChange={(e) => setOverrideValues((p) => ({ ...p, [row.row_index]: e.target.value }))}
                        className="w-full max-w-xs text-xs rounded border px-2 py-1 mb-2 bg-surface-card"
                        placeholder="Override value"
                      />
                    )}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-text-muted mb-2">
                      {Object.entries(row.context ?? {}).map(([col, val]) => (
                        <span key={col}>{col} = {formatValue(val)}</span>
                      ))}
                    </div>
                    <p className="text-text-muted">
                      Method: <span className="capitalize">{row.method}</span>
                      {' · '}
                      Reason: {row.reason}
                    </p>
                  </div>
                );
              })}
              {!pageRows.length && !loadingRows && (
                <p className="text-sm text-text-muted">No row details loaded. Save a column-level decision to mark this column reviewed.</p>
              )}
            </div>

            {totalPages > 1 && (
              <div className="flex gap-2 mt-3">
                <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button variant="ghost" size="sm" disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            )}
          </>
        )}
      </div>

      {missingPct > 30 && (
        <div className="flex items-start gap-2 rounded-lg bg-warning/10 border border-warning/30 p-3 text-sm mb-4">
          <Info className="h-4 w-4 text-warning shrink-0 mt-0.5" />
          <p className="text-text-muted">High missing ratio — review carefully before imputing.</p>
        </div>
      )}

      <Button disabled={!selectedMethod || saving} onClick={handleSave} className="gap-2">
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        {saved ? 'Saved' : saving ? 'Saving…' : `Save ${missingRows.length || 1} decisions: ${selectedMethod}`}
      </Button>

      <ImputationDetailDrawer
        open={drawerOpen}
        column={column}
        method={selectedMethod}
        confidence={confidence}
        reason={scoresList.find((s) => s.method === recommended)?.reason}
        scores={scoresList}
        onClose={() => setDrawerOpen(false)}
      />
    </Card>
  );
}
