'use client';

export interface ValidationCandidate {
  column?: string;
  kind?: string;
  severity?: string;
  candidate_action?: string;
  row?: number;
  detail?: Record<string, unknown>;
}

interface ValidationPanelProps {
  candidates: ValidationCandidate[];
}

export default function ValidationPanel({ candidates }: ValidationPanelProps) {
  if (!candidates.length) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-2">Rule validation</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">No validation candidates flagged.</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Rule validation ({candidates.length})
      </h2>
      <ul className="space-y-2 max-h-80 overflow-auto text-sm">
        {candidates.slice(0, 100).map((c, i) => (
          <li key={i} className="p-3 bg-gray-50 dark:bg-gray-900 rounded flex flex-wrap gap-2 justify-between">
            <span className="font-medium text-gray-900 dark:text-gray-100">{c.column || '—'}</span>
            <span className="text-amber-700 dark:text-amber-400">{c.severity || 'REVIEW'}</span>
            <span className="text-gray-600 dark:text-gray-400 w-full">
              {c.kind || 'validation'} · {c.candidate_action || 'REVIEW'}
              {c.row != null ? ` · row ${c.row}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
