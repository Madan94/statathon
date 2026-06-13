'use client';

import { useCallback, useEffect, useState } from 'react';
import { cn } from '@/lib/cn';

interface Binding {
  entity_id: string;
  entity_name: string;
  column_name: string | null;
  confidence: number;
  method: string;
  auto_accepted: boolean;
  user_override: boolean;
  status: 'resolved' | 'pending' | 'unresolved' | 'rejected';
}

interface BindingResult {
  job_id: number;
  total: number;
  resolved: number;
  pending: number;
  unresolved: number;
  bindings: Binding[];
}

export default function EntityBindingPanel({
  jobId,
  columns,
  apiBase = '',
  onAllResolved,
  className,
}: {
  jobId: number;
  columns: string[];
  apiBase?: string;
  onAllResolved?: () => void;
  className?: string;
}) {
  const [data, setData] = useState<BindingResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editColumn, setEditColumn] = useState('');

  const fetchBindings = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/report-builder/bindings/${jobId}`);
      if (res.ok) {
        const json: BindingResult = await res.json();
        setData(json);
        if (json.unresolved === 0 && json.pending === 0) {
          onAllResolved?.();
        }
      }
    } catch (err) {
      setError('Failed to load bindings');
    }
  }, [jobId, apiBase, onAllResolved]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch; state is only set after the awaited response
    fetchBindings();
  }, [fetchBindings]);

  const handleResolve = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/api/report-builder/bindings/${jobId}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ column_names: columns }),
      });
      if (res.ok) {
        const json: BindingResult = await res.json();
        setData(json);
      }
    } catch {
      setError('Resolution failed');
    }
    setLoading(false);
  };

  const handleAcceptAll = async () => {
    if (!data) return;
    const pendingIds = data.bindings
      .filter((b) => b.status === 'pending')
      .map((b) => b.entity_id);
    if (pendingIds.length === 0) return;

    const res = await fetch(`${apiBase}/api/report-builder/bindings/${jobId}/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entity_ids: pendingIds }),
    });
    if (res.ok) fetchBindings();
  };

  const handleOverride = async (entityId: string) => {
    if (!editColumn) return;
    const res = await fetch(`${apiBase}/api/report-builder/bindings/${jobId}/${entityId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ column_name: editColumn }),
    });
    if (res.ok) {
      setEditingId(null);
      setEditColumn('');
      fetchBindings();
    }
  };

  const handleReject = async (entityId: string) => {
    const res = await fetch(`${apiBase}/api/report-builder/bindings/${jobId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entity_ids: [entityId] }),
    });
    if (res.ok) fetchBindings();
  };

  const statusColor = (s: string) => {
    switch (s) {
      case 'resolved': return 'bg-green-100 text-green-700';
      case 'pending': return 'bg-yellow-100 text-yellow-700';
      case 'unresolved': return 'bg-gray-100 text-gray-600';
      case 'rejected': return 'bg-red-100 text-red-700';
      default: return 'bg-gray-100 text-gray-500';
    }
  };

  if (error) {
    return <p className="text-sm text-red-500">{error}</p>;
  }

  return (
    <div className={cn('rounded-lg border bg-white shadow-sm', className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">Entity Bindings</h3>
          {data && (
            <p className="text-xs text-gray-400 mt-0.5">
              {data.resolved} resolved · {data.pending} pending · {data.unresolved} unresolved
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleResolve}
            disabled={loading}
            className="px-3 py-1.5 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Resolving...' : 'Auto-Resolve'}
          </button>
          {data && data.pending > 0 && (
            <button
              onClick={handleAcceptAll}
              className="px-3 py-1.5 text-xs font-medium rounded bg-green-600 text-white hover:bg-green-700"
            >
              Accept All Pending
            </button>
          )}
        </div>
      </div>

      {/* Binding table */}
      {data && data.bindings.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-500">Entity</th>
                <th className="px-4 py-2 text-left font-medium text-gray-500">Column</th>
                <th className="px-4 py-2 text-center font-medium text-gray-500">Confidence</th>
                <th className="px-4 py-2 text-center font-medium text-gray-500">Method</th>
                <th className="px-4 py-2 text-center font-medium text-gray-500">Status</th>
                <th className="px-4 py-2 text-right font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.bindings.map((b) => (
                <tr key={b.entity_id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-medium text-gray-700">{b.entity_name}</td>
                  <td className="px-4 py-2 text-gray-600">
                    {editingId === b.entity_id ? (
                      <select
                        value={editColumn}
                        onChange={(e) => setEditColumn(e.target.value)}
                        className="border rounded px-2 py-1 text-xs w-full"
                      >
                        <option value="">Select column...</option>
                        {columns.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    ) : (
                      b.column_name || <span className="text-gray-400 italic">unbound</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <span className={cn(
                      'inline-block w-12 text-center',
                      b.confidence >= 0.9 ? 'text-green-600' :
                        b.confidence >= 0.7 ? 'text-yellow-600' : 'text-red-500'
                    )}>
                      {(b.confidence * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center text-gray-500">{b.method}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', statusColor(b.status))}>
                      {b.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right">
                    {editingId === b.entity_id ? (
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={() => handleOverride(b.entity_id)}
                          className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="px-2 py-1 text-xs bg-gray-200 rounded hover:bg-gray-300"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={() => { setEditingId(b.entity_id); setEditColumn(b.column_name || ''); }}
                          className="px-2 py-1 text-xs bg-gray-100 rounded hover:bg-gray-200"
                        >
                          Edit
                        </button>
                        {b.status !== 'rejected' && (
                          <button
                            onClick={() => handleReject(b.entity_id)}
                            className="px-2 py-1 text-xs text-red-500 hover:bg-red-50 rounded"
                          >
                            Reject
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.bindings.length === 0 && (
        <p className="p-4 text-sm text-gray-400 text-center">No entity bindings yet</p>
      )}
    </div>
  );
}
