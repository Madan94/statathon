'use client';

import { AlertTriangle } from 'lucide-react';
import OutlierCard from '@/components/OutlierCard';
import EmptyState from '@/components/ui/EmptyState';
import { OutlierResult } from '@/lib/api';

interface OutlierGridProps {
  outliers: Record<string, OutlierResult>;
  onDecision: (column: string, decision: 'keep' | 'delete' | 'normalize') => void;
}

export default function OutlierGrid({ outliers, onDecision }: OutlierGridProps) {
  const entries = Object.entries(outliers);

  if (!entries.length) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="No outliers detected"
        description="Z-score, IQR, and isolation forest found no columns requiring review."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {entries.map(([column, outlier]) => (
        <OutlierCard
          key={column}
          column={column}
          indices={[...(outlier.zscore || []), ...(outlier.iqr || [])]}
          confidence={outlier.confidence || 0.5}
          risk={outlier.risk || 'medium'}
          onDecision={(decision) => onDecision(column, decision)}
        />
      ))}
    </div>
  );
}
