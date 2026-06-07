'use client';

import { X } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import type { AnalysisResult, AnomalyCandidate, AnomalyExplain } from '@/lib/api';
import { cn } from '@/lib/cn';

interface Props {
  candidate: AnomalyCandidate | null;
  column: string;
  methodLabel: string;
  domain?: string;
  cluster?: string;
  onClose: () => void;
}

function explainOf(c: AnomalyCandidate): AnomalyExplain | null {
  return typeof c.explain === 'object' ? (c.explain as AnomalyExplain) : null;
}

export default function AnomalyDetailDrawer({
  candidate,
  column,
  methodLabel,
  domain,
  cluster,
  onClose,
}: Props) {
  if (!candidate) return null;
  const explain = explainOf(candidate);
  const conf = candidate.confidence != null ? Math.round(candidate.confidence * 100) : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button type="button" className="absolute inset-0 bg-black/40" onClick={onClose} aria-label="Close" />
      <aside className="relative w-full max-w-md bg-surface-card border-l border-border shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-surface-card border-b border-border px-5 py-4 flex items-center justify-between">
          <h3 className="font-semibold text-text">Anomaly details</h3>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-border/50" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          <section><p className="text-xs uppercase text-text-muted mb-1">Column</p><p className="font-medium">{column}</p></section>
          <section className="grid grid-cols-2 gap-3">
            <div><p className="text-xs uppercase text-text-muted mb-1">Row</p><p className="font-mono">{candidate.row}</p></div>
            <div><p className="text-xs uppercase text-text-muted mb-1">Value</p><p className="font-mono font-semibold text-danger">{String(candidate.value ?? '—')}</p></div>
          </section>
          <section className="grid grid-cols-2 gap-3">
            <div><p className="text-xs uppercase text-text-muted mb-1">Method</p><p>{methodLabel}</p></div>
            <div><p className="text-xs uppercase text-text-muted mb-1">Severity</p><Badge variant="warning">{(candidate.severity ?? '').toUpperCase()}</Badge></div>
          </section>
          {explain?.lower_fence != null && (
            <section><p className="text-xs uppercase text-text-muted mb-1">Lower fence</p><p className="font-mono">{explain.lower_fence}</p></section>
          )}
          {explain?.upper_fence != null && (
            <section><p className="text-xs uppercase text-text-muted mb-1">Upper fence</p><p className="font-mono">{explain.upper_fence}</p></section>
          )}
          <section>
            <p className="text-xs uppercase text-text-muted mb-1">Why flagged</p>
            <p className="text-text-muted">{explain?.reason ?? 'Value outside expected statistical boundary'}</p>
          </section>
          {conf != null && (
            <section><p className="text-xs uppercase text-text-muted mb-1">Confidence</p><Badge variant="success">{conf}%</Badge></section>
          )}
          <section>
            <p className="text-xs uppercase text-text-muted mb-1">Recommended action</p>
            <p>Convert to missing (for extreme values) or keep after review</p>
          </section>
          <section className="flex flex-wrap gap-2">
            {domain && <Badge variant="default">Domain: {domain}</Badge>}
            {cluster && <Badge variant="muted">Cluster: {cluster}</Badge>}
          </section>
          <section>
            <p className="text-xs uppercase text-text-muted mb-2">KG path</p>
            <div className="flex flex-col gap-1 text-xs font-mono">
              {[domain ?? 'Dataset', column, cluster ?? 'Metrics', 'Statistical Rules'].map((step, i) => (
                <div key={step} className="flex items-center gap-2">
                  {i > 0 && <span className="text-text-muted ml-2">↓</span>}
                  <span className={cn('px-2 py-0.5 rounded', i === 3 ? 'bg-accent/15 text-primary' : 'bg-border/40')}>{step}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
