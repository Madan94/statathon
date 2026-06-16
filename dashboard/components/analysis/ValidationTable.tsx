'use client';

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from 'react';
import { Loader2, Save, ShieldAlert } from 'lucide-react';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import EmptyState from '@/components/ui/EmptyState';
import ValidationDetailDrawer from '@/components/analysis/ValidationDetailDrawer';
import { ValidationCandidate, ValidationDecisionItem, analysisApi } from '@/lib/api';
import { toast } from '@/lib/toast';

const DECISION_OPTIONS = [
  { value: 'KEEP', label: 'Keep' },
  { value: 'TREAT_AS_MISSING', label: 'Mark missing' },
  { value: 'REMOVE_ROW', label: 'Delete row' },
  { value: 'IGNORE_RULE', label: 'Ignore' },
  { value: 'MODIFY', label: 'Modify value' },
] as const;

type DecisionValue = (typeof DECISION_OPTIONS)[number]['value'];
export type ValidationLoadState = 'idle' | 'loading' | 'loaded' | 'error';

const LOADING_PHASES = [
  'Discovering rules',
  'Applying single-column rules',
  'Applying multi-column rules',
  'Scoring violations',
  'Preparing review table',
];

export interface ValidationTableHandle {
  saveDecisions: () => Promise<{ saved: number }>;
  getDecisionPayload: () => ValidationDecisionItem[];
  hasPendingChanges: () => boolean;
}

interface ValidationTableProps {
  candidates: ValidationCandidate[];
  analysisId?: number;
  loadState?: ValidationLoadState;
  loadError?: string | null;
  domainByColumn?: Record<string, string>;
  onSaved?: () => void;
  paginated?: boolean;
  totalCandidates?: number;
  reportedTotal?: number;
  candidatesTruncated?: boolean;
}

function candidateRuleId(c: ValidationCandidate): string {
  return String(
    c.rule_id ??
      (typeof c.rule === 'string'
        ? c.rule
        : typeof c.rule === 'object'
          ? c.rule?.rule_id
          : undefined) ??
      c.kind ??
      'rule',
  );
}

function stableRowKey(c: ValidationCandidate): string {
  return `${c.column ?? 'col'}-${c.row ?? 'na'}-${candidateRuleId(c)}`;
}

function rowKey(c: ValidationCandidate, _i?: number): string {
  return stableRowKey(c);
}

function ValidationLoadingPanel({ phaseIndex }: { phaseIndex: number }) {
  return (
    <div className="space-y-6 py-4" aria-live="polite" aria-busy="true">
      <div className="flex items-center gap-3">
        <Loader2 className="h-5 w-5 animate-spin text-accent shrink-0" />
        <div>
          <p className="font-medium text-text">Loading rule validation results…</p>
          <p className="text-sm text-text-muted">Applying validation rules to your dataset</p>
        </div>
      </div>
      <div className="space-y-2 border-l-2 border-accent/30 pl-4">
        {LOADING_PHASES.map((label, i) => (
          <p
            key={label}
            className={`text-sm ${i <= phaseIndex ? 'text-text font-medium' : 'text-text-muted'}`}
          >
            {i <= phaseIndex ? '✓' : '○'} {label}
          </p>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
              <th className="pb-2 pr-3 w-8" />
              <th className="pb-2 pr-3">Column</th>
              <th className="pb-2 pr-3">Row</th>
              <th className="pb-2 pr-3">Value</th>
              <th className="pb-2 pr-3">Severity</th>
              <th className="pb-2 pr-3">Rule</th>
              <th className="pb-2">Decision</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 10 }).map((_, i) => (
              <tr key={i} className="border-b border-border/60">
                <td className="py-3 pr-3"><Skeleton className="h-4 w-4" /></td>
                <td className="py-3 pr-3"><Skeleton className="h-4 w-20" /></td>
                <td className="py-3 pr-3"><Skeleton className="h-4 w-10" /></td>
                <td className="py-3 pr-3"><Skeleton className="h-4 w-14" /></td>
                <td className="py-3 pr-3"><Skeleton className="h-5 w-16" /></td>
                <td className="py-3 pr-3"><Skeleton className="h-4 w-32" /></td>
                <td className="py-3"><Skeleton className="h-8 w-28" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const ValidationTable = forwardRef<ValidationTableHandle, ValidationTableProps>(
  function ValidationTable(
    {
      candidates,
      analysisId,
      loadState = 'loaded',
      loadError,
      domainByColumn,
      onSaved,
      paginated = false,
      totalCandidates,
      reportedTotal,
      candidatesTruncated = false,
    },
    ref,
  ) {
    const [severityFilter, setSeverityFilter] = useState<string>('all');
    const [columnFilter, setColumnFilter] = useState('');
    const [decisions, setDecisions] = useState<Record<string, DecisionValue>>({});
    const [modifyValues, setModifyValues] = useState<Record<string, string>>({});
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [bulkDecision, setBulkDecision] = useState<DecisionValue>('KEEP');
    const [saving, setSaving] = useState(false);
    const [savedCount, setSavedCount] = useState(0);
    const [detailRow, setDetailRow] = useState<ValidationCandidate | null>(null);
    const [phaseIndex, setPhaseIndex] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(50);
    const [pageTotal, setPageTotal] = useState(totalCandidates ?? candidates.length);
    const [pageCandidates, setPageCandidates] = useState<ValidationCandidate[]>(
      paginated ? [] : candidates,
    );
    const [pageLoading, setPageLoading] = useState(false);
    const [selectingAll, setSelectingAll] = useState(false);
    const [candidateCache, setCandidateCache] = useState<Record<string, ValidationCandidate>>({});

    const activeCandidates = paginated ? pageCandidates : candidates;

    useEffect(() => {
      if (!paginated) {
        setPageCandidates(candidates);
        setPageTotal(totalCandidates ?? candidates.length);
      }
    }, [paginated, candidates, totalCandidates]);

    useEffect(() => {
      if (!paginated || !analysisId || loadState !== 'loaded') return;
      let cancelled = false;
      setPageLoading(true);
      analysisApi
        .getValidationCandidates(analysisId, {
          page,
          pageSize,
          severity: severityFilter !== 'all' ? severityFilter : undefined,
          column: columnFilter || undefined,
        })
        .then((res) => {
          if (cancelled) return;
          setPageCandidates(res.items);
          setPageTotal(res.total);
          setCandidateCache((prev) => {
            const next = { ...prev };
            res.items.forEach((c) => {
              next[stableRowKey(c)] = c;
            });
            return next;
          });
        })
        .catch(() => {
          if (!cancelled) setPageCandidates([]);
        })
        .finally(() => {
          if (!cancelled) setPageLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }, [paginated, analysisId, loadState, page, pageSize, severityFilter, columnFilter]);

    useEffect(() => {
      if (loadState !== 'loading') return;
      setPhaseIndex(0);
      const timer = setInterval(() => {
        setPhaseIndex((p) => (p < LOADING_PHASES.length - 1 ? p + 1 : p));
      }, 700);
      return () => clearInterval(timer);
    }, [loadState]);

    const severities = useMemo(() => {
      const set = new Set(activeCandidates.map((c) => (c.severity || 'REVIEW').toUpperCase()));
      return ['all', ...Array.from(set)];
    }, [activeCandidates]);

    const filtered = useMemo(() => {
      if (paginated) return activeCandidates;
      return activeCandidates.filter((c) => {
        const sev = (c.severity || 'REVIEW').toUpperCase();
        if (severityFilter !== 'all' && sev !== severityFilter) return false;
        if (columnFilter && !(c.column || '').toLowerCase().includes(columnFilter.toLowerCase())) {
          return false;
        }
        return true;
      });
    }, [activeCandidates, paginated, severityFilter, columnFilter]);

    const filteredKeys = useMemo(
      () => filtered.map((c) => stableRowKey(c)),
      [filtered],
    );

    const candidateToDecisionItem = (
      c: ValidationCandidate,
      decisionMap: Record<string, DecisionValue>,
    ): ValidationDecisionItem => {
      const key = stableRowKey(c);
      const decision = decisionMap[key] ?? 'KEEP';
      return {
        rule_id: candidateRuleId(c),
        column: c.column ?? '',
        row_index: c.row ?? null,
        rule_type: c.kind ?? 'single_column',
        severity: c.severity,
        confidence: c.confidence,
        decision,
        old_value: c.value ?? null,
        new_value: decision === 'MODIFY' ? modifyValues[key] ?? null : null,
      };
    };

    const buildFullPayload = async (
      decisionMap: Record<string, DecisionValue> = decisions,
    ): Promise<ValidationDecisionItem[]> => {
      if (paginated && analysisId) {
        const { items } = await analysisApi.fetchAllValidationCandidates(analysisId, {
          severity: severityFilter !== 'all' ? severityFilter : undefined,
          column: columnFilter || undefined,
        });
        return items.map((c) => candidateToDecisionItem(c, decisionMap));
      }
      return buildPayload(undefined, decisionMap);
    };

    const buildPayload = (
      keys?: Set<string> | string[],
      decisionMap: Record<string, DecisionValue> = decisions,
    ): ValidationDecisionItem[] => {
      const keySet = keys instanceof Set ? keys : keys ? new Set(keys) : null;
      const sourceEntries = keySet
        ? Object.entries(candidateCache).filter(([key]) => keySet.has(key))
        : paginated
          ? Object.entries(candidateCache)
          : candidates.map((c) => [stableRowKey(c), c] as const);

      if (keySet && sourceEntries.length === 0 && !paginated) {
        return candidates
          .filter((c) => keySet.has(stableRowKey(c)))
          .map((c) => {
            const key = stableRowKey(c);
            const decision = decisionMap[key] ?? 'KEEP';
            return {
              rule_id: candidateRuleId(c),
              column: c.column ?? '',
              row_index: c.row ?? null,
              rule_type: c.kind ?? 'single_column',
              severity: c.severity,
              confidence: c.confidence,
              decision,
              old_value: c.value ?? null,
              new_value: decision === 'MODIFY' ? modifyValues[key] ?? null : null,
            };
          });
      }

      return sourceEntries.map(([key, c]) => {
        const decision = decisionMap[key] ?? 'KEEP';
        return {
          rule_id: candidateRuleId(c),
          column: c.column ?? '',
          row_index: c.row ?? null,
          rule_type: c.kind ?? 'single_column',
          severity: c.severity,
          confidence: c.confidence,
          decision,
          old_value: c.value ?? null,
          new_value: decision === 'MODIFY' ? modifyValues[key] ?? null : null,
        };
      });
    };

    const handleSave = async (decisionMap: Record<string, DecisionValue> = decisions) => {
      if (!analysisId) return { saved: 0 };
      setSaving(true);
      try {
        const payload = await buildFullPayload(decisionMap);
        const res = await analysisApi.saveValidationDecisions(analysisId, payload);
        const count = Number(res.saved ?? payload.length);
        setSavedCount(count);
        if (res.success === false) {
          throw new Error('Server did not confirm save');
        }
        toast.success(`Saved ${count} validation decision(s)`);
        onSaved?.();
        return { saved: count };
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Failed to save validation decisions');
        throw err;
      } finally {
        setSaving(false);
      }
    };

    useImperativeHandle(ref, () => ({
      saveDecisions: handleSave,
      getDecisionPayload: () => buildPayload(),
      hasPendingChanges: () =>
        Object.values(decisions).some((d) => d !== 'KEEP') ||
        Object.keys(modifyValues).length > 0,
    }));

    const toggleSelect = (key: string) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
    };

    const selectAllFiltered = () => setSelected(new Set(filteredKeys));

    const selectAllViolations = async () => {
      if (!analysisId || !paginated) {
        selectAllFiltered();
        return;
      }
      setSelectingAll(true);
      try {
        const { items, total } = await analysisApi.fetchAllValidationCandidates(analysisId, {
          severity: severityFilter !== 'all' ? severityFilter : undefined,
          column: columnFilter || undefined,
        });
        const keys = new Set<string>();
        const cachePatch: Record<string, ValidationCandidate> = {};
        for (const c of items) {
          const key = stableRowKey(c);
          keys.add(key);
          cachePatch[key] = c;
        }
        setCandidateCache((prev) => ({ ...prev, ...cachePatch }));
        setSelected(keys);
        toast.success(`Selected all ${keys.size} of ${total} violation(s)`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Failed to select all violations');
      } finally {
        setSelectingAll(false);
      }
    };

    const selectBySeverity = (sev: string) => {
      const keys = filtered
        .filter((c) => (c.severity || '').toUpperCase() === sev)
        .map((c) => stableRowKey(c));
      setSelected(new Set(keys));
    };

    const selectByColumn = (col: string) => {
      const keys = filtered
        .filter((c) => (c.column || '').toLowerCase() === col.toLowerCase())
        .map((c) => stableRowKey(c));
      setSelected(new Set(keys));
    };

    const applyBulkDecision = async () => {
      if (!selected.size) {
        toast.error('Select at least one row');
        return;
      }
      const updatedDecisions = { ...decisions };
      selected.forEach((key) => {
        updatedDecisions[key] = bulkDecision;
      });
      setDecisions(updatedDecisions);
      if (analysisId) {
        try {
          await handleSave(updatedDecisions);
          return;
        } catch {
          toast.error('Applied locally but save failed — click Save decisions to retry');
          return;
        }
      }
      toast.success(`Applied "${bulkDecision}" to ${selected.size} row(s)`);
    };

    if (loadState === 'loading' || loadState === 'idle') {
      return (
        <Card title="Rule validation" description="Review flagged cells and record auditable decisions">
          <ValidationLoadingPanel phaseIndex={phaseIndex} />
        </Card>
      );
    }

    if (loadState === 'error') {
      return (
        <Card title="Rule validation">
          <EmptyState
            icon={ShieldAlert}
            title="Failed to load validation results"
            description={loadError ?? 'Could not load rule validation data from the server.'}
          />
        </Card>
      );
    }

    if (!paginated && !candidates.length) {
      return (
        <EmptyState
          icon={ShieldAlert}
          title="No validation issues flagged"
          description="Rule validation found no candidates requiring review."
        />
      );
    }

    if (paginated && pageTotal === 0 && !pageLoading) {
      return (
        <EmptyState
          icon={ShieldAlert}
          title="No validation issues flagged"
          description="Rule validation found no candidates requiring review."
        />
      );
    }

    const uniqueColumns = [...new Set(activeCandidates.map((c) => c.column).filter(Boolean))] as string[];
    const displayTotal = paginated ? pageTotal : candidates.length;
    const headlineTotal = reportedTotal && reportedTotal > displayTotal ? reportedTotal : displayTotal;
    const pageStart = displayTotal === 0 ? 0 : (page - 1) * pageSize + 1;
    const pageEnd = Math.min(page * pageSize, displayTotal);

    return (
      <>
        <Card
          title={`Rule validation (${headlineTotal})`}
          description="Review flagged cells and record auditable decisions before proceeding"
        >
          {candidatesTruncated && reportedTotal != null && reportedTotal > displayTotal && (
            <p className="text-xs text-warning mb-3">
              {displayTotal} of {reportedTotal} violations are loaded in the review table. Re-run rule validation
              to persist the full set ({reportedTotal - displayTotal} not stored from the prior run).
            </p>
          )}
          {paginated && displayTotal > pageSize && (
            <p className="text-xs text-text-muted mb-3">
              Showing {pageStart}–{pageEnd} of {displayTotal} violations
            </p>
          )}
          <div className="flex flex-wrap gap-3 mb-4">
            <select
              value={severityFilter}
              onChange={(e) => {
                setSeverityFilter(e.target.value);
                setPage(1);
              }}
              className="text-sm rounded-lg border border-border px-3 py-2 bg-surface-card"
              aria-label="Filter by severity"
            >
              {severities.map((s) => (
                <option key={s} value={s}>
                  {s === 'all' ? 'All severities' : s}
                </option>
              ))}
            </select>
            <input
              type="search"
              placeholder="Filter by column…"
              value={columnFilter}
              onChange={(e) => {
                setColumnFilter(e.target.value);
                setPage(1);
              }}
              className="text-sm rounded-lg border border-border px-3 py-2 flex-1 min-w-[160px] bg-surface-card"
              aria-label="Filter by column"
            />
            {analysisId && (
              <Button variant="secondary" size="sm" onClick={() => void handleSave()} disabled={saving} className="gap-1.5">
                <Save className="h-3.5 w-3.5" />
                {saving ? 'Saving…' : savedCount ? `Saved (${savedCount})` : 'Save decisions'}
              </Button>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 mb-4 p-3 rounded-lg bg-border/20 border border-border/60">
            <span className="text-xs text-text-muted mr-1">{selected.size} selected</span>
            {paginated && analysisId ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void selectAllViolations()}
                disabled={selectingAll || displayTotal === 0}
              >
                {selectingAll
                  ? 'Selecting…'
                  : `Select all ${displayTotal} violation${displayTotal !== 1 ? 's' : ''}`}
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={selectAllFiltered}>Select page</Button>
            <Button variant="ghost" size="sm" onClick={() => selectBySeverity('HIGH')}>Select all HIGH</Button>
            <Button variant="ghost" size="sm" onClick={() => selectBySeverity('LOW')}>Select all LOW</Button>
            {uniqueColumns.slice(0, 3).map((col) => (
              <Button key={col} variant="ghost" size="sm" onClick={() => selectByColumn(col)}>
                Select {col}
              </Button>
            ))}
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-xs text-text-muted">Apply to selected</span>
              <select
                value={bulkDecision}
                onChange={(e) => setBulkDecision(e.target.value as DecisionValue)}
                className="text-xs rounded border border-border px-2 py-1.5 bg-surface-card"
              >
                {DECISION_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <Button variant="secondary" size="sm" onClick={() => void applyBulkDecision()}>Apply</Button>
            </div>
          </div>

          <div className="overflow-x-auto max-h-[28rem]">
            {pageLoading ? (
              <div className="py-8 flex justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-accent" />
              </div>
            ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-card z-10">
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
                  <th className="pb-2 pr-2 w-8">
                    <input
                      type="checkbox"
                      checked={filteredKeys.length > 0 && filteredKeys.every((k) => selected.has(k))}
                      onChange={(e) => (e.target.checked ? selectAllFiltered() : setSelected(new Set()))}
                      aria-label="Select all rows on this page"
                    />
                  </th>
                  <th className="pb-2 pr-3">Column</th>
                  <th className="pb-2 pr-3">Row</th>
                  <th className="pb-2 pr-3">Value</th>
                  <th className="pb-2 pr-3">Severity</th>
                  <th className="pb-2 pr-3">Rule</th>
                  <th className="pb-2">Decision</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => {
                  const key = stableRowKey(c);
                  const decision = decisions[key] ?? 'KEEP';
                  const isSelected = selected.has(key);
                  return (
                    <tr
                      key={key}
                      className={`border-b border-border/60 align-top cursor-pointer hover:bg-border/20 ${isSelected ? 'bg-accent/5' : ''}`}
                      onClick={() => setDetailRow(c)}
                    >
                      <td className="py-2 pr-2" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(key)}
                          aria-label={`Select row ${c.row}`}
                        />
                      </td>
                      <td className="py-2 pr-3 font-medium">{c.column || '—'}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{c.row ?? '—'}</td>
                      <td className="py-2 pr-3 font-mono text-xs font-medium">{c.value != null ? String(c.value) : '—'}</td>
                      <td className="py-2 pr-3">
                        <Badge variant="warning">{(c.severity || 'REVIEW').toUpperCase()}</Badge>
                      </td>
                      <td className="py-2 pr-3 text-text-muted text-xs max-w-[200px]">
                        <div className="truncate" title={c.reason ?? c.rule_id ?? ''}>
                          {c.rule_id ??
                            (typeof c.rule === 'string' ? c.rule : c.rule?.rule_id) ??
                            '—'}
                        </div>
                        {c.expected && (
                          <div className="text-[10px] text-text-muted truncate">Expected: {c.expected}</div>
                        )}
                      </td>
                      <td className="py-2" onClick={(e) => e.stopPropagation()}>
                        <div className="flex flex-col gap-1 min-w-[140px]">
                          <select
                            value={decision}
                            onChange={(e) =>
                              setDecisions((prev) => ({ ...prev, [key]: e.target.value as DecisionValue }))
                            }
                            className="text-xs rounded border border-border px-2 py-1 bg-surface-card"
                            aria-label={`Decision for row ${c.row}`}
                          >
                            {DECISION_OPTIONS.map((o) => (
                              <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                          </select>
                          {decision === 'MODIFY' && (
                            <input
                              type="text"
                              placeholder="New value"
                              value={modifyValues[key] ?? ''}
                              onChange={(e) =>
                                setModifyValues((prev) => ({ ...prev, [key]: e.target.value }))
                              }
                              className="text-xs rounded border border-border px-2 py-1 bg-surface-card"
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            )}
          </div>

          {paginated && displayTotal > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 mt-4 pt-4 border-t border-border">
              <div className="flex items-center gap-2 text-sm text-text-muted">
                <span>Rows per page</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
                  className="text-sm rounded border border-border px-2 py-1 bg-surface-card"
                >
                  {[25, 50, 100, 200, 500].map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1 || pageLoading}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Previous
                </Button>
                <span className="text-sm text-text-muted">
                  Page {page} of {Math.max(1, Math.ceil(displayTotal / pageSize))}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page * pageSize >= displayTotal || pageLoading}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </Card>

        <ValidationDetailDrawer
          candidate={detailRow}
          domain={detailRow?.column ? domainByColumn?.[detailRow.column] ?? detailRow.domain : detailRow?.domain}
          onClose={() => setDetailRow(null)}
        />
      </>
    );
  },
);

export default ValidationTable;
