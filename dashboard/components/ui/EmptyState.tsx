import { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-surface-card/50 py-12 px-6 text-center',
        className
      )}
    >
      <Icon className="h-10 w-10 text-text-muted mb-4" aria-hidden />
      <p className="font-medium text-text">{title}</p>
      {description && (
        <p className="mt-2 text-sm text-text-muted max-w-md">{description}</p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export default EmptyState;
