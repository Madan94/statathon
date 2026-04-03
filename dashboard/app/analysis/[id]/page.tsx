'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { analysisApi, AnalysisResult, OutlierResult } from '@/lib/api';
import OutlierCard from '@/components/OutlierCard';
import ConfidenceScore from '@/components/ConfidenceScore';

export default function AnalysisPage() {
  const params = useParams();
  const id = Number(params.id);
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [decisions, setDecisions] = useState<Record<string, 'keep' | 'delete' | 'normalize'>>({});

  useEffect(() => {
    analysisApi
      .getResults(id)
      .then(setResults)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const handleDecision = (column: string, decision: 'keep' | 'delete' | 'normalize') => {
    setDecisions((prev) => ({ ...prev, [column]: decision }));
  };

  const handleSubmit = async () => {
    try {
      await analysisApi.submitDecisions(id, decisions);
      alert('Decisions submitted successfully');
    } catch (err) {
      console.error(err);
      alert('Failed to submit decisions');
    }
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center">Loading analysis results...</div>;
  }

  if (!results) {
    return <div className="min-h-screen flex items-center justify-center">Analysis not found</div>;
  }

  const outlierEntries = Object.entries(results.outliers || {});

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black py-16 px-4">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold text-black dark:text-zinc-50 mb-8">Analysis Results</h1>

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">Health Summary</h2>
          <pre className="bg-gray-100 dark:bg-gray-900 p-4 rounded overflow-auto text-sm">
            {JSON.stringify(results.health, null, 2)}
          </pre>
        </div>

        {results.semantic && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">Semantic Mapping</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {Object.entries(results.semantic).map(([col, label]) => (
                <div key={col} className="p-3 bg-gray-50 dark:bg-gray-900 rounded">
                  <span className="font-medium text-gray-900 dark:text-gray-100">{col}:</span>{' '}
                  <span className="text-gray-600 dark:text-gray-400">{label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {outlierEntries.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">Outlier Detection</h2>
            {outlierEntries.map(([column, outlier]) => (
              <OutlierCard
                key={column}
                column={column}
                indices={[...(outlier.zscore || []), ...(outlier.iqr || [])]}
                confidence={outlier.confidence || 0.5}
                risk={outlier.risk || 'medium'}
                onDecision={(decision) => handleDecision(column, decision)}
              />
            ))}
            <button
              onClick={handleSubmit}
              className="mt-4 px-6 py-3 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
            >
              Submit Decisions
            </button>
          </div>
        )}

        {results.content_hash && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">Report Hash</h2>
            <p className="font-mono text-sm text-gray-600 dark:text-gray-400 break-all">{results.content_hash}</p>
          </div>
        )}
      </div>
    </div>
  );
}

