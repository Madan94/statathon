'use client';

import { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleDashed, Search, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EntityBindingCard } from '@/components/report-builder/binding/EntityBindingCard';
import type {
  BindingAction,
  BindingDependencyGraph,
  BindingWorkspaceIssue,
  ColumnOwnershipMap,
  DatasetColumnProfile,
  EntityBinding,
} from '@/lib/api';

export type EntityDecision = {
  action: BindingAction;
  columns?: string[];
  note?: string;
  force_transfer?: boolean;
  transfer_from_entity_ids?: string[];
  share_policy?: 'exclusive' | 'shared';
  share_reason?: string;
};

interface EntityMatrixPanelProps {
  bindings: EntityBinding[];
  columns: DatasetColumnProfile[];
  columnOwnership?: ColumnOwnershipMap;
  decisions: Record<string, EntityDecision>;
  dependencyGraph?: BindingDependencyGraph;
  issues?: BindingWorkspaceIssue[];
  initialEntityId?: string | null;
  busyEntity?: string | null;
  onDecide: (entityId: string, decision: EntityDecision) => void;
  onConfirmAll: () => void;
}

function effectiveStatus(binding: EntityBinding, decision?: EntityDecision): EntityBinding['status'] {
  if (!decision) return binding.status;
  if (decision.action === 'confirm') return 'confirmed';
  if (decision.action === 'override' || decision.action === 'share') return 'overridden';
  if (decision.action === 'reject') return 'rejected';
  return binding.status;
}

function statusVariant(status: EntityBinding['status']): 'success' | 'warning' | 'danger' | 'muted' {
  if (status === 'confirmed' || status === 'overridden') return 'success';
  if (status === 'proposed') return 'warning';
  if (status === 'rejected' || status === 'unresolved') return 'danger';
  return 'muted';
}

function statusIcon(status: EntityBinding['status']) {
  if (status === 'confirmed' || status === 'overridden') return CheckCircle2;
  if (status === 'rejected' || status === 'unresolved') return XCircle;
  if (status === 'proposed') return CircleDashed;
  return AlertTriangle;
}

function confidenceVariant(confidence: number): 'success' | 'warning' | 'danger' {
  if (confidence >= 0.85) return 'success';
  if (confidence >= 0.6) return 'warning';
  return 'danger';
}

function selectedColumn(binding: EntityBinding, decision?: EntityDecision): string {
  if ((decision?.action === 'override' || decision?.action === 'share') && decision.columns?.[0]) return decision.columns[0];
  return binding.columns[0]?.column || '';
}

function issueCountFor(binding: EntityBinding, issues: BindingWorkspaceIssue[]): number {
  return issues.filter((issue) => issue.entityId === binding.entityId).length + (binding.risks?.length || 0);
}

export function EntityMatrixPanel({
  bindings,
  columns,
  columnOwnership,
  decisions,
  dependencyGraph,
  issues = [],
  initialEntityId,
  busyEntity,
  onDecide,
  onConfirmAll,
}: EntityMatrixPanelProps) {
  const [query, setQuery] = useState('');
  const [selectedEntityId, setSelectedEntityId] = useState(initialEntityId || bindings[0]?.entityId || '');

  const filteredBindings = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return bindings;
    return bindings.filter((binding) => {
      const haystack = [
        binding.entityId,
        binding.entityName,
        binding.entityType,
        selectedColumn(binding, decisions[binding.entityId]),
        ...(dependencyGraph?.entityToQuestions[binding.entityId] || []),
        ...(dependencyGraph?.entityToComponents[binding.entityId] || []),
      ].join(' ').toLowerCase();
      return haystack.includes(needle);
    });
  }, [bindings, decisions, dependencyGraph, query]);

  const selectedBinding = bindings.find((binding) => binding.entityId === selectedEntityId) || filteredBindings[0] || bindings[0];
  const pendingCount = bindings.filter((binding) => !decisions[binding.entityId]).length;
  const confirmedCount = bindings.length - pendingCount;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card className="p-4" title="Entity-column matrix" description="Review impact, confidence, ownership, and downstream usage before confirming.">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2 text-xs">
            <Badge variant={pendingCount === 0 ? 'success' : 'warning'}>{confirmedCount}/{bindings.length} reviewed</Badge>
            <Badge variant="muted">{columns.length} dataset columns</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs text-text-muted">
              <Search className="h-3.5 w-3.5" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find entity, column, question"
                className="w-44 bg-transparent text-text outline-none placeholder:text-text-muted"
              />
            </label>
            <Button variant="outline" size="sm" onClick={onConfirmAll} disabled={!!busyEntity || pendingCount === 0}>
              Confirm remaining
            </Button>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-border">
          <div className="grid grid-cols-[1.35fr_0.9fr_0.7fr_0.55fr_0.55fr_0.55fr] gap-2 border-b border-border bg-surface px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            <span>Entity</span>
            <span>Column</span>
            <span>Status</span>
            <span>Confidence</span>
            <span>Used by</span>
            <span>Issues</span>
          </div>
          <div className="max-h-[34rem] overflow-auto">
            {filteredBindings.map((binding) => {
              const decision = decisions[binding.entityId];
              const status = effectiveStatus(binding, decision);
              const StatusIcon = statusIcon(status);
              const column = selectedColumn(binding, decision);
              const questions = dependencyGraph?.entityToQuestions[binding.entityId] || [];
              const components = dependencyGraph?.entityToComponents[binding.entityId] || [];
              const issueCount = issueCountFor(binding, issues);
              const selected = selectedBinding?.entityId === binding.entityId;
              return (
                <button
                  key={binding.entityId}
                  type="button"
                  onClick={() => setSelectedEntityId(binding.entityId)}
                  className={`grid w-full grid-cols-[1.35fr_0.9fr_0.7fr_0.55fr_0.55fr_0.55fr] gap-2 border-b border-border px-3 py-2 text-left text-xs transition-colors last:border-b-0 ${selected ? 'bg-primary/5' : 'bg-surface-card hover:bg-surface'}`}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold text-text">{binding.entityName || binding.entityId}</span>
                    <span className="block truncate font-mono text-[11px] text-text-muted">{binding.entityId} · {binding.entityType}</span>
                  </span>
                  <span className="min-w-0 self-center">
                    {column ? <span className="block truncate font-mono text-text">{column}</span> : <span className="text-text-muted">No match</span>}
                  </span>
                  <span className="flex items-center gap-1 self-center">
                    <StatusIcon className="h-3.5 w-3.5 text-text-muted" />
                    <Badge variant={statusVariant(status)}>{status}</Badge>
                  </span>
                  <span className="self-center">
                    <Badge variant={confidenceVariant(binding.confidence)}>{Math.round(binding.confidence * 100)}%</Badge>
                  </span>
                  <span className="self-center text-text-muted">{questions.length} q / {components.length} c</span>
                  <span className="self-center">
                    {issueCount ? <Badge variant="warning">{issueCount}</Badge> : <Badge variant="muted">0</Badge>}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </Card>

      <div className="space-y-4">
        {selectedBinding ? (
          <>
            <Card className="p-4" title="Impact" description="Downstream objects affected by this entity.">
              <div className="space-y-3 text-xs">
                <div>
                  <p className="font-semibold uppercase tracking-wide text-text-muted">Questions</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {(dependencyGraph?.entityToQuestions[selectedBinding.entityId] || []).length ? (
                      (dependencyGraph?.entityToQuestions[selectedBinding.entityId] || []).map((questionId) => (
                        <span key={questionId} className="rounded bg-border px-2 py-0.5 font-mono text-text-muted">{questionId}</span>
                      ))
                    ) : <span className="text-text-muted">No linked questions yet.</span>}
                  </div>
                </div>
                <div>
                  <p className="font-semibold uppercase tracking-wide text-text-muted">Components</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {(dependencyGraph?.entityToComponents[selectedBinding.entityId] || []).length ? (
                      (dependencyGraph?.entityToComponents[selectedBinding.entityId] || []).map((componentId) => (
                        <span key={componentId} className="rounded bg-border px-2 py-0.5 font-mono text-text-muted">{componentId}</span>
                      ))
                    ) : <span className="text-text-muted">No linked components yet.</span>}
                  </div>
                </div>
              </div>
            </Card>
            <EntityBindingCard
              binding={selectedBinding}
              columns={columns}
              columnOwnership={columnOwnership}
              decided={decisions[selectedBinding.entityId]}
              busy={busyEntity === selectedBinding.entityId}
              onDecide={onDecide}
            />
          </>
        ) : (
          <Card className="p-4" title="Entity inspector" description="Select a row to review the match.">
            <p className="text-sm text-text-muted">No entity selected.</p>
          </Card>
        )}
      </div>
    </div>
  );
}

export default EntityMatrixPanel;
