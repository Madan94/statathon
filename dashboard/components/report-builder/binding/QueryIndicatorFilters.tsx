'use client';

import { useEffect, useMemo, useState } from 'react';
import { Filter, Plus, Trash2, Zap } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { parseCsv, toNumber, type ParsedCsv } from '@/lib/csv';
import type { DatasetColumnProfile } from '@/lib/api';

// ─────────────────────────────────────────────────────────────────────────────
// Query indicator filter layer (loop template)
//   A starter "complex filtering" surface: the officer composes a set of
//   indicator predicates (column · operator · value) joined by AND / OR. The
//   uploaded CSV is parsed client-side so the matched-row count updates live.
//   The resulting QueryFilterRule[] + combinator is lifted to the binding page
//   so later loop-generation phases can consume it. Intentionally a scaffold
//   ("for now we will build on it") — predicate set is easy to extend.
// ─────────────────────────────────────────────────────────────────────────────

const COMPUTE_CAP = 100_000;

export type FilterOperator = 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'in';

export interface QueryFilterRule {
  id: string;
  column: string;
  operator: FilterOperator;
  value: string;
}

const OPERATORS: Array<{ value: FilterOperator; label: string; symbol: string; numeric?: boolean }> = [
  { value: 'eq', label: 'equals', symbol: '=' },
  { value: 'neq', label: 'not equals', symbol: '≠' },
  { value: 'gt', label: 'greater than', symbol: '>', numeric: true },
  { value: 'gte', label: 'at least', symbol: '≥', numeric: true },
  { value: 'lt', label: 'less than', symbol: '<', numeric: true },
  { value: 'lte', label: 'at most', symbol: '≤', numeric: true },
  { value: 'contains', label: 'contains', symbol: '⊇' },
  { value: 'in', label: 'in list', symbol: '∈' },
];

const OPERATOR_SYMBOL: Record<FilterOperator, string> = OPERATORS.reduce(
  (acc, o) => ({ ...acc, [o.value]: o.symbol }),
  {} as Record<FilterOperator, string>,
);

let ruleSeq = 0;
function newRuleId(): string {
  ruleSeq += 1;
  return `qf_${Date.now().toString(36)}_${ruleSeq}`;
}

/** Evaluate one predicate against a raw cell value. */
function matchRule(cell: string | undefined, rule: QueryFilterRule): boolean {
  const raw = (cell ?? '').trim();
  const target = rule.value.trim();
  if (target === '' && rule.operator !== 'eq' && rule.operator !== 'neq') return true; // incomplete rule → no-op
  switch (rule.operator) {
    case 'eq':
      return raw.toLowerCase() === target.toLowerCase();
    case 'neq':
      return raw.toLowerCase() !== target.toLowerCase();
    case 'gt':
    case 'gte':
    case 'lt':
    case 'lte': {
      const a = toNumber(raw);
      const b = toNumber(target);
      if (a === null || b === null) return false;
      if (rule.operator === 'gt') return a > b;
      if (rule.operator === 'gte') return a >= b;
      if (rule.operator === 'lt') return a < b;
      return a <= b;
    }
    case 'contains':
      return raw.toLowerCase().includes(target.toLowerCase());
    case 'in': {
      const set = target
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
      return set.includes(raw.toLowerCase());
    }
    default:
      return true;
  }
}

interface QueryIndicatorFiltersProps {
  file: File | null;
  columns: DatasetColumnProfile[];
  rules: QueryFilterRule[];
  combinator: 'AND' | 'OR';
  onChange: (rules: QueryFilterRule[], combinator: 'AND' | 'OR') => void;
  className?: string;
}

export function QueryIndicatorFilters({
  file,
  columns,
  rules,
  combinator,
  onChange,
  className,
}: QueryIndicatorFiltersProps) {
  const [parsed, setParsed] = useState<ParsedCsv | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const colIndex = useMemo(() => {
    const map = new Map<string, number>();
    parsed?.headers.forEach((h, idx) => map.set(h, idx));
    return map;
  }, [parsed]);

  // Live matched-row count over the parsed rows.
  const match = useMemo(() => {
    if (!parsed) return null;
    const active = rules.filter((r) => r.column && (r.value.trim() !== '' || r.operator === 'eq' || r.operator === 'neq'));
    if (!active.length) return { matched: parsed.totalDataRows, total: parsed.totalDataRows };
    let matched = 0;
    for (const row of parsed.rows) {
      const results = active.map((rule) => {
        const idx = colIndex.get(rule.column);
        return idx == null ? false : matchRule(row[idx], rule);
      });
      const ok = combinator === 'AND' ? results.every(Boolean) : results.some(Boolean);
      if (ok) matched += 1;
    }
    return { matched, total: parsed.totalDataRows };
  }, [parsed, rules, combinator, colIndex]);

  const addRule = () => {
    const firstCol = headerNames[0] ?? '';
    onChange([...rules, { id: newRuleId(), column: firstCol, operator: 'eq', value: '' }], combinator);
  };
  const updateRule = (id: string, patch: Partial<QueryFilterRule>) => {
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)), combinator);
  };
  const removeRule = (id: string) => {
    onChange(rules.filter((r) => r.id !== id), combinator);
  };
  const setCombinator = (c: 'AND' | 'OR') => onChange(rules, c);

  const summary = rules
    .filter((r) => r.column)
    .map((r) => `${r.column} ${OPERATOR_SYMBOL[r.operator]} ${r.value || '…'}`)
    .join(` ${combinator} `);

  const pct = match && match.total > 0 ? Math.round((match.matched / match.total) * 100) : 0;

  return (
    <div className={cn('rounded-2xl border border-border bg-surface-card shadow-sm', className)}>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-text">
            <Filter className="h-4 w-4 text-primary" aria-hidden />
            Query indicator filters
            <Badge variant="default" className="text-[9px]">loop template</Badge>
          </h3>
          <p className="mt-0.5 text-xs text-text-muted">
            Narrow the dataset to the rows the loop should iterate. Predicates combine with{' '}
            <span className="font-semibold text-text">{combinator}</span>.
          </p>
        </div>
        {match && (
          <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-1.5 text-right">
            <p className="text-sm font-bold tabular-nums text-primary">
              {match.matched.toLocaleString()}
              <span className="text-xs font-normal text-text-muted"> / {match.total.toLocaleString()} rows</span>
            </p>
            <p className="text-[10px] text-text-muted">{pct}% match this query</p>
          </div>
        )}
      </div>

      <div className="space-y-4 p-5">
        {error && (
          <Alert variant="error" title="Could not read the dataset">{error}</Alert>
        )}

        {/* Combinator toggle */}
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-text-muted">Match</span>
          <div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
            {(['AND', 'OR'] as const).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setCombinator(c)}
                className={cn(
                  'rounded-md px-3 py-1 text-xs font-semibold transition-colors',
                  combinator === c ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
                )}
              >
                {c === 'AND' ? 'ALL (AND)' : 'ANY (OR)'}
              </button>
            ))}
          </div>
          <span className="text-xs text-text-muted">of the predicates below</span>
        </div>

        {/* Rules */}
        {rules.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-surface px-4 py-8 text-center">
            <Filter className="mx-auto h-6 w-6 text-text-muted" aria-hidden />
            <p className="mt-2 text-sm text-text">No indicator filters yet.</p>
            <p className="text-xs text-text-muted">Add a predicate to restrict which rows the loop iterates.</p>
            <Button type="button" size="sm" className="mt-3" onClick={addRule}>
              <Plus className="h-4 w-4" /> Add predicate
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            {rules.map((rule, idx) => {
              const op = OPERATORS.find((o) => o.value === rule.operator);
              const profile = columns.find((c) => c.name === rule.column);
              const samples = (profile?.sampleValues ?? []).slice(0, 4).map(String).filter(Boolean);
              return (
                <div key={rule.id} className="rounded-xl border border-border bg-surface p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    {idx > 0 && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-bold text-primary">{combinator}</span>
                    )}
                    {/* column */}
                    <select
                      value={rule.column}
                      onChange={(e) => updateRule(rule.id, { column: e.target.value })}
                      className="min-w-[9rem] flex-1 rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {headerNames.map((h) => (
                        <option key={h} value={h}>{h}</option>
                      ))}
                    </select>
                    {/* operator */}
                    <select
                      value={rule.operator}
                      onChange={(e) => updateRule(rule.id, { operator: e.target.value as FilterOperator })}
                      className="rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {OPERATORS.map((o) => (
                        <option key={o.value} value={o.value}>{o.symbol} {o.label}</option>
                      ))}
                    </select>
                    {/* value */}
                    <input
                      value={rule.value}
                      onChange={(e) => updateRule(rule.id, { value: e.target.value })}
                      placeholder={op?.value === 'in' ? 'a, b, c' : op?.numeric ? 'number' : 'value'}
                      inputMode={op?.numeric ? 'decimal' : 'text'}
                      className="min-w-[7rem] flex-1 rounded-md border border-border bg-surface-card px-2 py-1.5 text-xs text-text outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    />
                    <button
                      type="button"
                      onClick={() => removeRule(rule.id)}
                      title="Remove predicate"
                      className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-danger/10 hover:text-danger"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {samples.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap items-center gap-1 pl-1">
                      <span className="text-[9px] uppercase text-text-muted">e.g.</span>
                      {samples.map((s, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => updateRule(rule.id, { value: s })}
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
            <Button type="button" variant="outline" size="sm" onClick={addRule}>
              <Plus className="h-4 w-4" /> Add predicate
            </Button>
          </div>
        )}

        {/* Query summary */}
        {summary && (
          <div className="flex gap-2 rounded-lg border border-border bg-surface px-4 py-3">
            <Zap className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wide text-text-muted">Query</p>
              <p className="break-words font-mono text-xs text-text">
                WHERE {summary}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default QueryIndicatorFilters;
