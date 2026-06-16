'use client';

import { useState } from 'react';
import { Check, ChevronDown, GitPullRequestArrow, Pencil, RotateCcw, Share2, X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Button } from '@/components/ui/Button';
import type { BindingAction, ColumnOwner, ColumnOwnershipMap, DatasetColumnProfile, EntityBinding } from '@/lib/api';

type Decision = {
  action: BindingAction;
  columns?: string[];
  note?: string;
  force_transfer?: boolean;
  transfer_from_entity_ids?: string[];
  share_policy?: 'exclusive' | 'shared';
  share_reason?: string;
};

const STATUS_META: Record<
  EntityBinding['status'],
  { label: string; dot: string; text: string; ring: string }
> = {
  confirmed: { label: 'Confirmed', dot: 'bg-success', text: 'text-success', ring: 'ring-success/30' },
  overridden: { label: 'Overridden', dot: 'bg-primary', text: 'text-primary', ring: 'ring-primary/30' },
  rejected: { label: 'Skipped', dot: 'bg-danger', text: 'text-danger', ring: 'ring-danger/30' },
  proposed: { label: 'Needs review', dot: 'bg-warning', text: 'text-warning', ring: 'ring-warning/30' },
  unresolved: { label: 'No match', dot: 'bg-danger', text: 'text-danger', ring: 'ring-danger/30' },
};

function confidenceTone(c: number): string {
  if (c >= 0.85) return 'text-success';
  if (c >= 0.6) return 'text-warning';
  return 'text-danger';
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const tone = value >= 0.85 ? 'bg-success' : value >= 0.6 ? 'bg-warning' : 'bg-danger';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-border">
        <div className={cn('h-full rounded-full', tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn('text-xs font-semibold tabular-nums', confidenceTone(value))}>{pct}%</span>
    </div>
  );
}

function uniqueOwners(owners: ColumnOwner[]): ColumnOwner[] {
  const seen = new Set<string>();
  return owners.filter((owner) => {
    if (seen.has(owner.entityId)) return false;
    seen.add(owner.entityId);
    return true;
  });
}

function ownershipLabel(entry: ColumnOwnershipMap['columns'][string] | undefined, entityId: string): string {
  if (!entry || entry.owners.length === 0) return 'open';
  const otherOwners = uniqueOwners(entry.owners.filter((owner) => owner.entityId !== entityId));
  const exclusiveOwners = otherOwners.filter(
    (owner) => owner.sharePolicy !== 'shared' && (owner.status === 'confirmed' || owner.status === 'overridden')
  );
  if (exclusiveOwners.length > 0) return `locked by ${exclusiveOwners.map((owner) => owner.entityName || owner.entityId).join(', ')}`;
  if (otherOwners.some((owner) => owner.sharePolicy === 'shared')) return 'shared';
  if (otherOwners.length > 0) return `${otherOwners.length} proposal claim${otherOwners.length === 1 ? '' : 's'}`;
  return entry.locked ? 'locked by this entity' : 'selected here';
}

interface EntityBindingCardProps {
  binding: EntityBinding;
  /** All dataset column names, for the override picker. */
  columns: DatasetColumnProfile[];
  /** Live column ownership from the review record; proposed claims are visible, locks are reviewed-only. */
  columnOwnership?: ColumnOwnershipMap;
  /** Current human decision for this entity, if any. */
  decided?: Decision;
  busy?: boolean;
  onDecide: (entityId: string, decision: Decision) => void;
  className?: string;
}

/**
 * One reviewable entity → column mapping. Humans confirm the proposal, override
 * with a different column, or skip it. The current decision is reflected inline.
 */
export function EntityBindingCard({
  binding,
  columns,
  columnOwnership,
  decided,
  busy,
  onDecide,
  className,
}: EntityBindingCardProps) {
  const [overriding, setOverriding] = useState(false);
  const [conflictColumn, setConflictColumn] = useState<string | null>(null);
  const [shareReason, setShareReason] = useState('');

  const effectiveStatus = decided
    ? decided.action === 'confirm'
      ? 'confirmed'
      : decided.action === 'override' || decided.action === 'share'
        ? 'overridden'
        : decided.action === 'reject'
          ? 'rejected'
          : binding.status
    : binding.status;
  const meta = STATUS_META[effectiveStatus] ?? STATUS_META.proposed;

  const proposedColumn = binding.columns[0]?.column ?? null;
  const overrideColumn = decided?.action === 'override' || decided?.action === 'share' ? decided.columns?.[0] : undefined;
  const shownColumn = overrideColumn ?? proposedColumn;
  const isResolved = !!decided && decided.action !== 'reopen';
  const shownOwnership = shownColumn ? columnOwnership?.columns?.[shownColumn] : undefined;
  const conflictEntry = conflictColumn ? columnOwnership?.columns?.[conflictColumn] : undefined;
  const lockedOwners = uniqueOwners(
    (conflictEntry?.owners ?? []).filter(
      (owner) =>
        owner.entityId !== binding.entityId &&
        owner.sharePolicy !== 'shared' &&
        (owner.status === 'confirmed' || owner.status === 'overridden')
    )
  );

  const handleConfirm = () => onDecide(binding.entityId, { action: 'confirm' });
  const handleReject = () => onDecide(binding.entityId, { action: 'reject' });
  const handleOverride = (column: string, forceTransfer = false) => {
    const owners = uniqueOwners(
      (columnOwnership?.columns?.[column]?.owners ?? []).filter(
        (owner) =>
          owner.entityId !== binding.entityId &&
          owner.sharePolicy !== 'shared' &&
          (owner.status === 'confirmed' || owner.status === 'overridden')
      )
    );
    if (owners.length > 0 && !forceTransfer) {
      setConflictColumn(column);
      setShareReason('');
      return;
    }
    onDecide(binding.entityId, {
      action: 'override',
      columns: [column],
      ...(forceTransfer
        ? {
            force_transfer: true,
            transfer_from_entity_ids: owners.map((owner) => owner.entityId),
            note: `column ownership transferred to ${binding.entityName || binding.entityId}`,
          }
        : {}),
    });
    setConflictColumn(null);
    setOverriding(false);
  };
  const handleShare = (column: string) => {
    const reason = shareReason.trim();
    if (!reason) return;
    onDecide(binding.entityId, {
      action: 'share',
      columns: [column],
      share_policy: 'shared',
      share_reason: reason,
      note: reason,
    });
    setConflictColumn(null);
    setShareReason('');
    setOverriding(false);
  };

  return (
    <div
      className={cn(
        'rounded-xl border bg-surface-card p-4 shadow-sm transition-all',
        isResolved ? cn('border-border ring-1', meta.ring) : 'border-border',
        className
      )}
    >
      {/* header: entity + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="truncate text-sm font-semibold text-text">{binding.entityName}</h4>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
              {binding.entityType}
            </span>
          </div>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {binding.cardinality} · matched via {binding.method}
          </p>
        </div>
        <span className={cn('inline-flex shrink-0 items-center gap-1.5 text-xs font-medium', meta.text)}>
          <span className={cn('h-2 w-2 rounded-full', meta.dot)} aria-hidden />
          {meta.label}
        </span>
      </div>

      {/* mapping */}
      <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-3 py-2.5">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            {overrideColumn ? 'Mapped to (your choice)' : 'Proposed column'}
          </p>
          {shownColumn ? (
            <p className="truncate font-mono text-sm font-semibold text-text">{shownColumn}</p>
          ) : (
            <p className="text-sm text-text-muted">No column matched</p>
          )}
          {shownColumn && (
            <p className="mt-1 text-[11px] text-text-muted">
              Ownership: {ownershipLabel(shownOwnership, binding.entityId)}
            </p>
          )}
        </div>
        {!overrideColumn && binding.columns[0] && <ConfidenceBar value={binding.confidence} />}
      </div>

      {/* override picker */}
      {overriding ? (
        <div className="mt-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
          <p className="mb-2 text-xs font-medium text-text">Choose the correct column</p>
          <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
            {columns.map((col) => {
              const alt = binding.alternatives.find((a) => a.column === col.name);
              const isProposed = col.name === proposedColumn;
              return (
                <button
                  key={col.name}
                  type="button"
                  onClick={() => handleOverride(col.name)}
                  className="flex w-full items-center justify-between gap-2 rounded-md border border-transparent px-2.5 py-1.5 text-left text-sm hover:border-border hover:bg-surface-card"
                >
                  <span className="min-w-0">
                    <span className="font-mono text-xs text-text">{col.name}</span>
                    <span className="ml-2 text-[11px] capitalize text-text-muted">{col.role}</span>
                    {isProposed && (
                      <span className="ml-2 text-[10px] font-medium uppercase text-primary">proposed</span>
                    )}
                    <span className="ml-2 text-[10px] font-medium uppercase text-text-muted">
                      {ownershipLabel(columnOwnership?.columns?.[col.name], binding.entityId)}
                    </span>
                  </span>
                  {alt && (
                    <span className={cn('text-[11px] font-semibold tabular-nums', confidenceTone(alt.confidence))}>
                      {Math.round(alt.confidence * 100)}%
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {conflictColumn && lockedOwners.length > 0 && (
            <div className="mt-3 rounded-lg border border-warning/40 bg-warning/5 p-3">
              <p className="text-xs font-semibold text-text">Column already has an exclusive owner</p>
              <p className="mt-1 text-xs text-text-muted">
                {conflictColumn} is locked by {lockedOwners.map((owner) => owner.entityName || owner.entityId).join(', ')}.
                Choose audited sharing or transfer the column.
              </p>
              <textarea
                value={shareReason}
                onChange={(event) => setShareReason(event.target.value)}
                rows={2}
                placeholder="Required reason for shared ownership"
                className="mt-2 w-full rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none focus:ring-2 focus:ring-accent/30"
              />
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || !shareReason.trim()}
                  onClick={() => handleShare(conflictColumn)}
                >
                  <Share2 className="h-4 w-4" aria-hidden /> Share with reason
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => handleOverride(conflictColumn, true)}
                  className="text-warning"
                >
                  <GitPullRequestArrow className="h-4 w-4" aria-hidden /> Force transfer
                </Button>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => {
              setOverriding(false);
              setConflictColumn(null);
            }}
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-text-muted hover:text-text"
          >
            <ChevronDown className="h-3.5 w-3.5" aria-hidden /> Close
          </button>
        </div>
      ) : null}

      {/* actions */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {isResolved ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onDecide(binding.entityId, { action: 'reopen' })}
            className="text-text-muted"
            title="Re-open this binding for review"
          >
            <RotateCcw className="h-4 w-4" aria-hidden /> Change
          </Button>
        ) : (
          <>
            <Button
              variant="primary"
              size="sm"
              disabled={busy || !proposedColumn}
              onClick={handleConfirm}
            >
              <Check className="h-4 w-4" aria-hidden /> Confirm
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || columns.length === 0}
              onClick={() => setOverriding((v) => !v)}
            >
              <Pencil className="h-4 w-4" aria-hidden /> Override
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={handleReject} className="text-text-muted">
              <X className="h-4 w-4" aria-hidden /> Skip
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

export default EntityBindingCard;
