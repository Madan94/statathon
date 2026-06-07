'use client';

import { useMemo, useState } from 'react';
import type { AnalysisResult, ImputationCandidate } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import ImputationDetailDrawer from '@/components/analysis/ImputationDetailDrawer';
import { cn } from '@/lib/cn';
import { CheckCircle2, Save, Info } from 'lucide-react';
import { toast } from '@/lib/toast';

interface Props {
  column: string;
  analysisId: number;
  results: AnalysisResult;
  className?: string;
  onSaved?: () => void;
}

const METHODS = ['mean', 'median', 'mode', 'knn'] as const;

const METHOD_DESCRIPTIONS: Record<string, string> = {
  mean: 'Replace missing values with the column mean.',
  median: 'Replace with the median — robust to skew and outliers.',
  mode: 'Replace with the most frequent value.',
  knn: 'k-NN imputation using similar rows.',
};

type ConfidenceFilter = 'all' | 'high' | 'medium' | 'low';

function bandOf(score: number): ConfidenceFilter {
  if (score >= 0.8) return 'high';
  if (score >= 0.5) return 'medium';
  return 'low';
}

export default function ImputationReviewTable({ column, analysisId, results, className, onSaved }: Props) {
  const phase3 = results.phase3 as {
    imputation_candidates?: ImputationCandidate[];
    imputation_results?: Array<Record<string, unknown>>;
  } | undefined;

  const candidate = phase3?.imputation_candidates?.find((c) => c.column === column);
  const block = phase3?.imputation_results?.find((r) => r.column === column);

  const health = results.health as { rows?: number; missing_per_column?: Record<string, number> } | undefined;
  const missingCount = Number(candidate?.missing_count ?? health?.missing_per_column?.[column] ?? 0);
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

  const rankedReasons = useMemo(() => {
    const ranked = (block?.ranked_methods as Array<{ method: string; score: number; reason?: string }>) ?? [];
    return ranked.map((r) => ({
      method: String(r.method).toLowerCase(),
      score: Number(r.score ?? methodScores[String(r.method).toLowerCase()] ?? 0),
      reason: r.reason,
    }));
  }, [block, methodScores]);

  const scoresList = useMemo(() => {
    if (rankedReasons.length) return rankedReasons;
    return METHODS.map((m) => ({
      method: m,
      score: Number(methodScores[m] ?? 0),
      reason: METHOD_DESCRIPTIONS[m],
    })).sort((a, b) => b.score - a.score);
  }, [rankedReasons, methodScores]);

  const [selectedMethod, setSelectedMethod] = useState<string>(recommended);
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>('all');
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const filteredMethods = scoresList.filter((s) => {
    if (confidenceFilter === 'all') return true;
    return bandOf(s.score) === confidenceFilter;
  });

  const bandCounts = useMemo(() => {
    const c = { high: 0, medium: 0, low: 0 };
    for (const s of scoresList) c[bandOf(s.score)] += 1;
    return c;
  }, [scoresList]);

  if (!candidate && missingCount === 0) {
    return (
      <Card className={cn('border-success/30 bg-success/5', className)}>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-6 w-6 text-success shrink-0" />
          <p className="font-semibold text-text">No missing values</p>
        </div>
      </Card>
    );
  }

  const previewRows = Array.from({ length: Math.min(5, missingCount || 3) }, (_, i) => i + 100);

  const handleSave = async (method: string, bulk = false) => {
    setSaving(true);
    try {
      const decisions = bulk
        ? previewRows.map((row) => ({
            row_index: row,
            column,
            method,
            decision: 'ACCEPT',
            original_value: null,
            imputed_value: null,
            confidence,
          }))
        : [{
            column,
            method,
            decision: 'ACCEPT',
            confidence,
          }];
      const res = await analysisApi.saveImputationDecisions(analysisId, column, method, decisions);
      if (res.success === false) throw new Error('Save failed');
      setSaved(true);
      toast.success(`Imputation method saved for ${column}`);
      onSaved?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Missing value intelligence" className={className}>
      <div className="grid grid-cols-3 gap-3 mb-4 text-sm">
        <div className="rounded border p-3"><p className="text-xs text-text-muted">Missing</p><p className="text-xl font-bold">{missingCount}</p></div>
        <div className="rounded border p-3"><p className="text-xs text-text-muted">Ratio</p><p className="text-xl font-bold">{missingPct.toFixed(1)}%</p></div>
        <div className="rounded border p-3"><p className="text-xs text-text-muted">Confidence</p><p className="text-xl font-bold">{(confidence * 100).toFixed(0)}%</p></div>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-4">
        {(['all', 'high', 'medium', 'low'] as const).map((f) => (
          <button key={f} type="button" onClick={() => setConfidenceFilter(f)}
            className={cn('px-2 py-1 rounded text-xs border capitalize',
              confidenceFilter === f ? 'bg-accent text-white border-accent' : 'border-border text-text-muted')}>
            {f === 'all' ? 'All methods' : `${f} (${bandCounts[f]})`}
          </button>
        ))}
        <Button variant="ghost" size="sm" onClick={() => setDrawerOpen(true)}>Explain methods</Button>
      </div>

      <div className="space-y-2 mb-4">
        {filteredMethods.map((s) => {
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
      </div>

      <div className="mb-4">
        <p className="text-sm font-semibold mb-2">Imputation preview (sample rows)</p>
        <div className="overflow-x-auto text-xs">
          <table className="w-full">
            <thead><tr className="border-b text-text-muted"><th className="py-1 pr-2">☐</th><th className="py-1 pr-2">Row</th><th className="py-1 pr-2">Current</th><th className="py-1 pr-2">Selected</th></tr></thead>
            <tbody>
              {previewRows.map((row) => (
                <tr key={row} className="border-b border-border/50">
                  <td className="py-1 pr-2">
                    <input type="checkbox" checked={selectedRows.has(row)} onChange={() => {
                      setSelectedRows((prev) => {
                        const n = new Set(prev);
                        if (n.has(row)) n.delete(row); else n.add(row);
                        return n;
                      });
                    }} />
                  </td>
                  <td className="py-1 pr-2 font-mono">{row}</td>
                  <td className="py-1 pr-2">NULL</td>
                  <td className="py-1 pr-2 capitalize">{selectedMethod} (preview)</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-4 p-3 rounded-lg bg-border/20">
        <Button variant="ghost" size="sm" onClick={() => setSelectedRows(new Set(previewRows))}>Select all</Button>
        <Button variant="ghost" size="sm" onClick={() => setSelectedMethod(recommended)}>Apply recommended</Button>
        {METHODS.map((m) => (
          <Button key={m} variant="ghost" size="sm" onClick={() => setSelectedMethod(m)} className="capitalize">{m}</Button>
        ))}
      </div>

      {missingPct > 30 && (
        <div className="flex items-start gap-2 rounded-lg bg-warning/10 border border-warning/30 p-3 text-sm mb-4">
          <Info className="h-4 w-4 text-warning shrink-0 mt-0.5" />
          <p className="text-text-muted">High missing ratio — review carefully before imputing.</p>
        </div>
      )}

      <Button disabled={!selectedMethod || saving} onClick={() => handleSave(selectedMethod, selectedRows.size > 0)} className="gap-2">
        <Save className="h-4 w-4" />
        {saved ? 'Saved' : saving ? 'Saving…' : `Save: ${selectedMethod}`}
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
