'use client';

import { CheckCircle2, Loader2, Sparkles, X } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import type { TemplateExtractionJob } from '@/lib/api';
import TemplateExtractionMetroPath from '@/components/report-builder/TemplateExtractionMetroPath';
import { cn } from '@/lib/cn';

export type TemplateExtractionModalPhase = 'running' | 'success' | 'failed';

interface TemplateExtractionModalProps {
  open: boolean;
  templateName: string;
  job: TemplateExtractionJob | null;
  phase: TemplateExtractionModalPhase;
  errorMessage?: string | null;
  onClose: () => void;
  onViewBlueprint: () => void;
  onRetry?: () => void;
}

export default function TemplateExtractionModal({
  open,
  templateName,
  job,
  phase,
  errorMessage,
  onClose,
  onViewBlueprint,
  onRetry,
}: TemplateExtractionModalProps) {
  if (!open) return null;

  const progress = job?.progress_pct ?? 0;
  const canDismiss = phase === 'success' || phase === 'failed';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="template-extraction-title"
      onClick={canDismiss ? onClose : undefined}
    >
      <div
        className="bg-surface-card rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between p-5 border-b border-border shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            {phase === 'running' ? (
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-primary" />
            ) : phase === 'success' ? (
              <CheckCircle2 className="h-5 w-5 shrink-0 text-success" />
            ) : (
              <Sparkles className="h-5 w-5 shrink-0 text-primary" />
            )}
            <div className="min-w-0">
              <h2 id="template-extraction-title" className="font-semibold text-text truncate">
                {phase === 'success'
                  ? 'Template extracted'
                  : phase === 'failed'
                    ? 'Extraction failed'
                    : 'Extracting template'}
              </h2>
              <p className="text-xs text-text-muted truncate">{templateName}</p>
            </div>
          </div>
          {canDismiss && (
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded hover:bg-border/50 text-text-muted hover:text-text"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </header>

        <div className="p-5 overflow-y-auto flex-1 space-y-5">
          {phase === 'failed' && errorMessage && (
            <Alert variant="error">{errorMessage}</Alert>
          )}

          {phase === 'running' && (
            <>
              <div>
                <div className="flex justify-between text-xs text-text-muted mb-1.5">
                  <span>Overall progress</span>
                  <span className="font-medium text-text">{progress}%</span>
                </div>
                <div className="h-2 rounded-full bg-border overflow-hidden">
                  <div
                    className="h-full rounded-full bg-accent transition-all duration-500 ease-out"
                    style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
                  />
                </div>
              </div>

              <TemplateExtractionMetroPath job={job} />

              <p className="text-xs text-text-muted text-center">
                Do not close this window while extraction is in progress.
              </p>
            </>
          )}

          {phase === 'success' && (
            <div className="space-y-4 text-center py-4">
              <div className="rounded-lg border border-success/30 bg-success/5 p-4 text-sm">
                <p className="font-medium text-success mb-2">Production AST ready</p>
                <div className="grid grid-cols-2 gap-2 text-xs text-text-muted text-left">
                  <div>
                    <span className="font-medium text-text">Method:</span>{' '}
                    {job?.extraction_method ?? '—'}
                  </div>
                  <div>
                    <span className="font-medium text-text">Template ID:</span>{' '}
                    {job?.created_template_id ?? '—'}
                  </div>
                  {job?.source_hash && (
                    <div className="col-span-2 font-mono text-[10px] break-all">
                      SHA256: {job.source_hash}
                    </div>
                  )}
                </div>
              </div>
              <TemplateExtractionMetroPath job={job} />
              <p className="text-xs text-text-muted">
                Next: bind a dataset to this template, then generate your report.
              </p>
            </div>
          )}

          {phase === 'failed' && (
            <TemplateExtractionMetroPath job={job} />
          )}
        </div>

        <footer
          className={cn(
            'flex justify-end gap-2 p-5 border-t border-border shrink-0',
            phase === 'running' && 'opacity-60 pointer-events-none'
          )}
        >
          {phase === 'success' && (
            <>
              <Button variant="secondary" onClick={onClose}>
                Close
              </Button>
              <Button onClick={onViewBlueprint}>
                View blueprint
              </Button>
            </>
          )}
          {phase === 'failed' && (
            <>
              <Button variant="secondary" onClick={onClose}>
                Close
              </Button>
              {onRetry && <Button onClick={onRetry}>Try again</Button>}
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
