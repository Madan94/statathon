import { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

interface StatCardProps {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  className?: string;
}

export function StatCard({ label, value, icon: Icon, className }: StatCardProps) {
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
      <p className="mt-2 text-2xl font-semibold text-text">{value}</p>
    </div>
  );
}

export default StatCard;
