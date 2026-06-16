'use client';

import { useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Lock, Pencil, RotateCcw, Share2, X } from 'lucide-react';
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

interface EntityBindingCardProps {
  binding: EntityBinding;
  /** All dataset column names, for the override picker. */
  columns: DatasetColumnProfile[];
  /** Global column ownership map, used to show locks and controlled reassignments. */
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
  const [pendingConflict, setPendingConflict] = useState<{ column: string; owners: ColumnOwner[] } | null>(null);
  const [shareReason, setShareReason] = useState('');

  const effectiveStatus = decided
    ? decided.action === 'confirm'
      ? 'confirmed'
      : decided.action === 'override'
        ? 'overridden'
        : decided.action === 'share'
          ? 'overridden'
          : 'rejected'
    : binding.status;
  const meta = STATUS_META[effectiveStatus] ?? STATUS_META.proposed;

  const proposedColumn = binding.columns[0]?.column ?? null;
  const overrideColumn = decided?.action === 'override' || decided?.action === 'share' ? decided.columns?.[0] : undefined;
  const shownColumn = overrideColumn ?? proposedColumn;
  const isResolved = !!decided;

  const ownersFor = (column: string): ColumnOwner[] => {
    const owners = columnOwnership?.columns?.[column]?.owners ?? [];
    return owners.filter(
      (owner) => owner.entityId !== binding.entityId && owner.status !== 'rejected'
    );
  };

  const blockingOwnersFor = (column: string): ColumnOwner[] => {
    return ownersFor(column).filter(
      (owner) => ['confirmed', 'overridden'].includes(owner.status) && owner.sharePolicy !== 'shared'
    );
  };

  const handleConflict = (column: string, owners: ColumnOwner[]) => {
    setShareReason('');
    setPendingConflict({ column, owners });
  };

  const handleConfirm = () => {
    if (proposedColumn) {
      const owners = blockingOwnersFor(proposedColumn);
      if (owners.length > 0) {
        handleConflict(proposedColumn, owners);
        return;
      }
    }
    onDecide(binding.entityId, { action: 'confirm' });
  };
  const handleReject = () => onDecide(binding.entityId, { action: 'reject' });
  const handleOverride = (column: string) => {
    const owners = blockingOwnersFor(column);
    if (owners.length > 0) {
      handleConflict(column, owners);
      return;
    }
    onDecide(binding.entityId, { action: 'override', columns: [column] });
    setOverriding(false);
  };

  const handleMoveColumn = () => {
    if (!pendingConflict) return;
    onDecide(binding.entityId, {
      action: 'override',
      columns: [pendingConflict.column],
      force_transfer: true,
      transfer_from_entity_ids: pendingConflict.owners.map((owner) => owner.entityId),
      note: `Moved from ${pendingConflict.owners.map((owner) => owner.entityName).join(', ')}`,
    });
    setPendingConflict(null);
    setOverriding(false);
  };

  const handleShareColumn = () => {
    if (!pendingConflict || !shareReason.trim()) return;
    onDecide(binding.entityId, {
      action: 'share',
      columns: [pendingConflict.column],
      share_policy: 'shared',
      share_reason: shareReason.trim(),
    });
    setPendingConflict(null);
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
              const owners = ownersFor(col.name);
              const blockingOwners = blockingOwnersFor(col.name);
              const isLocked = blockingOwners.length > 0;
              const sharedOwners = owners.filter((owner) => owner.sharePolicy === 'shared');
              return (
                <button
                  key={col.name}
                  type="button"
                  onClick={() => handleOverride(col.name)}
                  className={cn(
                    'flex w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-sm transition-colors hover:border-border hover:bg-surface-card',
                    isLocked ? 'border-warning/30 bg-warning/5' : 'border-transparent'
                  )}
                >
                  <span className="min-w-0">
                    <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                      {isLocked && <Lock className="h-3.5 w-3.5 text-warning" aria-hidden />}
                      {!isLocked && sharedOwners.length > 0 && <Share2 className="h-3.5 w-3.5 text-primary" aria-hidden />}
                      <span className="font-mono text-xs text-text">{col.name}</span>
                      <span className="text-[11px] capitalize text-text-muted">{col.role}</span>
                      {isProposed && (
                        <span className="text-[10px] font-medium uppercase text-primary">proposed</span>
                      )}
                    </span>
                    {owners.length > 0 && (
                      <span className="mt-0.5 block truncate text-[11px] text-text-muted">
                        {isLocked ? 'Locked by ' : 'Shared with '}
                        {owners.map((owner) => owner.entityName).join(', ')}
                      </span>
                    )}
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
          {pendingConflict && (
            <div className="mt-3 rounded-lg border border-warning/40 bg-warning/10 p-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-text">Column already allocated</p>
                  <p className="mt-1 text-xs text-text-muted">
                    <span className="font-mono text-text">{pendingConflict.column}</span> is assigned to{' '}
                    {pendingConflict.owners.map((owner) => owner.entityName).join(', ')}.
                  </p>
                </div>
              </div>
              <textarea
                value={shareReason}
                onChange={(e) => setShareReason(e.target.value)}
                placeholder="Reason for sharing this column"
                className="mt-3 h-16 w-full resize-none rounded-md border border-border bg-surface px-2.5 py-2 text-xs text-text outline-none focus:ring-2 focus:ring-accent/30"
              />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button size="sm" disabled={busy} onClick={handleMoveColumn}>
                  Move column
                </Button>
                <Button variant="outline" size="sm" disabled={busy || !shareReason.trim()} onClick={handleShareColumn}>
                  Share with reason
                </Button>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => setPendingConflict(null)} className="text-text-muted">
                  Cancel
                </Button>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setOverriding(false)}
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
