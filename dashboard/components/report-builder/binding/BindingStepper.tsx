'use client';

import { Check, Database, GitPullRequestArrow, Shield } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface BindingStep {
  id: string;
  label: string;
  hint?: string;
}

const STEP_ICONS = [Database, GitPullRequestArrow, Shield];

interface BindingStepperProps {
  steps: BindingStep[];
  /** Zero-based index of the current step. */
  current: number;
  className?: string;
}

/**
 * Calm, polished progress tracker for the binding workflow.
 * Completed steps fill with navy + a check; the active step gets a pulsing ring.
 */
export function BindingStepper({ steps, current, className }: BindingStepperProps) {
  return (
    <ol className={cn('flex w-full items-start', className)} aria-label="Binding progress">
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        const isLast = i === steps.length - 1;
        const StepIcon = STEP_ICONS[i] || Database;
        return (
          <li
            key={step.id}
            className={cn('relative flex min-w-0 flex-1 flex-col items-center', isLast && 'flex-none')}
          >
            <div className="flex w-full items-center">
              {/* leading connector */}
              {i > 0 && (
                <span
                  className={cn(
                    'h-0.5 flex-1 rounded-full transition-all duration-500',
                    done || active ? 'bg-primary' : 'bg-border'
                  )}
                  aria-hidden
                />
              )}

              <span
                className={cn(
                  'flex h-11 w-11 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-all duration-300',
                  done && 'border-primary bg-primary text-white shadow-sm',
                  active && 'border-primary bg-primary text-white ring-4 ring-primary/20 shadow-md',
                  !done && !active && 'border-border bg-surface-card text-text-muted'
                )}
                aria-current={active ? 'step' : undefined}
              >
                {done ? <Check className="h-5 w-5" aria-hidden /> : <StepIcon className="h-4.5 w-4.5" />}
              </span>

              {/* trailing connector */}
              {!isLast && (
                <span
                  className={cn(
                    'h-0.5 flex-1 rounded-full transition-all duration-500',
                    done ? 'bg-primary' : 'bg-border'
                  )}
                  aria-hidden
                />
              )}
            </div>

            <div className={cn('mt-2.5 px-1 text-center', isLast && 'min-w-[7rem]')}>
              <p
                className={cn(
                  'text-sm font-semibold leading-tight transition-colors',
                  active ? 'text-primary' : done ? 'text-text' : 'text-text-muted'
                )}
              >
                {step.label}
              </p>
              {step.hint && (
                <p className="mt-0.5 text-[11px] text-text-muted">{step.hint}</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default BindingStepper;
