'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { datasetsApi, analysisApi, Dataset, Analysis } from '@/lib/api';
import DataTable from '@/components/DataTable';

export default function DatasetPage() {
  const params = useParams();
  const router = useRouter();
  const id = Number(params.id);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);

  useEffect(() => {
    datasetsApi
      .get(id)
      .then(setDataset)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const result = await analysisApi.run(id);
      setAnalysis(result);
      router.push(`/analysis/${result.id}`);
    } catch (err) {
      console.error(err);
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center">Loading...</div>;
  }

  if (!dataset) {
    return <div className="min-h-screen flex items-center justify-center">Dataset not found</div>;
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black py-16 px-4">
      <div className="max-w-6xl mx-auto">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 mb-6">
          <h1 className="text-3xl font-bold text-black dark:text-zinc-50 mb-4">{dataset.filename}</h1>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Rows</p>
              <p className="text-2xl font-semibold text-gray-900 dark:text-gray-100">{dataset.row_count}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Columns</p>
              <p className="text-2xl font-semibold text-gray-900 dark:text-gray-100">{dataset.column_count}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Status</p>
              <p className="text-2xl font-semibold text-gray-900 dark:text-gray-100">{dataset.status}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Created</p>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {new Date(dataset.created_at).toLocaleDateString()}
              </p>
            </div>
          </div>
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="px-6 py-3 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {analyzing ? 'Analyzing...' : 'Run Analysis'}
          </button>
        </div>
      </div>
    </div>
  );
}

