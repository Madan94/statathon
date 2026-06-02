'use client';

import { useEffect, useMemo, useState } from 'react';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/ui/Card';
import { Alert } from '@/components/ui/Alert';
import { dashboardApi, type ActivityItem } from '@/lib/api';
import { formatIndiaTime } from '@/lib/datetime';

export default function ActivityPage() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await dashboardApi.getActivity(200);
        if (!cancelled) setItems(data);
      } catch (e: unknown) {
        if (!cancelled) {
          const ax = e as { response?: { data?: { detail?: string } }; message?: string };
          setError(ax.response?.data?.detail || ax.message || 'Failed to load activity');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((row) => {
      const hay = `${row.event_type} ${row.title} ${JSON.stringify(row.metadata || {})}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, query]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="All Activity"
        description="Audit trail and account-level metadata across uploads, analyses, template extraction, report jobs, and corrections."
      />

      {error && <Alert variant="error">{error}</Alert>}

      <Card className="p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search event type, title, or metadata"
            className="w-full md:max-w-md rounded-lg border border-border px-3 py-2 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
          <p className="text-xs text-text-muted">{filtered.length} events</p>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {loading ? (
          <div className="p-4 text-sm text-text-muted">Loading activity…</div>
        ) : filtered.length === 0 ? (
          <div className="p-4 text-sm text-text-muted">No activity found for this account.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-border">
                  <th className="px-4 py-3 font-medium ">Timestamp</th>
                  <th className="px-4 py-3 font-medium ">Type</th>
                  <th className="px-4 py-3 font-medium ">Activity</th>
                  <th className="px-4 py-3 font-medium ">Metadata</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item, idx) => (
                  <tr key={`${item.event_type}-${item.created_at || idx}`} className="border-b border-border/40 align-top">
                    <td className="px-4 py-3 whitespace-nowrap ">
                      {formatIndiaTime(item.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-md bg-surface px-2 py-0.5 text-xs font-mono ">
                        {item.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-text">{item.title}</td>
                    <td className="px-4 py-3 min-w-[360px]">
                      <pre className="text-xs  whitespace-pre-wrap">
                        {JSON.stringify(item.metadata || {}, null, 2)}
                      </pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
