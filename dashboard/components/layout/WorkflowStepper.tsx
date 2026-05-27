'use client';

import { cn } from '@/lib/cn';
import { Check } from 'lucide-react';

export const WORKFLOW_STEPS = [
  { id: 1, label: 'Upload' },
  { id: 2, label: 'Analyze' },
  { id: 3, label: 'Review & decide' },
  { id: 4, label: 'Report' },
] as const;

interface WorkflowStepperProps {
  currentStep: 1 | 2 | 3 | 4;
  className?: string;
}

export default function WorkflowStepper({ currentStep, className }: WorkflowStepperProps) {
  return (
    <ol
      className={cn('flex flex-wrap items-center gap-2 md:gap-0', className)}
      aria-label="Workflow progress"
    >
      {WORKFLOW_STEPS.map((step, index) => {
        const done = step.id < currentStep;
        const active = step.id === currentStep;
        return (
          <li key={step.id} className="flex items-center">
            <div
              className={cn(
                'flex items-center gap-2 rounded-lg px-3 py-2 text-sm',
                active && 'bg-accent-muted text-primary font-medium',
                done && 'text-success',
                !active && !done && 'text-text-muted'
              )}
            >
              <span
                className={cn(
                  'flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold border',
                  active && 'border-accent bg-accent text-white',
                  done && 'border-success bg-success text-white',
                  !active && !done && 'border-border bg-surface-card'
                )}
                aria-current={active ? 'step' : undefined}
              >
                {done ? <Check className="h-3.5 w-3.5" aria-hidden /> : step.id}
              </span>
              <span className="hidden sm:inline">{step.label}</span>
            </div>
            {index < WORKFLOW_STEPS.length - 1 && (
              <div
                className={cn(
                  'hidden md:block w-8 lg:w-12 h-px mx-1',
                  done ? 'bg-success' : 'bg-border'
                )}
                aria-hidden
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
