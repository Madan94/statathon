'use client';

import { Check } from 'lucide-react';
import { cn } from '@/lib/cn';

export const PIPELINE_STEPS = [
  { id: 1, label: 'Summary', sublabel: 'Dataset overview' },
  { id: 2, label: 'Normalise', sublabel: 'Columns' },
  { id: 3, label: 'Semantic', sublabel: 'Domain mapping' },
  { id: 4, label: 'Clustering', sublabel: 'Column groups' },
  { id: 5, label: 'Schema & KG', sublabel: 'Graph outputs' },
  { id: 6, label: 'Column Analysis', sublabel: 'Anomaly & missing' },
] as const;

interface AnalysisStepperProps {
  currentStep: number;
  className?: string;
}

export default function AnalysisStepper({ currentStep, className }: AnalysisStepperProps) {
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
          return (
            <li key={step.id} className="flex items-center flex-1 min-w-0">
              <div
                className={cn(
                  'flex flex-col items-center gap-1 flex-1 min-w-0',
                  active && 'text-primary',
                  done && 'text-success',
                  !active && !done && 'text-text-muted'
                )}
              >
                <span
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold border-2 transition-all',
                    active && 'border-accent bg-accent text-white shadow-sm shadow-accent/30',
                    done && 'border-success bg-success text-white',
                    !active && !done && 'border-border bg-surface text-text-muted'
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
