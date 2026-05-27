'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp, Activity } from 'lucide-react';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';

interface HealthSummaryProps {
  health: Record<string, unknown>;
}

function summarizeHealth(health: Record<string, unknown>) {
  const entries = Object.entries(health).filter(([, v]) => v != null && v !== '');
  const numeric = entries.filter(([, v]) => typeof v === 'number');
  const flags = entries.filter(([, v]) => typeof v === 'boolean');
  return { entries, numeric, flags };
}

export default function HealthSummary({ health }: HealthSummaryProps) {
  const [showJson, setShowJson] = useState(false);
  const { entries, numeric, flags } = summarizeHealth(health);

  return (
    <Card title="Health summary" description="Dataset quality signals from ingestion">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        {numeric.slice(0, 6).map(([key, val]) => (
          <div key={key} className="rounded-lg border border-border p-3">
            <p className="text-xs uppercase tracking-wide text-text-muted">{key.replace(/_/g, ' ')}</p>
            <p className="text-lg font-semibold text-text mt-1">{String(val)}</p>
          </div>
        ))}
        {flags.slice(0, 4).map(([key, val]) => (
          <div key={key} className="flex items-center justify-between rounded-lg border border-border p-3">
            <span className="text-sm text-text">{key.replace(/_/g, ' ')}</span>
            <Badge variant={val ? 'warning' : 'success'}>{val ? 'Yes' : 'No'}</Badge>
          </div>
        ))}
        {entries.length === 0 && (
          <p className="text-sm text-text-muted col-span-full flex items-center gap-2">
            <Activity className="h-4 w-4" aria-hidden />
            No health metrics available.
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={() => setShowJson(!showJson)}
        className="flex items-center gap-2 text-sm text-primary hover:underline focus-visible:ring-2 focus-visible:ring-accent/40 rounded"
      >
        {showJson ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        Technical JSON
      </button>
      {showJson && (
        <pre className="mt-3 max-h-64 overflow-auto rounded-lg bg-surface p-4 text-xs font-mono text-text-muted border border-border">
          {JSON.stringify(health, null, 2)}
        </pre>
      )}
    </Card>
  );
}
