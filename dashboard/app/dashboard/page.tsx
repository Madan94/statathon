'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  BarChart3,
  FileText,
  FolderOpen,
  LineChart,
  Upload,
  ArrowRight,
} from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { authApi, dashboardApi, type DashboardSummary } from '@/lib/api';
import Card from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: number;
  hint: string;
  icon: typeof BarChart3;
}) {
  return (
    <Card className="p-5 border-[#e2e8f0] bg-white shadow-sm ring-1 ring-black/5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-[#64748b]">{label}</p>
          <p className="mt-2 text-3xl font-bold text-[#0a1f44]">{value}</p>
          <p className="mt-1 text-xs text-[#64748b]">{hint}</p>
        </div>
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#fffbeb] text-[#0a1f44]">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      </div>
    </Card>
  );
}

function formatDate(iso: string | null) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [userName, setUserName] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [me, data] = await Promise.all([authApi.me(), dashboardApi.getSummary()]);
        if (cancelled) return;
        setUserName(me.full_name || me.email);
        setSummary(data);
      } catch (e: unknown) {
        if (!cancelled) {
          const ax = e as { response?: { data?: { detail?: string } } };
          setError(ax.response?.data?.detail || 'Could not load dashboard');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader
        title={userName ? `Welcome, ${userName}` : 'Dashboard'}
        description="Your survey intelligence at a glance — datasets, analyses, and reports."
        actions={
          <Link href="/upload">
            <Button className="bg-[#0a1f44] hover:bg-[#0f2d52] text-white">
              <Upload className="h-4 w-4" aria-hidden />
              Upload dataset
            </Button>
          </Link>
        }
      />

      {error && <Alert variant="error">{error}</Alert>}

      {loading && (
        <p className="text-sm text-[#64748b]">Loading analytics…</p>
      )}

      {summary && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <StatCard
              label="Datasets uploaded"
              value={summary.datasets_count}
              hint="Total files in your workspace"
              icon={FolderOpen}
            />
            <StatCard
              label="Analyses run"
              value={summary.analyses_count}
              hint={`${summary.analyses_complete_count} completed`}
              icon={LineChart}
            />
            <StatCard
              label="Reports generated"
              value={summary.reports_count}
              hint="Audit PDFs + exported builder jobs"
              icon={FileText}
            />
            <StatCard
              label="Report builder jobs"
              value={summary.report_jobs_count}
              hint={`${summary.report_jobs_exported_count} exported`}
              icon={BarChart3}
            />
          </div>

          <Card className="overflow-hidden border-[#e2e8f0] ring-1 ring-black/5">
            <div className="flex items-center justify-between gap-4 py-4 border-b border-[#e2e8f0]">
              <h2 className="text-lg font-bold text-[#0a1f44]">Latest uploaded datasets</h2>
            </div>
            {summary.latest_datasets.length === 0 ? (
              <div className="p-8 text-center">
                <p className="text-sm text-[#64748b]">No datasets yet.</p>
                <Link href="/upload" className="inline-block mt-4">
                  <Button variant="secondary" size="sm">
                    Upload your first dataset
                  </Button>
                </Link>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-[#64748b] border-b border-[#e2e8f0]">
                      <th className="px-5 py-3 font-semibold">File</th>
                      <th className="px-5 py-3 font-semibold">Status</th>
                      <th className="px-5 py-3 font-semibold">Rows</th>
                      <th className="px-5 py-3 font-semibold">Columns</th>
                      <th className="px-5 py-3 font-semibold">Uploaded</th>
                      <th className="px-5 py-3 font-semibold" />
                    </tr>
                  </thead>
                  <tbody>
                    {summary.latest_datasets.map((ds) => (
                      <tr
                        key={ds.id}
                        className="border-b border-[#e2e8f0] last:border-0 hover:bg-[#fffbeb]/40"
                      >
                        <td className="px-5 py-3 font-medium text-[#0a0a0a] max-w-[200px] truncate">
                          {ds.filename}
                        </td>
                        <td className="px-5 py-3">
                          <span className="inline-flex rounded-full bg-[#eef4ff] px-2.5 py-0.5 text-xs font-medium text-[#0a1f44] capitalize">
                            {ds.status}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-[#64748b]">{ds.row_count}</td>
                        <td className="px-5 py-3 text-[#64748b]">{ds.column_count}</td>
                        <td className="px-5 py-3 text-[#64748b] whitespace-nowrap">
                          {formatDate(ds.created_at)}
                        </td>
                        <td className="px-5 py-3 text-right">
                          <Link
                            href={`/datasets/${ds.id}`}
                            className="text-sm font-semibold text-[#0a1f44] hover:underline"
                          >
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
