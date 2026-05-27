'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { FileText, Upload as UploadIcon, Loader2, Trash2, RefreshCw } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import {
  reportBuilderApi,
  ReportTemplate,
  ReportJob,
} from '@/lib/api';

export default function ReportBuilderLanding() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-text-muted">Loading Report Builder…</div>}>
      <ReportBuilderContent />
    </Suspense>
  );
}

function ReportBuilderContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [jobs, setJobs] = useState<ReportJob[]>([]);
  const [analysisId, setAnalysisId] = useState<string>('');
  const [selectedTemplate, setSelectedTemplate] = useState<number | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      const [t, j] = await Promise.all([
        reportBuilderApi.listTemplates(),
        reportBuilderApi.listJobs(),
      ]);
      setTemplates(t);
      setJobs(j);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load Report Builder state'
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    const fromQuery = searchParams.get('analysisId');
    if (fromQuery && !Number.isNaN(Number(fromQuery))) {
      setAnalysisId(fromQuery);
    }
  }, [searchParams]);

  const onUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || !uploadName.trim()) return;
    setUploading(true);
    setError(null);
    try {
      await reportBuilderApi.uploadTemplate(uploadName.trim(), uploadFile);
      setUploadName('');
      setUploadFile(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Template upload failed');
    } finally {
      setUploading(false);
    }
  };

  const onGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    const aid = Number(analysisId);
    if (!aid || Number.isNaN(aid)) {
      setError('Provide a numeric Analysis ID');
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const job = await reportBuilderApi.generate(aid, selectedTemplate);
      router.push(`/report-builder/${job.id}`);
    } catch (err) {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      setError(msg || (err instanceof Error ? err.message : 'Generation failed'));
    } finally {
      setGenerating(false);
    }
  };

  const onDeleteTemplate = async (id: number) => {
    if (!confirm('Delete this template?')) return;
    try {
      await reportBuilderApi.deleteTemplate(id);
      if (selectedTemplate === id) setSelectedTemplate(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  return (
    <>
      <PageHeader
        title="Report Builder"
        description="Reverse-engineered AST · Knowledge graph · Hallucination firewall · Block-based AGUI"
      />

      <div className="space-y-6">
        {error && <Alert variant="error">{error}</Alert>}

        {/* Architecture banner */}
        <Card className="bg-gradient-to-r from-[#0B3B7A]/5 to-[#0B3B7A]/10 border-[#0B3B7A]/20">
          <h2 className="text-sm font-semibold text-primary mb-2">
            6-Phase Architecture
          </h2>
          <ol className="text-xs text-text-muted grid gap-1 md:grid-cols-2">
            <li>
              <span className="font-semibold text-text">Phase 0</span> · PDF →
              AST template (pdfplumber + Gemini Vision)
            </li>
            <li>
              <span className="font-semibold text-text">Phase 1</span> ·
              Knowledge Graph + RDF/Turtle/OWL export
            </li>
            <li>
              <span className="font-semibold text-text">Phase 2</span> · Dual
              memory: Redis STM + Postgres Reflection Ledger
            </li>
            <li>
              <span className="font-semibold text-text">Phase 3</span> · Stateful
              Apache Arrow kernel + Semantic Router
            </li>
            <li>
              <span className="font-semibold text-text">Phase 4</span> ·
              Hallucination Firewall (Scribe + Verifier)
            </li>
            <li>
              <span className="font-semibold text-text">Phase 5/6</span> ·
              Block-based AGUI + tamper-proof PDF export
            </li>
          </ol>
        </Card>

        <div className="grid gap-6 md:grid-cols-2">
          {/* Phase 0: upload template */}
          <Card title="1. Upload MoSPI template (PDF)" description="Phase 0 reverse-engineers an old MoSPI bulletin PDF into a reusable AST. Datasets (CSV/XLSX) go through the Upload page — templates are PDF only.">
            <form onSubmit={onUpload} className="space-y-3">
              <input
                type="text"
                placeholder="Template name (e.g. MoSPI Labour Survey Q4)"
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
                className="w-full rounded-lg border border-border px-3 py-2 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
              />
              <label
                htmlFor="rb-template-pdf"
                className="block rounded-xl border-2 border-dashed border-border hover:border-accent/50 p-5 cursor-pointer text-center transition-colors"
              >
                <UploadIcon className="h-6 w-6 mx-auto text-text-muted mb-2" />
                <p className="text-sm font-medium text-text">
                  {uploadFile ? uploadFile.name : 'Click to choose an old MoSPI PDF'}
                </p>
                <p className="text-xs text-text-muted mt-1">PDF only.</p>
              </label>
              <input
                id="rb-template-pdf"
                type="file"
                accept="application/pdf,.pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  if (f && !/\.pdf$/i.test(f.name) && f.type !== 'application/pdf') {
                    setError('Templates must be a PDF. Use the Upload page for CSV/XLSX datasets.');
                    return;
                  }
                  setUploadFile(f);
                }}
              />
              <Button
                type="submit"
                size="sm"
                disabled={uploading || !uploadFile || !uploadName.trim()}
              >
                {uploading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    Compiling AST…
                  </>
                ) : (
                  <>
                    <UploadIcon className="h-4 w-4 mr-2" />
                    Extract template
                  </>
                )}
              </Button>
              <p className="text-xs text-text-muted">
                Skip this step to use the built-in MoSPI default template, or
                upload from inside any open report via &ldquo;Change template&rdquo;.
              </p>
            </form>
          </Card>

          {/* Generate */}
          <Card title="2. Generate report" description="Run all 6 phases against a completed analysis.">
            <form onSubmit={onGenerate} className="space-y-3">
              <div>
                <label className="text-xs text-text-muted mb-1 block">
                  Completed Analysis ID
                </label>
                <input
                  type="number"
                  placeholder="e.g. 12"
                  value={analysisId}
                  onChange={(e) => setAnalysisId(e.target.value)}
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              </div>
              <div>
                <label className="text-xs text-text-muted mb-1 block">
                  Template (optional)
                </label>
                <select
                  value={selectedTemplate ?? ''}
                  onChange={(e) =>
                    setSelectedTemplate(
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                  className="w-full rounded-lg border border-border px-3 py-2 text-sm bg-surface"
                >
                  <option value="">— Built-in MoSPI default —</option>
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} ({t.block_count} blocks)
                    </option>
                  ))}
                </select>
              </div>
              <Button type="submit" disabled={generating || !analysisId.trim()}>
                {generating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    Queuing…
                  </>
                ) : (
                  'Generate report'
                )}
              </Button>
            </form>
          </Card>
        </div>

        {/* Templates list */}
        <Card title="Uploaded templates" description="Source PDFs reverse-engineered into block ASTs.">
          {loading ? (
            <p className="text-sm text-text-muted">Loading…</p>
          ) : templates.length === 0 ? (
            <p className="text-sm text-text-muted">
              No templates yet — the built-in MoSPI default will be used.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left border-b border-border">
                    <th className="py-2 pr-4 font-medium text-text-muted">ID</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Name</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Pages</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Blocks</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Method</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Hash</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {templates.map((t) => (
                    <tr key={t.id} className="border-b border-border/40">
                      <td className="py-2 pr-4">{t.id}</td>
                      <td className="py-2 pr-4 font-medium">{t.name}</td>
                      <td className="py-2 pr-4">{t.page_count ?? '—'}</td>
                      <td className="py-2 pr-4">{t.block_count}</td>
                      <td className="py-2 pr-4 text-xs">
                        {t.extraction_method ?? '—'}
                      </td>
                      <td className="py-2 pr-4 font-mono text-[10px] text-text-muted">
                        {t.source_hash ? t.source_hash.slice(0, 12) + '…' : '—'}
                      </td>
                      <td className="py-2 pr-4">
                        <button
                          onClick={() => onDeleteTemplate(t.id)}
                          className="text-red-600 hover:text-red-700"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Jobs list */}
        <Card
          title="Recent report jobs"
          description="Each job runs all 6 phases end-to-end."
        >
          <div className="flex justify-end mb-2">
            <button
              onClick={refresh}
              className="text-xs text-text-muted hover:text-text inline-flex items-center gap-1"
            >
              <RefreshCw className="h-3 w-3" /> Refresh
            </button>
          </div>
          {jobs.length === 0 ? (
            <p className="text-sm text-text-muted">No jobs yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left border-b border-border">
                    <th className="py-2 pr-4 font-medium text-text-muted">Job</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Analysis</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Status</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Stage</th>
                    <th className="py-2 pr-4 font-medium text-text-muted">Hash</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j.id} className="border-b border-border/40">
                      <td className="py-2 pr-4 font-mono">#{j.id}</td>
                      <td className="py-2 pr-4">{j.analysis_id}</td>
                      <td className="py-2 pr-4">
                        <StatusBadge status={j.status} />
                      </td>
                      <td className="py-2 pr-4 text-xs text-text-muted">
                        {j.stage ?? '—'}
                      </td>
                      <td className="py-2 pr-4 font-mono text-[10px] text-text-muted">
                        {j.content_hash ? j.content_hash.slice(0, 12) + '…' : '—'}
                      </td>
                      <td className="py-2 pr-4">
                        <Link
                          href={`/report-builder/${j.id}`}
                          className="text-primary hover:underline text-xs"
                        >
                          Open canvas →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variant: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
    exported: 'success',
    verified: 'success',
    running: 'warning',
    pending: 'default',
    awaiting_verification: 'warning',
    failed: 'danger',
  };
  return <Badge variant={variant[status] || 'default'}>{status}</Badge>;
}
