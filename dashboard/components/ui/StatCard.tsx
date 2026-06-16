import { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

interface StatCardProps {
  label: string;
  value?: string | number;
  subValue?: string;
  /** Two timezone lines with equal highlight styling (e.g. IST + UTC). */
  highlightedTimes?: Array<{ zone: string; time: string }>;
  icon?: LucideIcon;
  className?: string;
  compactValue?: boolean;
}

export function StatCard({
  label,
  value = '—',
  subValue,
  highlightedTimes,
  icon: Icon,
  className,
  compactValue,
}: StatCardProps) {
  return (
    <div
      className={cn(
        'rounded-xl border border-border bg-surface-card p-4 shadow-sm',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
          {label}
        </p>
        {Icon && <Icon className="h-4 w-4 text-accent shrink-0" aria-hidden />}
      </div>
      {highlightedTimes?.length ? (
        <div className="mt-2 space-y-2">
          {highlightedTimes.map(({ zone, time }) => (
            <p
              key={zone}
              className="rounded-lg border border-accent/30 bg-accent/10 px-2.5 py-1.5 text-sm font-semibold text-text leading-snug"
            >
              <span className="mr-2 inline-block rounded bg-accent/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-accent">
                {zone}
              </span>
              {time}
            </p>
          ))}
        </div>
      ) : (
        <>
          <p
            className={cn(
              'mt-2 font-semibold text-text',
              compactValue || subValue ? 'text-sm leading-snug' : 'text-2xl',
            )}
          >
            {value}
          </p>
          {subValue ? (
            <p className="mt-1 text-xs text-text-muted leading-snug">{subValue}</p>
          ) : null}
        </>
      )}
    </div>
  );
}

export default StatCard;
