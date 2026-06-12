'use client';

/**
 * R3 — provenance slide-over. Click a measured value → see the evidence chain
 * (question → component → analytics → row ids) that produced it. Read-only;
 * editing/locking arrives in R5.
 */
import { X } from 'lucide-react';

import type { Provenance } from '@/lib/report/types';

export interface ProvenanceTarget {
  label: string;
  value: string;
  rowIds?: string[];
  provenance?: Provenance;
}

interface Props {
  target: ProvenanceTarget | null;
  onClose: () => void;
}

function evidenceRefs(p?: Provenance): string[] {
  if (!p) return [];
  const ev = p.evidenceRef;
  if (Array.isArray(ev)) return ev;
  return ev ? [ev] : [];
}

export function ProvenanceDrawer({ target, onClose }: Props) {
  if (!target) return null;
  const p = target.provenance;
  const refs = evidenceRefs(p);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden />
      <aside className="relative h-full w-full max-w-sm overflow-y-auto border-l border-border bg-surface p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">Provenance</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-text-muted hover:bg-border/40"
            aria-label="Close provenance"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <dl className="space-y-3 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-text-muted">Value</dt>
            <dd className="font-medium text-text">
              {target.label}: <span className="tabular-nums">{target.value}</span>
            </dd>
          </div>
          {p?.questionId && (
            <Field label="Question" value={p.questionId} />
          )}
          {p?.componentId && <Field label="Component" value={p.componentId} />}
          {p?.analyticsRef && <Field label="Analytics" value={p.analyticsRef} />}
          {refs.length > 0 && <Field label="Evidence" value={refs.join(', ')} />}
          {target.rowIds && target.rowIds.length > 0 && (
            <div>
              <dt className="text-xs uppercase tracking-wide text-text-muted">Row IDs</dt>
              <dd className="flex flex-wrap gap-1">
                {target.rowIds.map((id) => (
                  <code
                    key={id}
                    className="rounded bg-border/40 px-1.5 py-0.5 text-xs text-text"
                  >
                    {id}
                  </code>
                ))}
              </dd>
            </div>
          )}
          {!p && (!target.rowIds || target.rowIds.length === 0) && (
            <p className="text-text-muted">No provenance recorded for this value.</p>
          )}
        </dl>
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-text-muted">{label}</dt>
      <dd className="break-words text-text">{value}</dd>
    </div>
  );
}
