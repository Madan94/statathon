'use client';

import { cn } from '@/lib/cn';

const STEPS = [
  'Officer',
  'Data source',
  'Template',
  'Blocks',
  'Filters',
  'Generate',
] as const;

export default function WizardStepper({
  current,
  className,
}: {
  current: number;
  className?: string;
}) {
  return (
    <ol className={cn('flex flex-wrap gap-2 mb-8', className)}>
      {STEPS.map((label, i) => (
        <li
          key={label}
          className={cn(
            'rounded-full px-3 py-1 text-xs font-semibold border',
            i === current
              ? 'bg-[#f5c518] text-[#0a0a0a] border-[#f5c518]'
              : i < current
              ? 'bg-[#0a1f44] text-white border-[#0a1f44]'
              : 'bg-white text-[#64748b] border-[#e2e8f0]'
          )}
        >
          {i + 1}. {label}
        </li>
      ))}
    </ol>
  );
}
