'use client';

import { X } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';

interface MethodScore {
  method: string;
  score: number;
  reason?: string;
}

interface Props {
  open: boolean;
  column: string;
  method: string;
  confidence?: number;
  reason?: string;
  scores: MethodScore[];
  onClose: () => void;
}

export default function ImputationDetailDrawer({
  open,
  column,
  method,
  confidence,
  reason,
  scores,
  onClose,
}: Props) {
  if (!open) return null;
  const recommended = scores.find((s) => s.method === method);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button type="button" className="absolute inset-0 bg-black/40" onClick={onClose} aria-label="Close" />
      <aside className="relative w-full max-w-md bg-surface-card border-l border-border shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-surface-card border-b border-border px-5 py-4 flex items-center justify-between">
          <h3 className="font-semibold text-text">Imputation explainability</h3>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-border/50"><X className="h-5 w-5" /></button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          <section><p className="text-xs uppercase text-text-muted mb-1">Column</p><p className="font-medium">{column}</p></section>
          <section>
            <p className="text-xs uppercase text-text-muted mb-1">Recommended</p>
            <Badge variant="success" className="capitalize">{method}</Badge>
            {confidence != null && <span className="ml-2 text-xs">Confidence: {(confidence * 100).toFixed(0)}%</span>}
          </section>
          {reason && (
            <section><p className="text-xs uppercase text-text-muted mb-1">Why selected</p><p className="text-text-muted">{reason}</p></section>
          )}
          <section>
            <p className="text-xs uppercase text-text-muted mb-2">Method comparison</p>
            <div className="space-y-2">
              {scores.map((s) => (
                <div key={s.method} className={`rounded border p-2 ${s.method === method ? 'border-success bg-success/5' : 'border-border'}`}>
                  <div className="flex justify-between capitalize font-medium">
                    <span>{s.method}</span>
                    <span>{(s.score * 100).toFixed(0)}%</span>
                  </div>
                  {s.reason && <p className="text-xs text-text-muted mt-1">{s.reason}</p>}
                  {s.method !== method && <p className="text-[10px] text-text-muted mt-1">Rejected: lower suitability score</p>}
                </div>
              ))}
            </div>
          </section>
          {recommended?.reason && (
            <section>
              <p className="text-xs uppercase text-text-muted mb-1">{method} chosen because</p>
              <ul className="list-disc pl-4 text-text-muted space-y-1">
                <li>{recommended.reason}</li>
                <li>Lowest expected bias among scored methods</li>
                <li>Highest confidence score for this column</li>
              </ul>
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
