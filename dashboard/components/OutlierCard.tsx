'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';

interface OutlierCardProps {
  column: string;
  indices: number[];
  confidence: number;
  risk: 'low' | 'medium' | 'high';
  onDecision: (decision: 'keep' | 'delete' | 'normalize') => void;
}

export default function OutlierCard({ column, indices, confidence, risk, onDecision }: OutlierCardProps) {
  const [decision, setDecision] = useState<'keep' | 'delete' | 'normalize' | null>(null);

  const riskVariant = {
    low: 'success' as const,
    medium: 'warning' as const,
    high: 'danger' as const,
  };

  const handleDecision = (d: 'keep' | 'delete' | 'normalize') => {
    setDecision(d);
    onDecision(d);
  };

  return (
    <Card>
      <div className="flex items-center justify-between gap-2 mb-3">
        <h3 className="font-semibold text-text font-mono">{column}</h3>
        <div className="flex items-center gap-2 shrink-0">
          <Badge variant={riskVariant[risk]}>{risk} risk</Badge>
          <span className="text-xs text-text-muted">{(confidence * 100).toFixed(0)}%</span>
        </div>
      </div>
      <p className="text-sm text-text-muted mb-4">
        {indices.length} outlier{indices.length !== 1 ? 's' : ''} at row
        {indices.length !== 1 ? 's' : ''}: {indices.slice(0, 8).join(', ')}
        {indices.length > 8 && ` +${indices.length - 8} more`}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={decision === 'keep' ? 'primary' : 'outline'}
          onClick={() => handleDecision('keep')}
        >
          Keep
        </Button>
        <Button
          size="sm"
          variant={decision === 'delete' ? 'destructive' : 'outline'}
          onClick={() => handleDecision('delete')}
        >
          Delete
        </Button>
        <Button
          size="sm"
          variant={decision === 'normalize' ? 'secondary' : 'outline'}
          onClick={() => handleDecision('normalize')}
        >
          Normalize
        </Button>
      </div>
    </Card>
  );
}
