'use client';

/**
 * EntityMatrixPanel — the full binding review matrix.
 *
 * Two-layer architecture per the dataset-first binder model:
 *
 *  Layer 1 (Dataset matching tab — default):
 *    Primary rows = dataset columns.
 *    For each column: show best-matching template entity, confidence,
 *    role, questions it feeds. Officer confirms, overrides, or assigns
 *    a lifecycle decision (matched / added_as_entity / ignored_* / needs_question).
 *
 *  Layer 2 (Template coverage tab):
 *    Rows = template entities from the proposals list.
 *    Shows each entity's status, dependent questions, and whether the
 *    dataset provided a column. Acts as a health-check / audit trail.
 *
 * The onDecide callback operates on entityId (backend contract unchanged).
 * Column lifecycle decisions go through onColumnDecide (optional — gracefully
 * absent if the parent hasn't wired it yet).
 */

import { useMemo, useState } from 'react';
import { AlertCircle, AlertTriangle, Check, ChevronDown, ChevronUp, Filter, GitPullRequestArrow, Info, Plus, Search, Share2, X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EntityBindingCard } from './EntityBindingCard';
import type {
  BindingAction,
  BindingDependencyGraph,
  BindingWorkspaceIssue,
  ColumnDecisionStatus,
  ColumnOwnershipMap,
  DatasetColumnProfile,
  EntityBinding,
} from '@/lib/api';

// ─── Exported decision type ────────────────────────────────────────────────

export type EntityDecision = {
  action: BindingAction;
  columns?: string[];
  note?: string;
  force_transfer?: boolean;
  transfer_from_entity_ids?: string[];
  share_policy?: 'exclusive' | 'shared';
  share_reason?: string;
};

export type ColumnDecision = {
  column: string;
  status: ColumnDecisionStatus;
  entity_id?: string;
  note?: string;
};

// ─── Internals ─────────────────────────────────────────────────────────────

const LIFECYCLE_META: Record<ColumnDecisionStatus, { label: string; badge: 'success' | 'warning' | 'muted' | 'danger' | 'default'; hint: string }> = {
  matched:              { label: 'Matched',          badge: 'success',  hint: 'Bound to a template entity' },
  added_as_entity:      { label: 'Added as entity',  badge: 'default',  hint: 'Officer created a new entity for this column' },
  ignored_metadata:     { label: 'Ignored (metadata)', badge: 'muted',  hint: 'Not used — identified as metadata/code column' },
  ignored_duplicate:    { label: 'Ignored (duplicate)', badge: 'muted', hint: 'Not used — duplicate or derived column' },
  ignored_out_of_scope: { label: 'Ignored (scope)',  badge: 'muted',    hint: 'Not used — out of scope for this template' },
  needs_question:       { label: 'Needs question',   badge: 'warning',  hint: 'Important column — needs a new question/entity' },
};

const IGNORE_STATUSES: ColumnDecisionStatus[] = [
  'ignored_metadata',
  'ignored_duplicate',
  'ignored_out_of_scope',
];

type MatrixTab = 'dataset' | 'template';

interface EntityMatrixPanelProps {
  /** The S1-proposed entity bindings (one per template entity). */
  bindings: EntityBinding[];
  /** All dataset column profiles from the DatasetAST. */
  columns: DatasetColumnProfile[];
  /** Live column ownership map from the review record. */
  columnOwnership?: ColumnOwnershipMap;
  /** Persisted per-column lifecycle decisions. */
  columnDecisions?: Record<string, ColumnDecision>;
  /** Current human entity decisions, indexed by entityId. */
  decisions: Record<string, EntityDecision>;
  /** Dependency graph linking entities → questions → columns. */
  dependencyGraph?: BindingDependencyGraph;
  /** Open workspace issues (for issue badges on rows). */
  issues?: BindingWorkspaceIssue[];
  /** entityId currently awaiting a backend response. */
  busyEntity?: string | null;
  onDecide: (entityId: string, decision: EntityDecision) => void;
  onConfirmAll?: () => void;
  /** Optional: save a column lifecycle decision. */
  onColumnDecide?: (decision: ColumnDecision) => void;
  /** Optional: open add-entity form pre-filled for a specific column. */
  onCreateEntity?: (columnName: string) => void;
  className?: string;
}

// ─── Dataset-first column row ────────────────────────────────────────────────

interface ColumnRowProps {
  col: DatasetColumnProfile;
  bestEntity: EntityBinding | null;
  decision: EntityDecision | null;
  columnDecision: ColumnDecision | null;
  ownershipEntry: ColumnOwnershipMap['columns'][string] | undefined;
  questionCount: number;
  issueCount: number;
  busy: boolean;
  onDecide: (entityId: string, decision: EntityDecision) => void;
  onColumnDecide?: (decision: ColumnDecision) => void;
  onCreateEntity?: (columnName: string) => void;
}

function ColumnRow({
  col,
  bestEntity,
  decision,
  columnDecision,
  ownershipEntry,
  questionCount,
  issueCount,
  busy,
  onDecide,
  onColumnDecide,
  onCreateEntity,
}: ColumnRowProps) {
  const [showIgnoreMenu, setShowIgnoreMenu] = useState(false);
  const [ignoreNote, setIgnoreNote] = useState('');
  const [pendingIgnoreStatus, setPendingIgnoreStatus] = useState<ColumnDecisionStatus | null>(null);

  const lifecycleStatus: ColumnDecisionStatus | null = columnDecision?.status ?? (
    bestEntity && (decision?.action === 'confirm' || decision?.action === 'override' || decision?.action === 'share')
      ? 'matched'
      : bestEntity && decision?.action === 'reject'
        ? null
        : null
  );
  const lcMeta = lifecycleStatus ? LIFECYCLE_META[lifecycleStatus] : null;

function entityStatusBadge(status: EntityBinding['status']): 'success' | 'default' | 'muted' | 'danger' | 'warning' {
  if (status === 'confirmed') return 'success';
  if (status === 'overridden') return 'default';
  if (status === 'rejected') return 'muted';
  if (status === 'unresolved') return 'danger';
  return 'warning'; // proposed
}

  const handleIgnoreSubmit = (status: ColumnDecisionStatus) => {
    onColumnDecide?.({ column: col.name, status, note: ignoreNote.trim() || undefined });
    setShowIgnoreMenu(false);
    setIgnoreNote('');
    setPendingIgnoreStatus(null);
  };

  return (
    <div
      className={cn(
        'rounded-xl border bg-surface-card px-4 py-3 text-sm shadow-sm transition-all',
        issueCount > 0 ? 'border-warning/30' : 'border-border',
        busy && 'opacity-60 pointer-events-none',
      )}
    >
      {/* Header row: column name + lifecycle badge + issue indicator */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-text">{col.name}</span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
              {col.role}
            </span>
            {col.dtype && (
              <span className="text-[10px] text-text-muted">{col.dtype}</span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {col.cardinality} distinct
            {col.nullPct > 0 ? ` · ${(col.nullPct * 100).toFixed(1)}% null` : ''}
            {col.unit ? ` · ${col.unit}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {issueCount > 0 && (
            <span className="flex items-center gap-1 text-xs text-warning">
              <AlertTriangle className="h-3 w-3" />{issueCount}
            </span>
          )}
          {lcMeta ? (
            <Badge variant={lcMeta.badge} className="text-[10px]">{lcMeta.label}</Badge>
          ) : (
            <Badge variant="muted" className="text-[10px]">Undecided</Badge>
          )}
        </div>
      </div>

      {/* Template entity match */}
      <div className="mt-3">
        {bestEntity ? (
          <div className="rounded-lg border border-border bg-surface px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-xs font-semibold text-text">{bestEntity.entityName}</span>
                <Badge variant={entityStatusBadge(decision ? (
                  decision.action === 'confirm' ? 'confirmed' :
                  decision.action === 'override' || decision.action === 'share' ? 'overridden' :
                  decision.action === 'reject' ? 'rejected' : bestEntity.status
                ) : bestEntity.status)} className="text-[10px]">
                  {decision?.action === 'confirm' ? 'confirmed' :
                   decision?.action === 'override' ? 'overridden' :
                   decision?.action === 'share' ? 'shared' :
                   decision?.action === 'reject' ? 'skipped' :
                   bestEntity.status}
                </Badge>
                {/* Confidence bar */}
                <div className="flex items-center gap-1">
                  <div className="h-1.5 w-14 overflow-hidden rounded-full bg-border">
                    <div
                      className={cn('h-full rounded-full', bestEntity.confidence >= 0.85 ? 'bg-success' : bestEntity.confidence >= 0.6 ? 'bg-warning' : 'bg-danger')}
                      style={{ width: `${Math.round(bestEntity.confidence * 100)}%` }}
                    />
                  </div>
                  <span className={cn('text-[10px] font-semibold tabular-nums', bestEntity.confidence >= 0.85 ? 'text-success' : bestEntity.confidence >= 0.6 ? 'text-warning' : 'text-danger')}>
                    {Math.round(bestEntity.confidence * 100)}%
                  </span>
                </div>
              </div>
              {questionCount > 0 && (
                <span className="text-[10px] text-text-muted">{questionCount} question{questionCount !== 1 ? 's' : ''}</span>
              )}
            </div>
            {/* Confirm / reopen actions on the entity */}
            {!decision || decision.action === 'reopen' ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => onDecide(bestEntity.entityId, { action: 'confirm' })}
                >
                  <Check className="h-3 w-3" /> Confirm
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => onDecide(bestEntity.entityId, { action: 'reject' })}
                >
                  <X className="h-3 w-3" /> Skip entity
                </Button>
              </div>
            ) : decision.action !== 'reject' ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="mt-2 h-6 px-2 text-[10px] text-text-muted"
                onClick={() => onDecide(bestEntity.entityId, { action: 'reopen' })}
              >
                <GitPullRequestArrow className="h-3 w-3" /> Reopen
              </Button>
            ) : null}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border bg-surface px-3 py-2">
            <p className="text-xs text-text-muted">No template entity matched this column.</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {onCreateEntity && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => onCreateEntity(col.name)}
                >
                  <Plus className="h-3 w-3" /> Create entity
                </Button>
              )}
              {IGNORE_STATUSES.map((s) => (
                <Button
                  key={s}
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-[10px] text-text-muted"
                  onClick={() => handleIgnoreSubmit(s)}
                >
                  {LIFECYCLE_META[s].label}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Column lifecycle actions when entity is skipped or column has no match */}
      {onColumnDecide && (!lifecycleStatus || IGNORE_STATUSES.includes(lifecycleStatus as ColumnDecisionStatus)) && (
        <div className="relative mt-2">
          <button
            type="button"
            className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text"
            onClick={() => setShowIgnoreMenu((v) => !v)}
          >
            <Filter className="h-3 w-3" />
            {lifecycleStatus ? `Change: ${LIFECYCLE_META[lifecycleStatus]?.label ?? lifecycleStatus}` : 'Assign lifecycle status'}
            {showIgnoreMenu ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          {showIgnoreMenu && (
            <div className="absolute left-0 top-6 z-30 w-64 rounded-xl border border-border bg-surface-card p-3 shadow-xl">
              <p className="mb-2 text-xs font-semibold text-text">Column lifecycle</p>
              {IGNORE_STATUSES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={cn(
                    'block w-full rounded-lg px-2 py-1.5 text-left text-xs text-text-muted transition-colors hover:bg-surface hover:text-text',
                    lifecycleStatus === s && 'font-semibold text-text',
                  )}
                  onClick={() => setPendingIgnoreStatus(s)}
                >
                  <span className="font-medium">{LIFECYCLE_META[s].label}</span>
                  <span className="ml-1 text-[10px] opacity-70">— {LIFECYCLE_META[s].hint}</span>
                </button>
              ))}
              {onCreateEntity && (
                <button
                  type="button"
                  className="mt-1 block w-full rounded-lg px-2 py-1.5 text-left text-xs text-primary transition-colors hover:bg-primary/5"
                  onClick={() => { setShowIgnoreMenu(false); onCreateEntity(col.name); }}
                >
                  <span className="font-medium">Create new entity</span>
                  <span className="ml-1 text-[10px] opacity-70">— Bind this column to a new entity</span>
                </button>
              )}
              {pendingIgnoreStatus && (
                <div className="mt-2 space-y-1.5">
                  <p className="text-[10px] text-text-muted">Optional note for audit trail:</p>
                  <input
                    value={ignoreNote}
                    onChange={(e) => setIgnoreNote(e.target.value)}
                    placeholder="Reason / note"
                    className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none"
                  />
                  <div className="flex gap-1.5">
                    <Button
                      type="button"
                      size="sm"
                      className="h-6 flex-1 px-2 text-[10px]"
                      onClick={() => handleIgnoreSubmit(pendingIgnoreStatus)}
                    >
                      Confirm
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-[10px]"
                      onClick={() => { setPendingIgnoreStatus(null); setIgnoreNote(''); }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Unmatched entity row (template coverage view) ──────────────────────────

interface UnmatchedEntityRowProps {
  binding: EntityBinding;
  questionCount: number;
  decision: EntityDecision | null;
  onDecide: (entityId: string, decision: EntityDecision) => void;
}

function UnmatchedEntityRow({ binding, questionCount, decision, onDecide }: UnmatchedEntityRowProps) {
  return (
    <div className="rounded-xl border border-danger/25 bg-danger/5 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-text">{binding.entityName}</span>
            <Badge variant="danger" className="text-[10px]">No dataset column</Badge>
            <span className="text-[10px] text-text-muted">{binding.entityType}</span>
          </div>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {questionCount} question{questionCount !== 1 ? 's' : ''} depend{questionCount === 1 ? 's' : ''} on this entity
          </p>
        </div>
        <div className="flex items-center gap-2">
          {decision?.action === 'reject' ? (
            <Badge variant="muted" className="text-[10px]">Deprecated</Badge>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-6 px-2 text-[10px] text-danger"
              onClick={() => onDecide(binding.entityId, { action: 'reject', note: 'deprecated — no matching dataset column' })}
            >
              Deprecate entity
            </Button>
          )}
        </div>
      </div>
      {questionCount > 0 && (
        <p className="mt-2 text-[11px] text-danger/80">
          <AlertCircle className="mr-1 inline h-3 w-3" />
          {questionCount} question{questionCount !== 1 ? 's' : ''} will become blocked/deprecated until this entity is bound or removed.
        </p>
      )}
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export function EntityMatrixPanel({
  bindings,
  columns,
  columnOwnership,
  columnDecisions = {},
  decisions,
  dependencyGraph,
  issues = [],
  busyEntity,
  onDecide,
  onConfirmAll,
  onColumnDecide,
  onCreateEntity,
  className,
}: EntityMatrixPanelProps) {
  const [tab, setTab] = useState<MatrixTab>('dataset');
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState<'all' | 'undecided' | 'decided' | 'issues'>('all');
  const [expandedEntities, setExpandedEntities] = useState<Set<string>>(new Set());

  // Build a reverse-map: column → best-matching entity (highest confidence)
  const columnToEntity = useMemo(() => {
    const map = new Map<string, EntityBinding>();
    for (const binding of bindings) {
      const cols = Array.isArray(binding.columns) ? binding.columns : [];
      for (const bc of cols) {
        const colName = typeof bc === 'object' ? bc.column : String(bc);
        if (!colName) continue;
        const existing = map.get(colName);
        if (!existing || binding.confidence > existing.confidence) {
          map.set(colName, binding);
        }
      }
      const alts = Array.isArray(binding.alternatives) ? binding.alternatives : [];
      for (const alt of alts) {
        const altCol = typeof alt === 'object' ? alt.column : String(alt);
        if (altCol && !map.has(altCol)) {
          map.set(altCol, binding);
        }
      }
    }
    // Debug: log if map is suspiciously empty
    if (bindings.length > 0 && map.size === 0) {
      console.error('[EntityMatrixPanel] BUG: columnToEntity is EMPTY despite', bindings.length, 'bindings. First binding:', JSON.stringify(bindings[0], null, 2).slice(0, 300));
    }
    return map;
  }, [bindings]);

  // Build entity → question count from dependency graph
  const entityQuestionCount = useMemo(() => {
    const dg = dependencyGraph?.entityToQuestions ?? {};
    return Object.fromEntries(Object.entries(dg).map(([eid, qs]) => [eid, qs.length]));
  }, [dependencyGraph]);

  // Column → question count (via ownership)
  const columnQuestionCount = useMemo(() => {
    const dg = dependencyGraph;
    if (!dg) return {} as Record<string, number>;
    const map: Record<string, number> = {};
    for (const [col, entities] of Object.entries(dg.columnToEntities ?? {})) {
      const count = entities.reduce((sum, eid) => sum + (entityQuestionCount[eid] ?? 0), 0);
      map[col] = count;
    }
    return map;
  }, [dependencyGraph, entityQuestionCount]);

  // Issues per column / entity
  const issuesByColumn = useMemo(() => {
    const map: Record<string, number> = {};
    for (const issue of issues) {
      if (issue.column) map[issue.column] = (map[issue.column] ?? 0) + 1;
    }
    return map;
  }, [issues]);

  const issuesByEntity = useMemo(() => {
    const map: Record<string, number> = {};
    for (const issue of issues) {
      if (issue.entityId) map[issue.entityId] = (map[issue.entityId] ?? 0) + 1;
    }
    return map;
  }, [issues]);

  // Stats
  const totalColumns = columns.length;
  // A column is "decided" if it has a backend column_decision OR its best entity has a decision
  const decidedColumns = useMemo(() => {
    return columns.filter((col) => {
      if (columnDecisions[col.name]) return true;
      const entity = columnToEntity.get(col.name);
      if (entity) {
        const dec = decisions[entity.entityId];
        return !!dec && dec.action !== 'reopen';
      }
      return false;
    }).length;
  }, [columns, columnDecisions, columnToEntity, decisions]);

  const unmatchedEntities = useMemo(
    () => bindings.filter((b) => b.status === 'unresolved' || b.columns.length === 0),
    [bindings],
  );

  // Filter dataset columns
  const filteredColumns = useMemo(() => {
    let list = columns;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((col) => {
        const entity = columnToEntity.get(col.name);
        return (
          col.name.toLowerCase().includes(q) ||
          col.role.toLowerCase().includes(q) ||
          (entity?.entityName ?? '').toLowerCase().includes(q)
        );
      });
    }
    if (filterStatus === 'undecided') {
      list = list.filter((col) => {
        const entity = columnToEntity.get(col.name);
        if (entity) {
          const dec = decisions[entity.entityId];
          return !dec || dec.action === 'reopen';
        }
        return !columnDecisions[col.name];
      });
    } else if (filterStatus === 'decided') {
      list = list.filter((col) => {
        const entity = columnToEntity.get(col.name);
        if (entity) {
          const dec = decisions[entity.entityId];
          return dec && dec.action !== 'reopen';
        }
        return !!columnDecisions[col.name];
      });
    } else if (filterStatus === 'issues') {
      list = list.filter((col) => issuesByColumn[col.name] > 0);
    }
    return list;
  }, [columns, search, filterStatus, columnToEntity, decisions, columnDecisions, issuesByColumn]);

  // Filter template entities
  const filteredBindings = useMemo(() => {
    let list = bindings;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (b) =>
          b.entityName.toLowerCase().includes(q) ||
          b.entityType.toLowerCase().includes(q) ||
          b.columns.some((c) => c.column.toLowerCase().includes(q)),
      );
    }
    if (filterStatus === 'undecided') {
      list = list.filter((b) => {
        const dec = decisions[b.entityId];
        return !dec || dec.action === 'reopen';
      });
    } else if (filterStatus === 'decided') {
      list = list.filter((b) => {
        const dec = decisions[b.entityId];
        return dec && dec.action !== 'reopen';
      });
    } else if (filterStatus === 'issues') {
      list = list.filter((b) => (issuesByEntity[b.entityId] ?? 0) > 0);
    }
    return list;
  }, [bindings, search, filterStatus, decisions, issuesByEntity]);

  const toggleEntity = (entityId: string) => {
    setExpandedEntities((prev) => {
      const next = new Set(prev);
      if (next.has(entityId)) next.delete(entityId);
      else next.add(entityId);
      return next;
    });
  };

  return (
    <div className={cn('space-y-4', className)}>
      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Tab toggle */}
        <div className="flex rounded-xl border border-border bg-surface p-1 gap-1">
          <button
            type="button"
            onClick={() => setTab('dataset')}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors',
              tab === 'dataset' ? 'bg-primary/10 text-primary' : 'text-text-muted hover:text-text',
            )}
          >
            Column mapping
          </button>
          <button
            type="button"
            onClick={() => setTab('template')}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors',
              tab === 'template' ? 'bg-primary/10 text-primary' : 'text-text-muted hover:text-text',
            )}
          >
            Entity coverage
          </button>
        </div>

        {/* Search */}
        <div className="relative flex-1 min-w-0 max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={tab === 'dataset' ? 'Search columns or entities…' : 'Search entities…'}
            className="w-full rounded-lg border border-border bg-surface-card py-2 pl-8 pr-3 text-xs text-text outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>

        {/* Status filter */}
        <div className="flex gap-1.5">
          {(['all', 'undecided', 'decided', 'issues'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setFilterStatus(s)}
              className={cn(
                'rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors',
                filterStatus === s ? 'bg-primary/10 text-primary' : 'text-text-muted hover:text-text',
              )}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>

        {/* Stats badge row */}
        <div className="ml-auto flex items-center gap-2">
          {tab === 'dataset' ? (
            <>
              <Badge variant={decidedColumns === totalColumns ? 'success' : 'warning'}>
                {decidedColumns}/{totalColumns} columns reviewed
              </Badge>
              {unmatchedEntities.length > 0 && (
                <Badge variant="danger">{unmatchedEntities.length} unmatched entities</Badge>
              )}
            </>
          ) : (
            <>
              <Badge variant={Object.keys(decisions).length === bindings.length ? 'success' : 'warning'}>
                {Object.keys(decisions).length}/{bindings.length} entities reviewed
              </Badge>
            </>
          )}
        </div>
      </div>

      {/* ── Dataset-first tab ── */}
      {tab === 'dataset' && (
        <div className="space-y-3">
          {filteredColumns.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface px-4 py-6 text-center text-sm text-text-muted">
              No columns match your filter.
            </div>
          ) : (
            filteredColumns.map((col) => {
              const entity = columnToEntity.get(col.name) ?? null;
              const dec = entity ? (decisions[entity.entityId] ?? null) : null;
              const cdec = columnDecisions[col.name] ?? null;
              const ownerEntry = columnOwnership?.columns?.[col.name];
              const qCount = columnQuestionCount[col.name] ?? 0;
              const issueCount = issuesByColumn[col.name] ?? 0;
              return (
                <ColumnRow
                  key={col.name}
                  col={col}
                  bestEntity={entity}
                  decision={dec}
                  columnDecision={cdec}
                  ownershipEntry={ownerEntry}
                  questionCount={qCount}
                  issueCount={issueCount}
                  busy={!!(entity && busyEntity === entity.entityId)}
                  onDecide={onDecide}
                  onColumnDecide={onColumnDecide}
                  onCreateEntity={onCreateEntity}
                />
              );
            })
          )}

          {/* Unmatched entity section */}
          {unmatchedEntities.length > 0 && filterStatus === 'all' && !search && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 pt-2">
                <div className="h-px flex-1 bg-danger/20" />
                <span className="text-[11px] font-semibold uppercase tracking-wide text-danger/80">
                  Unmatched template entities
                </span>
                <div className="h-px flex-1 bg-danger/20" />
              </div>
              <div className="rounded-xl border border-danger/20 bg-danger/5 px-4 py-3 text-xs text-text-muted">
                <p className="flex items-start gap-2">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
                  These template entities have no matching dataset column. Questions depending on them will be blocked until you manually bind them or deprecate them.
                </p>
              </div>
              {unmatchedEntities.map((binding) => (
                <UnmatchedEntityRow
                  key={binding.entityId}
                  binding={binding}
                  questionCount={entityQuestionCount[binding.entityId] ?? 0}
                  decision={decisions[binding.entityId] ?? null}
                  onDecide={onDecide}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Template coverage tab ── */}
      {tab === 'template' && (
        <div className="space-y-3">
          {/* Coverage summary */}
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="rounded-lg border border-success/25 bg-success/5 px-3 py-2">
              <p className="text-[10px] uppercase text-text-muted">Matched</p>
              <p className="mt-1 font-semibold text-text">
                {bindings.filter((b) => b.status !== 'unresolved' && b.columns.length > 0).length}
              </p>
            </div>
            <div className="rounded-lg border border-warning/25 bg-warning/5 px-3 py-2">
              <p className="text-[10px] uppercase text-text-muted">Pending</p>
              <p className="mt-1 font-semibold text-text">
                {bindings.filter((b) => !decisions[b.entityId] || decisions[b.entityId].action === 'reopen').length}
              </p>
            </div>
            <div className="rounded-lg border border-danger/25 bg-danger/5 px-3 py-2">
              <p className="text-[10px] uppercase text-text-muted">Unmatched</p>
              <p className="mt-1 font-semibold text-text">{unmatchedEntities.length}</p>
            </div>
          </div>

          {filteredBindings.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface px-4 py-6 text-center text-sm text-text-muted">
              No entities match your filter.
            </div>
          ) : (
            filteredBindings.map((binding) => {
              const isExpanded = expandedEntities.has(binding.entityId);
              return (
                <div key={binding.entityId} className="rounded-xl border border-border bg-surface-card shadow-sm">
                  {/* Collapsed header */}
                  <button
                    type="button"
                    className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
                    onClick={() => toggleEntity(binding.entityId)}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-semibold text-text">{binding.entityName}</span>
                      <span className="text-[10px] text-text-muted">{binding.entityType}</span>
                      {binding.status === 'unresolved' || binding.columns.length === 0 ? (
                        <Badge variant="danger" className="text-[10px]">No match</Badge>
                      ) : decisions[binding.entityId]?.action === 'confirm' ? (
                        <Badge variant="success" className="text-[10px]">Confirmed</Badge>
                      ) : decisions[binding.entityId]?.action === 'reject' ? (
                        <Badge variant="muted" className="text-[10px]">Deprecated</Badge>
                      ) : (
                        <Badge variant="warning" className="text-[10px]">Needs review</Badge>
                      )}
                      {(issuesByEntity[binding.entityId] ?? 0) > 0 && (
                        <span className="flex items-center gap-0.5 text-[10px] text-warning">
                          <AlertTriangle className="h-3 w-3" />
                          {issuesByEntity[binding.entityId]}
                        </span>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {(entityQuestionCount[binding.entityId] ?? 0) > 0 && (
                        <span className="text-[10px] text-text-muted">
                          {entityQuestionCount[binding.entityId]} Q
                        </span>
                      )}
                      {binding.columns[0] && (
                        <span className="max-w-[7rem] truncate rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                          {binding.columns[0].column}
                        </span>
                      )}
                      {isExpanded ? <ChevronUp className="h-4 w-4 text-text-muted" /> : <ChevronDown className="h-4 w-4 text-text-muted" />}
                    </div>
                  </button>
                  {/* Expanded card */}
                  {isExpanded && (
                    <div className="border-t border-border px-4 pb-4 pt-3">
                      <EntityBindingCard
                        binding={binding}
                        columns={[]} // columns list for the override picker
                        columnOwnership={columnOwnership}
                        decided={decisions[binding.entityId]}
                        busy={busyEntity === binding.entityId}
                        onDecide={onDecide}
                      />
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
