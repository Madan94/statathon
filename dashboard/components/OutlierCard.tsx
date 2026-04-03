'use client';

import { useState } from 'react';

interface OutlierCardProps {
  column: string;
  indices: number[];
  confidence: number;
  risk: 'low' | 'medium' | 'high';
  onDecision: (decision: 'keep' | 'delete' | 'normalize') => void;
}

export default function OutlierCard({ column, indices, confidence, risk, onDecision }: OutlierCardProps) {
  const [decision, setDecision] = useState<'keep' | 'delete' | 'normalize' | null>(null);

  const riskColors = {
    low: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    high: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  };

  const handleDecision = (d: 'keep' | 'delete' | 'normalize') => {
    setDecision(d);
    onDecision(d);
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mb-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{column}</h3>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full text-xs font-medium ${riskColors[risk]}`}>
            {risk.toUpperCase()} RISK
          </span>
          <span className="text-sm text-gray-600 dark:text-gray-400">
            Confidence: {(confidence * 100).toFixed(1)}%
          </span>
        </div>
      </div>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        Found {indices.length} outlier{indices.length !== 1 ? 's' : ''} at row{indices.length !== 1 ? 's' : ''}:{' '}
        {indices.slice(0, 10).join(', ')}
        {indices.length > 10 && ` +${indices.length - 10} more`}
      </p>
      <div className="flex gap-2">
        <button
          onClick={() => handleDecision('keep')}
          disabled={decision === 'keep'}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            decision === 'keep'
              ? 'bg-green-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
          }`}
        >
          Keep
        </button>
        <button
          onClick={() => handleDecision('delete')}
          disabled={decision === 'delete'}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            decision === 'delete'
              ? 'bg-red-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
          }`}
        >
          Delete
        </button>
        <button
          onClick={() => handleDecision('normalize')}
          disabled={decision === 'normalize'}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            decision === 'normalize'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
          }`}
        >
          Normalize
        </button>
      </div>
    </div>
  );
}

