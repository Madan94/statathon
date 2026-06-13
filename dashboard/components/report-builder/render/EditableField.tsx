'use client';

/**
 * R5 — inline editable field. Text edits commit directly; numbers are "locked"
 * and open an override form that requires a reason before committing (the server
 * flags the value `overridden` and writes an audit entry). An "overridden" badge
 * marks values a human has changed.
 */
import { useState } from 'react';
import { Check, Loader2, Lock, Pencil, X } from 'lucide-react';

export interface EditableFieldProps {
  value: string | number;
  kind?: 'text' | 'number';
  display?: string;
  overridden?: boolean;
  multiline?: boolean;
  className?: string;
  onCommit: (value: string | number, reason?: string) => Promise<void>;
}

export function EditableField({
  value,
  kind = 'text',
  display,
  overridden,
  multiline,
  className,
  onCommit,
}: EditableFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value ?? ''));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = () => {
    setDraft(String(value ?? ''));
    setReason('');
    setError(null);
    setEditing(true);
  };

  const commit = async () => {
    if (kind === 'number' && !reason.trim()) {
      setError('A reason is required to override a number.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = kind === 'number' ? Number(draft) : draft;
      if (kind === 'number' && Number.isNaN(next as number)) {
        setError('Enter a valid number.');
        return;
      }
      await onCommit(next, kind === 'number' ? reason.trim() : undefined);
      setEditing(false);
    } catch {
      setError('Save failed — try again.');
    } finally {
      setBusy(false);
    }
  };

  if (!editing) {
    return (
      <span className={`group inline-flex items-center gap-1 ${className ?? ''}`}>
        <span>{display ?? String(value ?? '')}</span>
        {overridden && (
          <span
            className="rounded bg-warning/15 px-1 text-[10px] font-medium text-warning"
            title="Overridden by a reviewer"
          >
            overridden
          </span>
        )}
        <button
          type="button"
          onClick={open}
          className="opacity-0 transition group-hover:opacity-100"
          aria-label="Edit"
          title={kind === 'number' ? 'Override (reason required)' : 'Edit'}
        >
          {kind === 'number' ? (
            <Lock className="h-3 w-3 text-text-muted" />
          ) : (
            <Pencil className="h-3 w-3 text-text-muted" />
          )}
        </button>
      </span>
    );
  }

  return (
    <span className="inline-flex flex-col gap-1 rounded-md border border-accent/40 bg-surface p-2 align-top shadow-sm">
      {multiline ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          className="w-72 rounded border border-border bg-surface px-2 py-1 text-sm text-text"
          autoFocus
        />
      ) : (
        <input
          type={kind === 'number' ? 'number' : 'text'}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-44 rounded border border-border bg-surface px-2 py-1 text-sm text-text tabular-nums"
          autoFocus
        />
      )}
      {kind === 'number' && (
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason for override (required)"
          className="w-72 rounded border border-border bg-surface px-2 py-1 text-xs text-text"
        />
      )}
      {error && <span className="text-xs text-danger">{error}</span>}
      <span className="flex items-center gap-1">
        <button
          type="button"
          onClick={commit}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded bg-accent px-2 py-0.5 text-xs font-medium text-white disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
          Save
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-text-muted"
        >
          <X className="h-3 w-3" /> Cancel
        </button>
      </span>
    </span>
  );
}
