import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { cn } from '@/lib/cn';

type AlertVariant = 'error' | 'warning' | 'info' | 'success';

const styles: Record<AlertVariant, string> = {
  error: 'border-danger/30 bg-danger/5 text-danger',
  warning: 'border-warning/30 bg-warning/5 text-warning',
  info: 'border-primary/30 bg-primary/5 text-primary',
  success: 'border-success/30 bg-success/5 text-success',
};

interface AlertProps {
  variant?: AlertVariant;
  title?: string;
  children: React.ReactNode;
  className?: string;
  onRetry?: () => void;
}

export function Alert({ variant = 'info', title, children, className, onRetry }: AlertProps) {
  const Icon = variant === 'error' ? AlertTriangle : variant === 'success' ? CheckCircle2 : Info;
  return (
    <div
      role="alert"
      className={cn('flex gap-3 rounded-lg border p-4 text-sm', styles[variant], className)}
    >
      <Icon className="h-5 w-5 shrink-0" aria-hidden />
      <div className="flex-1 min-w-0">
        {title && <p className="font-medium mb-1">{title}</p>}
        <div className="text-text/90">{children}</div>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 text-sm font-medium underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 rounded"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export default Alert;
