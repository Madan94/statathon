'use client';

import { useState } from 'react';
import { AlertTriangle, ArrowRight, Plus, X } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';

export interface ColumnConflict {
  column: string;
  owners: Array<{ entityId: string; entityName?: string; sharePolicy?: string }>;
}

export interface ConflictResolution {
  mode: 'transfer' | 'share' | 'create_new';
  shareReason?: string;
  newEntityName?: string;
  newEntityType?: 'dimension' | 'measure' | 'time' | 'filter' | 'metadata';
}

interface ConflictResolutionModalProps {
  open: boolean;
  entityId: string;
  entityName: string;
  conflicts: ColumnConflict[];
  onResolve: (resolution: ConflictResolution) => void;
  onCancel: () => void;
}

export function ConflictResolutionModal({
  open,
  entityId,
  entityName,
  conflicts,
  onResolve,
  onCancel,
}: ConflictResolutionModalProps) {
  const [mode, setMode] = useState<ConflictResolution['mode']>('transfer');
  const [shareReason, setShareReason] = useState('');
  const [newEntityName, setNewEntityName] = useState('');
  const [newEntityType, setNewEntityType] = useState<'dimension' | 'measure' | 'time' | 'filter' | 'metadata'>('dimension');

  if (!open) return null;

  const conflictColumns = conflicts.map((c) => c.column);
  const existingOwners = conflicts.flatMap((c) => c.owners).filter((o, i, arr) =>
    arr.findIndex((x) => x.entityId === o.entityId) === i
  );

  const canApply = mode === 'transfer'
    || (mode === 'share' && shareReason.trim().length > 0)
    || (mode === 'create_new' && newEntityName.trim().length > 0);

  const handleApply = () => {
    onResolve({
      mode,
      shareReason: mode === 'share' ? shareReason.trim() : undefined,
      newEntityName: mode === 'create_new' ? newEntityName.trim() : undefined,
      newEntityType: mode === 'create_new' ? newEntityType : undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onCancel}>
      <div
        className="relative w-[min(92vw,32rem)] rounded-2xl border border-border bg-surface-card p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="flex gap-3">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-warning/10">
              <AlertTriangle className="h-5 w-5 text-warning" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-text">Column ownership conflict</h3>
              <p className="mt-1 text-sm text-text-muted">
                <span className="font-medium text-text">{entityName || entityId}</span> claims column{conflictColumns.length > 1 ? 's' : ''}{' '}
                already assigned to another entity.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md p-1.5 text-text-muted hover:bg-border/60 hover:text-text"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Conflict details */}
        <div className="mb-5 rounded-lg border border-warning/20 bg-warning/5 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Conflicting columns</p>
          <div className="mt-2 space-y-1.5">
            {conflicts.map((conflict) => (
              <div key={conflict.column} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate font-mono text-text">{conflict.column}</span>
                <span className="flex items-center gap-1.5">
                  <ArrowRight className="h-3 w-3 text-text-muted" />
                  {conflict.owners.map((owner) => (
                    <Badge key={owner.entityId} variant="muted">{owner.entityName || owner.entityId}</Badge>
                  ))}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Resolution options */}
        <div className="mb-5 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Choose resolution</p>

          {/* Transfer */}
          <label className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${mode === 'transfer' ? 'border-primary bg-primary/5' : 'border-border hover:border-accent/50'}`}>
            <input
              type="radio"
              name="conflict-mode"
              value="transfer"
              checked={mode === 'transfer'}
              onChange={() => setMode('transfer')}
              className="mt-0.5"
            />
            <div>
              <p className="text-sm font-semibold text-text">Reassign to this entity</p>
              <p className="mt-0.5 text-xs text-text-muted">
                Remove from{' '}
                {existingOwners.map((o) => o.entityName || o.entityId).join(', ')} and transfer to{' '}
                <span className="font-medium">{entityName || entityId}</span>.
              </p>
            </div>
          </label>

          {/* Share */}
          <label className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${mode === 'share' ? 'border-primary bg-primary/5' : 'border-border hover:border-accent/50'}`}>
            <input
              type="radio"
              name="conflict-mode"
              value="share"
              checked={mode === 'share'}
              onChange={() => setMode('share')}
              className="mt-0.5"
            />
            <div className="flex-1">
              <p className="text-sm font-semibold text-text">Share across both entities</p>
              <p className="mt-0.5 text-xs text-text-muted">Allow multiple entities to use this column.</p>
              {mode === 'share' && (
                <input
                  value={shareReason}
                  onChange={(e) => setShareReason(e.target.value)}
                  placeholder="Reason for sharing (required)"
                  className="mt-2 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-primary/30"
                  autoFocus
                />
              )}
            </div>
          </label>

          {/* Create new */}
          <label className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${mode === 'create_new' ? 'border-primary bg-primary/5' : 'border-border hover:border-accent/50'}`}>
            <input
              type="radio"
              name="conflict-mode"
              value="create_new"
              checked={mode === 'create_new'}
              onChange={() => setMode('create_new')}
              className="mt-0.5"
            />
            <div className="flex-1">
              <p className="text-sm font-semibold text-text">Create a new entity instead</p>
              <p className="mt-0.5 text-xs text-text-muted">Leave the existing binding alone and create a fresh entity for this column.</p>
              {mode === 'create_new' && (
                <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto]">
                  <input
                    value={newEntityName}
                    onChange={(e) => setNewEntityName(e.target.value)}
                    placeholder="New entity name"
                    className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-primary/30"
                    autoFocus
                  />
                  <select
                    value={newEntityType}
                    onChange={(e) => setNewEntityType(e.target.value as typeof newEntityType)}
                    className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none"
                  >
                    <option value="dimension">Dimension</option>
                    <option value="measure">Measure</option>
                    <option value="time">Time</option>
                    <option value="filter">Filter</option>
                    <option value="metadata">Metadata</option>
                  </select>
                </div>
              )}
            </div>
          </label>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
          <Button size="sm" disabled={!canApply} onClick={handleApply}>
            {mode === 'transfer' && <><ArrowRight className="h-4 w-4" /> Reassign</>}
            {mode === 'share' && <><Plus className="h-4 w-4" /> Share</>}
            {mode === 'create_new' && <><Plus className="h-4 w-4" /> Create & assign</>}
          </Button>
        </div>
      </div>
    </div>
  );
}
