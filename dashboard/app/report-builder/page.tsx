'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Upload as UploadIcon, Loader2, Trash2, RefreshCw } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import {
  reportBuilderApi,
  ReportTemplate,
  ReportJob,
  TemplateExtractionJob,
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
  const [extractJob, setExtractJob] = useState<TemplateExtractionJob | null>(null);
  const [extractedTemplateAst, setExtractedTemplateAst] = useState<Record<string, unknown> | null>(null);
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
    setExtractJob(null);
    setError(null);
    try {
      const queued = await reportBuilderApi.extractTemplateAsync(uploadName.trim(), uploadFile);
      setExtractJob(queued);
      const final = await reportBuilderApi.pollTemplateExtractJob(queued.id, (job) => {
        setExtractJob(job);
      });
      if (final.status === 'failed') {
        throw new Error(final.error_message || 'Template extraction failed');
      }
      if (final.created_template_id) {
        const tpl = await reportBuilderApi.getTemplate(final.created_template_id);
        setExtractedTemplateAst(
          tpl && typeof tpl === 'object' && 'ast' in tpl
            ? (tpl as { ast: Record<string, unknown> }).ast
            : null
        );
      }
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

        <div className="grid gap-6 md:grid-cols-2">
          {/* Phase 0: upload template */}
          <Card title="1. Upload MoSPI template (PDF)">
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
                    Extracting full production AST…
                  </>
                ) : (
                  <>
                    <UploadIcon className="h-4 w-4 mr-2" />
                    Extract template
                  </>
                )}
              </Button>
              {extractJob && (
                <div className="rounded-lg border border-border bg-surface px-3 py-2">
                  <p className="text-xs text-text-muted">
                    Stage: <span className="font-medium text-text">{extractJob.stage || 'queued'}</span>
                    {' · '}
                    Progress: <span className="font-medium text-text">{extractJob.progress_pct}%</span>
                  </p>
                  {extractJob.source_hash && (
                    <p className="text-[11px] text-text-muted mt-1">
                      SHA256: <span className="font-mono">{extractJob.source_hash}</span>
                    </p>
                  )}
                  {extractJob.vault_object_key && (
                    <p className="text-[11px] text-text-muted mt-1">
                      Vault key: <span className="font-mono break-all">{extractJob.vault_object_key}</span>
                    </p>
                  )}
                </div>
              )}
            </form>
          </Card>

          {/* Generate */}
          <Card title="2. Generate report">
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
                  <option value="">Choose your Template</option>
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

        {extractedTemplateAst && (
          <Card
            title="Extracted PDF layout and blueprint"
            description="Actual structure, text snippets, table signals and generated question blueprint from uploaded PDF."
          >
            <TemplateExtractionPreview ast={extractedTemplateAst} />
          </Card>
        )}

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

function TemplateExtractionPreview({ ast }: { ast: Record<string, unknown> }) {
  const layout = (ast.extracted_layout as Record<string, unknown> | undefined) || {};
  const assets = (ast.extracted_assets as Record<string, unknown> | undefined) || {};
  const pagePreview = Array.isArray(layout.page_layout_preview)
    ? (layout.page_layout_preview as Array<Record<string, unknown>>)
    : [];
  const textPages = Array.isArray(assets.text_pages)
    ? (assets.text_pages as Array<Record<string, unknown>>)
    : [];
  const tableAssets = Array.isArray(assets.tables)
    ? (assets.tables as Array<Record<string, unknown>>)
    : [];
  const imageAssets = Array.isArray(assets.images)
    ? (assets.images as Array<Record<string, unknown>>)
    : [];
  const hasRealExtractedAssets =
    textPages.length > 0 || tableAssets.length > 0 || imageAssets.length > 0;
  const topics = Array.isArray(ast.main_topics) ? (ast.main_topics as Array<Record<string, unknown>>) : [];
  const subTopics = Array.isArray(ast.sub_topics) ? (ast.sub_topics as Array<Record<string, unknown>>) : [];
  const questions = Array.isArray(ast.questions) ? (ast.questions as Array<Record<string, unknown>>) : [];
  const blocks = Array.isArray(ast.blocks) ? (ast.blocks as Array<Record<string, unknown>>) : [];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[11px] text-text-muted">Doc ID</p>
          <p className="text-sm font-medium">{String(ast.doc_id || '—')}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[11px] text-text-muted">Pages</p>
          <p className="text-sm font-medium">{String(ast.page_count || 0)}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[11px] text-text-muted">Blocks</p>
          <p className="text-sm font-medium">{blocks.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[11px] text-text-muted">Extraction</p>
          <p className="text-sm font-medium">{String(ast.extraction_method || '—')}</p>
        </div>
      </div>

      {!hasRealExtractedAssets && (
        <Alert variant="error">
          Real PDF content artifacts are missing for this template. Re-extract after backend restart.
          If this persists, PDF extraction dependencies may be unavailable.
        </Alert>
      )}

      {pagePreview.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-text">Extracted layout & text snippets</h4>
          {pagePreview.slice(0, 8).map((page, idx) => {
            const headings = Array.isArray(page.headings) ? (page.headings as string[]) : [];
            return (
              <div key={`${page.page_index ?? idx}`} className="rounded-lg border border-border bg-surface p-3">
                <p className="text-xs text-text-muted mb-1">
                  Page {Number(page.page_index ?? idx) + 1} · Tables: {String(page.table_count ?? 0)}
                </p>
                {headings.length > 0 && (
                  <p className="text-xs mb-1">
                    <span className="text-text-muted">Headings:</span> {headings.slice(0, 6).join(' | ')}
                  </p>
                )}
                <p className="text-xs text-text-muted whitespace-pre-wrap">
                  {String(page.paragraph_excerpt || '(no paragraph excerpt)')}
                </p>
              </div>
            );
          })}
        </div>
      )}

      {textPages.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-text">Extracted text (by page)</h4>
          {textPages.slice(0, 6).map((tp, idx) => (
            <details key={`tp-${tp.page_index ?? idx}`} className="rounded-lg border border-border bg-surface">
              <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-text">
                Page {Number(tp.page_index ?? idx) + 1} text
              </summary>
              <pre className="px-3 pb-3 whitespace-pre-wrap text-xs text-text-muted">
                {String(tp.text || '(no text extracted)')}
              </pre>
            </details>
          ))}
        </div>
      )}

      {tableAssets.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-text">Extracted tables</h4>
          {tableAssets.slice(0, 8).map((entry, idx) => {
            const tables = Array.isArray(entry.tables) ? (entry.tables as Array<Record<string, unknown>>) : [];
            return (
              <div key={`tbl-${entry.page_index ?? idx}`} className="rounded-lg border border-border bg-surface p-3">
                <p className="text-xs text-text-muted mb-2">Page {Number(entry.page_index ?? idx) + 1}</p>
                {tables.length === 0 ? (
                  <p className="text-xs text-text-muted">No table preview.</p>
                ) : (
                  <div className="space-y-2">
                    {tables.map((t, ti) => (
                      <div key={`t-${ti}`} className="rounded border border-border/70 p-2">
                        <p className="text-[11px] text-text-muted mb-1">
                          rows: {String(t.row_count ?? 0)} · cols: {String(t.col_count ?? 0)}
                        </p>
                        <pre className="text-[11px] text-text-muted whitespace-pre-wrap">
                          {JSON.stringify(t.preview_rows ?? [], null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {imageAssets.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-text">Extracted image/layout regions</h4>
          {imageAssets.slice(0, 8).map((entry, idx) => {
            const images = Array.isArray(entry.images) ? (entry.images as Array<Record<string, unknown>>) : [];
            return (
              <div key={`img-${entry.page_index ?? idx}`} className="rounded-lg border border-border bg-surface p-3">
                <p className="text-xs text-text-muted mb-2">
                  Page {Number(entry.page_index ?? idx) + 1} · image regions: {images.length}
                </p>
                {images.length > 0 && (
                  <pre className="text-[11px] text-text-muted whitespace-pre-wrap">
                    {JSON.stringify(images, null, 2)}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      )}

      {(topics.length > 0 || subTopics.length > 0 || questions.length > 0) && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-text">Extracted semantic blueprint</h4>
          {topics.length > 0 && (
            <p className="text-xs text-text-muted">
              Topics: {topics.map((t) => String(t.name || t.id || '—')).join(', ')}
            </p>
          )}
          {subTopics.length > 0 && (
            <p className="text-xs text-text-muted">
              Subtopics: {subTopics.map((s) => String(s.name || '—')).join(', ')}
            </p>
          )}
          {questions.length > 0 && (
            <div className="rounded-lg border border-border bg-surface p-3">
              <p className="text-xs text-text-muted mb-2">Generated questions</p>
              <ul className="space-y-1 text-xs">
                {questions.slice(0, 12).map((q, idx) => (
                  <li key={`${q.id ?? idx}`} className="text-text">
                    {idx + 1}. {String(q.question || '—')}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {blocks.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-text">Extracted block layout</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left border-b border-border">
                  <th className="py-2 pr-3 text-text-muted font-medium">Block ID</th>
                  <th className="py-2 pr-3 text-text-muted font-medium">Kind</th>
                  <th className="py-2 pr-3 text-text-muted font-medium">Section</th>
                  <th className="py-2 pr-3 text-text-muted font-medium">Title</th>
                </tr>
              </thead>
              <tbody>
                {blocks.slice(0, 24).map((b, idx) => (
                  <tr key={`${b.block_id ?? idx}`} className="border-b border-border/40">
                    <td className="py-2 pr-3 font-mono">{String(b.block_id || '—')}</td>
                    <td className="py-2 pr-3">{String(b.kind || '—')}</td>
                    <td className="py-2 pr-3">{String(b.section || '—')}</td>
                    <td className="py-2 pr-3">{String(b.title || '—')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
