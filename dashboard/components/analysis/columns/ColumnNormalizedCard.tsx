'use client';

import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';
import { CheckCircle2, Loader2, AlertTriangle } from 'lucide-react';

export type NormalizePhase = 'anomaly' | 'imputation';

interface PhaseSummary {
  saved?: number;
  candidate_count?: number;
  missing_count?: number;
  method?: string | null;
  decision?: string;
  normalized?: boolean;
  already_applied?: boolean;
}

interface Props {
  column: string;
  phase: NormalizePhase;
  status: 'loading' | 'done' | 'error';
  summary?: PhaseSummary;
  error?: string | null;
  /** Shown when no backend work was needed (e.g. zero missing values). */
  uiOnly?: boolean;
  onRetry?: () => void;
  onReviewManually?: () => void;
  className?: string;
}

export default function ColumnNormalizedCard({
  column,
  phase,
  status,
  summary,
  error,
  uiOnly = false,
  onRetry,
  onReviewManually,
  className,
}: Props) {
  const isAnomaly = phase === 'anomaly';

  if (status === 'loading') {
    return (
      <Card className={cn('border-border', className)}>
        <div className="flex items-center gap-3 text-text-muted">
          <Loader2 className="h-5 w-5 animate-spin shrink-0" />
          <div>
            <p className="font-medium text-text">
              {isAnomaly ? 'Normalizing anomalies…' : 'Normalizing missing values…'}
            </p>
            <p className="text-sm mt-0.5">Applying defaults in the background for <span className="font-mono">{column}</span>.</p>
          </div>
        </div>
      </Card>
    );
  }

  if (status === 'error') {
    return (
      <Card className={cn('border-warning/40 bg-warning/5', className)}>
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold text-text">Auto-normalize failed</p>
            <p className="text-sm text-text-muted mt-1">{error ?? 'Could not apply default decisions.'}</p>
            <div className="flex gap-2 mt-3">
              {onRetry && (
                <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
              )}
              {onReviewManually && (
                <Button variant="ghost" size="sm" onClick={onReviewManually}>Review manually</Button>
              )}
            </div>
          </div>
        </div>
      </Card>
    );
  }

  const count = isAnomaly
    ? summary?.candidate_count ?? summary?.saved ?? 0
    : summary?.missing_count ?? summary?.saved ?? 0;
  const method = summary?.method;
  const decision = summary?.decision ?? (isAnomaly ? 'KEEP' : 'ACCEPT');
  const title = uiOnly ? 'Normalization applied' : 'Column normalized';

  return (
    <Card className={cn('border-success/30 bg-success/5', className)}>
      <div className="flex items-start gap-3">
        <CheckCircle2 className="h-6 w-6 text-success shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-text">{title}</p>
            <Badge variant="success">{isAnomaly ? 'Anomalies' : 'Missing values'}</Badge>
            {summary?.already_applied && (
              <Badge variant="muted">Previously applied</Badge>
            )}
          </div>
          <p className="text-sm text-text-muted mt-1">
            <span className="font-mono font-medium text-text">{column}</span>
            {isAnomaly ? (
              <>
                {' '}— {count === 0 ? 'no anomalies detected' : `${count} anomal${count === 1 ? 'y' : 'ies'} kept`}
                {count > 0 && <> · default <strong>{decision}</strong></>}
              </>
            ) : uiOnly ? (
              <> — no missing values; nothing to impute</>
            ) : (
              <>
                {' '}— {count} missing value{count === 1 ? '' : 's'} imputed
                {method && <> using <strong className="capitalize">{method}</strong></>}
                {count > 0 && <> · default <strong>{decision}</strong></>}
              </>
            )}
          </p>
          {onReviewManually && count > 0 && (
            <Button variant="ghost" size="sm" className="mt-3 px-0 h-auto text-primary" onClick={onReviewManually}>
              Review rows manually →
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
