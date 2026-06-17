'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Check } from 'lucide-react';
import { cn } from '@/lib/cn';
import { stepHref } from '@/lib/analysisPipeline';
import { analysisApi } from '@/lib/api';

export const PIPELINE_STEPS = [
  { id: 1, label: 'Summary', sublabel: 'Dataset overview' },
  { id: 2, label: 'Normalise', sublabel: 'Columns' },
  { id: 3, label: 'Semantic', sublabel: 'Domain mapping' },
  { id: 4, label: 'Clustering', sublabel: 'Column groups' },
  { id: 5, label: 'Schema', sublabel: 'Graph view' },
  { id: 6, label: 'Rule Validation', sublabel: 'Single & multi column' },
  { id: 7, label: 'Column Analysis', sublabel: 'Anomaly & missing' },
  { id: 8, label: 'Dataset Review', sublabel: 'Approve & proceed' },
] as const;

interface AnalysisStepperProps {
  currentStep: number;
  analysisId?: number;
  className?: string;
}

function stepUnlocked(
  stepId: number,
  status: Awaited<ReturnType<typeof analysisApi.getPhaseStatus>> | null,
): boolean {
  if (!status) return true;
  if (stepId <= 6) return true;
  if (stepId === 7) {
    return Boolean(status.rule_validation_completed);
  }
  if (stepId === 8) {
    return Boolean(
      status.rule_validation_completed && status.anomaly_completed && status.missing_value_completed,
    );
  }
  return true;
}

export default function AnalysisStepper({
  currentStep,
  analysisId,
  className,
}: AnalysisStepperProps) {
  const [phaseStatus, setPhaseStatus] = useState<Awaited<
    ReturnType<typeof analysisApi.getPhaseStatus>
  > | null>(null);

  useEffect(() => {
    if (!analysisId) return;
    analysisApi
      .getPhaseStatus(analysisId)
      .then(setPhaseStatus)
      .catch(() => setPhaseStatus(null));
  }, [analysisId, currentStep]);

  const unlockedByStep = useMemo(() => {
    const map = new Map<number, boolean>();
    for (const step of PIPELINE_STEPS) {
      map.set(step.id, stepUnlocked(step.id, phaseStatus));
    }
    return map;
  }, [phaseStatus]);

  return (
    <nav
      className={cn(
        'rounded-xl border border-border bg-surface-card px-4 py-3',
        className
      )}
      aria-label="Analysis pipeline progress"
    >
      <ol className="flex items-center">
        {PIPELINE_STEPS.map((step, idx) => {
          const done = step.id < currentStep;
          const active = step.id === currentStep;
          const last = idx === PIPELINE_STEPS.length - 1;
          const href = analysisId ? stepHref(analysisId, step.id) : undefined;
          const unlocked = unlockedByStep.get(step.id) ?? true;

          const inner = (
            <>
              <span
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold border-2 transition-all',
                  active && 'border-accent bg-accent text-white shadow-sm shadow-accent/30',
                  done && 'border-success bg-success text-white',
                  !active && !done && 'border-border bg-surface text-text-muted',
                  href && unlocked && !active && 'hover:border-accent/50',
                  !unlocked && 'opacity-40 cursor-not-allowed',
                )}
                aria-current={active ? 'step' : undefined}
              >
                {done ? <Check className="h-4 w-4" aria-hidden /> : step.id}
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wide hidden md:block text-center leading-tight">
                {step.label}
              </span>
              <span className="text-[9px] text-text-muted hidden lg:block text-center">
                {step.sublabel}
              </span>
            </>
          );

          return (
            <li key={step.id} className="flex items-center flex-1 min-w-0">
              <div
                className={cn(
                  'flex flex-col items-center gap-1 flex-1 min-w-0',
                  active && 'text-primary',
                  done && 'text-success',
                  !active && !done && 'text-text-muted',
                )}
              >
                {href && unlocked ? (
                  <Link href={href} className="flex flex-col items-center gap-1 min-w-0">
                    {inner}
                  </Link>
                ) : (
                  <span
                    className="flex flex-col items-center gap-1 min-w-0"
                    title={!unlocked ? 'Complete previous phases first' : undefined}
                  >
                    {inner}
                  </span>
                )}
              </div>
              {!last && (
                <div
                  className={cn(
                    'h-0.5 flex-1 mx-1 rounded-full transition-colors',
                    done ? 'bg-success' : 'bg-border'
                  )}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
