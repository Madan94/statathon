'use client';

import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';

export type AnalysisModalPhase = 'running' | 'success' | 'failed';

export const ANALYSIS_PIPELINE_STEPS = [
  { id: 'ingest', label: 'Loading dataset', detail: 'Reading file from storage' },
  { id: 'profile', label: 'Profiling columns', detail: 'Health metrics and data types' },
  { id: 'semantic', label: 'Semantic mapping', detail: 'Domain and keyword matching' },
  { id: 'graph', label: 'Building schema graph', detail: 'Column relationships' },
  { id: 'intel', label: 'Intelligence pipeline', detail: 'Validation and outlier scoring' },
  { id: 'persist', label: 'Preparing workspace', detail: 'Saving for pipeline wizard' },
] as const;

export function estimateAnalysisStepIndex(elapsedMs: number, status: string): number {
  if (status === 'complete') return ANALYSIS_PIPELINE_STEPS.length - 1;
  const sec = elapsedMs / 1000;
  if (sec < 12) return 0;
  if (sec < 35) return 1;
  if (sec < 90) return 2;
  if (sec < 180) return 3;
  if (sec < 360) return 4;
  return 5;
}

export function analysisProgressPct(stepIndex: number, phase: AnalysisModalPhase): number {
  if (phase === 'success') return 100;
  if (phase === 'failed') return Math.min(95, ((stepIndex + 0.6) / ANALYSIS_PIPELINE_STEPS.length) * 100);
  return Math.min(92, ((stepIndex + 0.75) / ANALYSIS_PIPELINE_STEPS.length) * 100);
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

interface AnalysisRunningModalProps {
  open: boolean;
  phase: AnalysisModalPhase;
  datasetName: string;
  analysisId?: number;
  elapsedMs: number;
  activeStepIndex: number;
  progressPct: number;
  statusLine?: string | null;
  errorMessage?: string | null;
  onClose?: () => void;
  onRetry?: () => void;
}

export default function AnalysisRunningModal({
  open,
  phase,
  datasetName,
  analysisId,
  elapsedMs,
  activeStepIndex,
  progressPct,
  statusLine,
  errorMessage,
  onClose,
  onRetry,
}: AnalysisRunningModalProps) {
  if (!open) return null;

  const canDismiss = phase === 'failed';
  const title =
    phase === 'success'
      ? 'Analysis complete'
      : phase === 'failed'
        ? 'Analysis failed'
        : 'Running analysis pipeline';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-primary/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="analysis-running-title"
      onClick={canDismiss ? onClose : undefined}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-xl border border-primary bg-surface-card shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-b border-primary-hover bg-primary px-6 py-4">
          <div className="flex items-start gap-3">
            {phase === 'running' && (
              <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-accent" aria-hidden />
            )}
            {phase === 'success' && (
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden />
            )}
            {phase === 'failed' && (
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-danger" aria-hidden />
            )}
            <div className="min-w-0 flex-1">
              <h2 id="analysis-running-title" className="text-base font-semibold text-white">
                {title}
              </h2>
              <p className="mt-0.5 truncate text-sm text-white/75">{datasetName}</p>
              {analysisId != null && (
                <p className="mt-1 font-mono text-xs text-white/60">Analysis #{analysisId}</p>
              )}
            </div>
          </div>
        </header>

        <div className="space-y-4 px-6 py-4">
          {phase === 'failed' && errorMessage && (
            <div
              className="rounded-lg border border-danger/25 bg-danger/5 px-3 py-2.5 text-sm text-danger"
              role="alert"
            >
              {errorMessage}
            </div>
          )}

          {phase === 'success' ? (
            <p className="text-sm text-text-muted">
              Redirecting to the analysis pipeline wizard…
            </p>
          ) : (
            <>
              {phase === 'running' && (
                <div>
                  <div className="mb-1.5 flex items-center justify-between text-xs text-text-muted">
                    <span>Progress</span>
                    <span className="font-medium tabular-nums text-text">
                      {Math.round(progressPct)}%
                      <span className="mx-1.5 text-border">·</span>
                      {formatElapsed(elapsedMs)}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-border">
                    <div
                      className="h-full rounded-full bg-accent transition-all duration-500 ease-out"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                  {statusLine && (
                    <p className="mt-2 text-xs leading-relaxed text-text-muted">{statusLine}</p>
                  )}
                </div>
              )}

              <ul className="space-y-2" aria-label="Pipeline steps">
                {ANALYSIS_PIPELINE_STEPS.map((step, index) => {
                  const done = index < activeStepIndex;
                  const active = phase === 'running' && index === activeStepIndex;

                  return (
                    <li
                      key={step.id}
                      className={cn(
                        'flex items-start gap-2.5 rounded-lg px-2 py-1.5 text-sm',
                        active && 'bg-accent-muted/60'
                      )}
                    >
                      <span className="mt-0.5 shrink-0">
                        {done && <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />}
                        {active && (
                          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
                        )}
                        {!done && !active && (
                          <span
                            className="block h-4 w-4 rounded-full border border-border bg-surface"
                            aria-hidden
                          />
                        )}
                      </span>
                      <span className="min-w-0">
                        <span
                          className={cn(
                            'font-medium',
                            active ? 'text-primary' : done ? 'text-text' : 'text-text-muted'
                          )}
                        >
                          {step.label}
                        </span>
                        {active && (
                          <span className="mt-0.5 block text-xs text-text-muted">{step.detail}</span>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>

        <footer className="border-t border-border px-6 py-3">
          {phase === 'running' && (
            <p className="text-xs text-text-muted">
              First run may take 10–20 minutes while models load. Please keep this tab open.
            </p>
          )}
          {phase === 'failed' && (
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={onClose}>
                Close
              </Button>
              {onRetry && (
                <Button variant="primary" size="sm" onClick={onRetry}>
                  Try again
                </Button>
              )}
            </div>
          )}
        </footer>
      </div>
    </div>
  );
}
