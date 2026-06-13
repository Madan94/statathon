'use client';

import { useState } from 'react';
import type { AnalysisResult } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import { resolveAnomalyBlock } from '@/lib/outlierColumnUtils';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';
import { TrendingUp, Zap, CheckCircle2, Loader2, BarChart3 } from 'lucide-react';

interface ColumnBlock {
  column?: string;
  recommended?: string;
  z_score_confidence?: number;
  iqr_confidence?: number;
  reason?: string[];
  z_score_pros?: string[];
  z_score_cons?: string[];
  iqr_pros?: string[];
  iqr_cons?: string[];
  goodness_of_fit?: {
    mean?: number;
    median?: number;
    standard_deviation?: number;
    skewness?: number;
    kurtosis?: number;
    shapiro_w_statistic?: number | null;
    p_value?: number | null;
  };
  method_selected?: string | null;
  detection_run?: boolean;
}

interface Props {
  column: string;
  analysisId: number;
  results: AnalysisResult;
  onComplete: (updated: AnalysisResult) => void;
  className?: string;
}

function MethodCard({
  title,
  icon: Icon,
  confidence,
  pros,
  cons,
  recommended,
  selected,
  onSelect,
  loading,
  color,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  confidence: number;
  pros: string[];
  cons: string[];
  recommended: boolean;
  selected: boolean;
  onSelect: () => void;
  loading: boolean;
  color: 'indigo' | 'amber';
}) {
  return (
    <div
      className={cn(
        'rounded-xl border p-4 flex flex-col gap-3 transition-all',
        selected ? `border-${color}-500 bg-${color}-500/5 ring-1 ring-${color}-500/30` : 'border-border bg-surface',
        recommended && !selected && 'border-primary/40',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Icon className={cn('h-5 w-5', color === 'indigo' ? 'text-indigo-400' : 'text-amber-400')} />
          <h3 className="font-semibold text-text">{title}</h3>
        </div>
        {recommended && <Badge variant="default">Recommended</Badge>}
      </div>
      <div>
        <p className="text-xs text-text-muted uppercase tracking-wide">Confidence</p>
        <p className="text-3xl font-bold font-mono text-text">{confidence}%</p>
        <div className="h-2 rounded-full bg-border mt-2 overflow-hidden">
          <div
            className={cn('h-full rounded-full', color === 'indigo' ? 'bg-indigo-500' : 'bg-amber-500')}
            style={{ width: `${confidence}%` }}
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs flex-1">
        <div>
          <p className="font-semibold text-success mb-1">Pros</p>
          <ul className="space-y-0.5 text-text-muted">
            {pros.map((p) => (
              <li key={p}>• {p}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className="font-semibold text-warning mb-1">Cons</p>
          <ul className="space-y-0.5 text-text-muted">
            {cons.map((c) => (
              <li key={c}>• {c}</li>
            ))}
          </ul>
        </div>
      </div>
      <Button
        onClick={onSelect}
        disabled={loading}
        variant={selected ? 'primary' : 'outline'}
        className="w-full gap-2"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Use {title}
      </Button>
    </div>
  );
}

export default function MethodSelectionPanel({
  column,
  analysisId,
  results,
  onComplete,
  className,
}: Props) {
  const [loading, setLoading] = useState<'Z_SCORE' | 'IQR' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const block = resolveAnomalyBlock(column, results);

  if (!block) {
    return (
      <Card className={cn('border-warning/30 bg-warning/5', className)}>
        <p className="text-sm text-text-muted">
          No goodness-of-fit data for <strong className="font-mono">{column}</strong>.
          Re-run analysis to generate outlier method recommendations.
        </p>
      </Card>
    );
  }

  if (block.detection_run) {
    return (
      <Card className={cn('border-success/30 bg-success/5', className)}>
        <div className="flex items-center gap-2 text-success">
          <CheckCircle2 className="h-5 w-5" />
          <span className="font-semibold">
            Detection complete using {block.method_selected === 'IQR' ? 'IQR' : 'Z-Score'}
          </span>
        </div>
      </Card>
    );
  }

  const gof = (block.goodness_of_fit ?? {}) as {
    mean?: number;
    median?: number;
    standard_deviation?: number;
    skewness?: number;
    kurtosis?: number;
    p_value?: number;
  };
  const recommended = String(block.recommended ?? 'Z_SCORE').toUpperCase();
  const zConf = Number(block.z_score_confidence ?? 0);
  const iqrConf = Number(block.iqr_confidence ?? 0);
  const reasons = block.reason ?? [];

  const handleSelect = async (method: 'Z_SCORE' | 'IQR') => {
    setLoading(method);
    setError(null);
    try {
      await analysisApi.selectOutlierMethod(analysisId, column, method);
      await analysisApi.runOutlierDetection(analysisId, column);
      const updated = await analysisApi.getResults(analysisId, { includePhase3: true });
      onComplete(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run detection');
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className={cn('space-y-4', className)}>
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 className="h-5 w-5 text-primary" />
          <div>
            <h3 className="font-semibold text-text">Goodness-of-Fit Analysis</h3>
            <p className="text-xs text-text-muted">
              Statistical fitness for <strong className="font-mono">{column}</strong> before outlier detection
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-xs">
          {[
            { l: 'Mean', v: gof.mean?.toFixed?.(3) ?? '—' },
            { l: 'Median', v: gof.median?.toFixed?.(3) ?? '—' },
            { l: 'Std Dev', v: gof.standard_deviation?.toFixed?.(3) ?? '—' },
            { l: 'Skewness', v: gof.skewness?.toFixed?.(3) ?? '—' },
            { l: 'Kurtosis', v: gof.kurtosis?.toFixed?.(3) ?? '—' },
            { l: 'Shapiro p', v: gof.p_value?.toFixed?.(4) ?? '—' },
          ].map(({ l, v }) => (
            <div key={l} className="rounded-lg border border-border p-2 bg-surface/50">
              <p className="text-text-muted uppercase text-[10px]">{l}</p>
              <p className="font-mono font-semibold text-text mt-0.5">{v}</p>
            </div>
          ))}
        </div>
        {reasons.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {reasons.map((r) => (
              <Badge key={r} variant="muted" className="text-[10px]">
                {r}
              </Badge>
            ))}
          </div>
        )}
      </Card>

      <div>
        <h3 className="font-semibold text-text mb-3">Choose Detection Method</h3>
        <p className="text-sm text-text-muted mb-4">
          Review confidence scores below. You must select a method before outliers are detected.
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <MethodCard
            title="Z-Score"
            icon={TrendingUp}
            confidence={zConf}
            pros={block.z_score_pros ?? ['Best for normal data']}
            cons={block.z_score_cons ?? ['Sensitive to skew']}
            recommended={recommended === 'Z_SCORE'}
            selected={block.method_selected === 'Z_SCORE'}
            onSelect={() => handleSelect('Z_SCORE')}
            loading={loading === 'Z_SCORE'}
            color="indigo"
          />
          <MethodCard
            title="IQR"
            icon={Zap}
            confidence={iqrConf}
            pros={block.iqr_pros ?? ['Robust to outliers']}
            cons={block.iqr_cons ?? ['Less precise for normal data']}
            recommended={recommended === 'IQR'}
            selected={block.method_selected === 'IQR'}
            onSelect={() => handleSelect('IQR')}
            loading={loading === 'IQR'}
            color="amber"
          />
        </div>
        {error && <p className="text-sm text-danger mt-3">{error}</p>}
      </div>
    </div>
  );
}
