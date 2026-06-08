'use client';

import { Check } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface BindingStep {
  id: string;
  label: string;
  hint?: string;
}

interface BindingStepperProps {
  steps: BindingStep[];
  /** Zero-based index of the current step. */
  current: number;
  className?: string;
}

/**
 * Calm, light, on-brand progress tracker for the binding workflow.
 * Completed steps fill with navy + a check; the active step gets a soft ring.
 */
export function BindingStepper({ steps, current, className }: BindingStepperProps) {
  return (
    <ol className={cn('flex w-full items-start', className)} aria-label="Binding progress">
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        const isLast = i === steps.length - 1;
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
                    'h-0.5 flex-1 rounded-full transition-colors',
                    done || active ? 'bg-primary' : 'bg-border'
                  )}
                  aria-hidden
                />
              )}

              <span
                className={cn(
                  'flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-all',
                  done && 'border-primary bg-primary text-white',
                  active && 'border-primary bg-primary text-white ring-4 ring-primary/15',
                  !done && !active && 'border-border bg-surface-card text-text-muted'
                )}
                aria-current={active ? 'step' : undefined}
              >
                {done ? <Check className="h-5 w-5" aria-hidden /> : i + 1}
              </span>

              {/* trailing connector */}
              {!isLast && (
                <span
                  className={cn(
                    'h-0.5 flex-1 rounded-full transition-colors',
                    done ? 'bg-primary' : 'bg-border'
                  )}
                  aria-hidden
                />
              )}
            </div>

            <div className={cn('mt-2 px-1 text-center', isLast && 'min-w-[7rem]')}>
              <p
                className={cn(
                  'text-sm font-semibold leading-tight transition-colors',
                  active || done ? 'text-text' : 'text-text-muted'
                )}
              >
                {step.label}
              </p>
              {step.hint && (
                <p className="mt-0.5 text-xs text-text-muted">{step.hint}</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default BindingStepper;
