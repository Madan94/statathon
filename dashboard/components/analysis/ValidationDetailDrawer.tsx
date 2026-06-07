'use client';

import { X } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import type { ValidationCandidate } from '@/lib/api';
import { cn } from '@/lib/cn';

interface Props {
  candidate: ValidationCandidate | null;
  domain?: string;
  onClose: () => void;
}

function kgPath(kg: unknown, column?: string): string[] {
  if (!kg || typeof kg !== 'object') {
    return column ? ['Dataset', column] : ['Dataset'];
  }
  const o = kg as Record<string, unknown>;
  const nodes = (o.nodes ?? o.entities ?? []) as unknown[];
  const path: string[] = ['Person'];
  if (column) path.push(column);
  const domainNode = nodes.find((n) => {
    if (!n || typeof n !== 'object') return false;
    const node = n as Record<string, unknown>;
    return String(node.id ?? node.name ?? '') === column;
  }) as Record<string, unknown> | undefined;
  if (domainNode?.domain) path.push(String(domainNode.domain));
  path.push('Demographic Rules');
  return path;
}

export default function ValidationDetailDrawer({ candidate, domain, onClose }: Props) {
  if (!candidate) return null;

  const conf = candidate.confidence != null ? Math.round(candidate.confidence * 100) : null;
  const relationships = candidate.kg_relationships;
  const path = kgPath(relationships, candidate.column);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button type="button" className="absolute inset-0 bg-black/40" onClick={onClose} aria-label="Close" />
      <aside className="relative w-full max-w-md bg-surface-card border-l border-border shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-surface-card border-b border-border px-5 py-4 flex items-center justify-between">
          <h3 className="font-semibold text-text">Violation details</h3>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-border/50" aria-label="Close panel">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5 space-y-5 text-sm">
          <section>
            <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Column</p>
            <p className="font-medium">{candidate.column ?? '—'}</p>
          </section>
          <section className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Row</p>
              <p className="font-mono">{candidate.row ?? '—'}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Original value</p>
              <p className="font-mono font-medium text-danger">{String(candidate.value ?? '—')}</p>
            </div>
          </section>
          <section>
            <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Rule</p>
            <p className="font-mono text-xs bg-border/30 rounded px-2 py-1.5">
              {candidate.explanation ??
                (typeof candidate.rule === 'string' ? candidate.rule : candidate.rule?.rule_expression) ??
                candidate.rule_id ??
                '—'}
            </p>
          </section>
          <section>
            <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Expected</p>
            <p>{candidate.expected ?? '—'}</p>
          </section>
          <section>
            <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Why flagged</p>
            <p className="text-text-muted">{candidate.reason ?? candidate.explanation ?? '—'}</p>
          </section>
          <section className="flex flex-wrap gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Domain</p>
              <Badge variant="default">{domain ?? candidate.domain ?? '—'}</Badge>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Severity</p>
              <Badge variant="warning">{(candidate.severity ?? 'REVIEW').toUpperCase()}</Badge>
            </div>
            {conf != null && (
              <div>
                <p className="text-xs uppercase tracking-wide text-text-muted mb-1">Confidence</p>
                <Badge variant="success">{conf}%</Badge>
              </div>
            )}
          </section>
          <section>
            <p className="text-xs uppercase tracking-wide text-text-muted mb-2">KG path</p>
            <div className="flex flex-col items-start gap-1">
              {path.map((step, i) => (
                <div key={`${step}-${i}`} className="flex items-center gap-2">
                  {i > 0 && <span className="text-text-muted ml-2">↓</span>}
                  <span className={cn('font-mono text-xs px-2 py-0.5 rounded', i === path.length - 1 ? 'bg-accent/15 text-primary' : 'bg-border/40')}>
                    {step}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
