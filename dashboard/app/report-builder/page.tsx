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
  const [activeTab, setActiveTab] = useState<string>('overview');

  // V2 enterprise AST data
  const enterpriseAst = (ast.enterprise_ast as Record<string, unknown>) || {};
  const assets = (ast.extracted_assets as Record<string, unknown> | undefined) || {};
  const pipelineTrace = (ast.pipeline_trace as Record<string, unknown>) || (enterpriseAst.pipeline_trace as Record<string, unknown>) || {};
  const passes = (pipelineTrace.passes as Record<string, Record<string, unknown>>) || {};

  // Content from enterprise AST or top-level
  const semanticAST = (enterpriseAst.semanticAST as Record<string, unknown>) || (ast.semanticAST as Record<string, unknown>) || {};
  const hierarchy = Array.isArray(semanticAST.hierarchy) ? (semanticAST.hierarchy as Array<Record<string, unknown>>) : [];
  const entityGraph = (enterpriseAst.entityGraph as Record<string, unknown>) || (ast.entityGraph as Record<string, unknown>) || {};
  const entities = Array.isArray(entityGraph.entities) ? (entityGraph.entities as Array<Record<string, unknown>>) : [];
  const templateSlots = (ast.templateSlots as Record<string, unknown>) || (enterpriseAst.templateSlots as Record<string, unknown>) || {};
  const slots = Array.isArray(templateSlots.slots) ? (templateSlots.slots as Array<Record<string, unknown>>) : [];
  const tableAST = (enterpriseAst.tableAST as Record<string, unknown>) || {};
  const tables = Array.isArray(tableAST.tables) ? (tableAST.tables as Array<Record<string, unknown>>) : [];
  const factGraph = (enterpriseAst.factGraph as Record<string, unknown>) || {};
  const facts = Array.isArray(factGraph.facts) ? (factGraph.facts as Array<Record<string, unknown>>) : [];
  const questions = Array.isArray(ast.questions) ? (ast.questions as Array<Record<string, unknown>>) : [];
  const blocks = Array.isArray(ast.blocks) ? (ast.blocks as Array<Record<string, unknown>>) : [];

  const textPages = Array.isArray(assets.text_pages) ? (assets.text_pages as Array<Record<string, unknown>>) : [];

  // Check if we have real content (V2 or V1)
  const hasContent = textPages.length > 0 || entities.length > 0 || blocks.length > 0 || Object.keys(enterpriseAst).length > 0;

  const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'blocks', label: `Blocks (${blocks.length})` },
    { id: 'entities', label: `Entities (${entities.length})` },
    { id: 'slots', label: `Slots (${slots.length})` },
    { id: 'tables', label: `Tables (${tables.length})` },
    { id: 'questions', label: `Questions (${questions.length})` },
    { id: 'trace', label: 'Pipeline Trace' },
  ];

  const kindColors: Record<string, string> = {
    heading: 'bg-purple-100 text-purple-700',
    narrative: 'bg-blue-100 text-blue-700',
    table: 'bg-green-100 text-green-700',
    chart: 'bg-orange-100 text-orange-700',
    metric: 'bg-pink-100 text-pink-700',
  };

  const entityTypeColors: Record<string, string> = {
    org: 'bg-indigo-100 text-indigo-700',
    metric: 'bg-emerald-100 text-emerald-700',
    time: 'bg-amber-100 text-amber-700',
    demographic: 'bg-cyan-100 text-cyan-700',
    location: 'bg-rose-100 text-rose-700',
    resource: 'bg-teal-100 text-teal-700',
  };

  return (
    <div className="space-y-4">
      {/* Summary badges */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-6">
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Doc ID</p>
          <p className="text-sm font-mono truncate">{String(ast.doc_id || enterpriseAst.metadata && (enterpriseAst.metadata as Record<string,unknown>).documentId || '—')}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Pages</p>
          <p className="text-sm font-bold">{String(ast.page_count || 0)}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Blocks</p>
          <p className="text-sm font-bold">{blocks.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Entities</p>
          <p className="text-sm font-bold">{entities.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Slots</p>
          <p className="text-sm font-bold">{slots.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Time</p>
          <p className="text-sm font-bold">{pipelineTrace.total_elapsed ? `${pipelineTrace.total_elapsed}s` : '—'}</p>
        </div>
      </div>

      {!hasContent && (
        <Alert variant="error">
          No extraction data found. Re-upload the PDF after ensuring backend services are running.
        </Alert>
      )}

      {/* Tab navigation */}
      <div className="flex gap-1 overflow-x-auto border-b border-border pb-px">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setActiveTab(t.id)}
            className={`shrink-0 px-3 py-2 text-xs font-medium rounded-t-lg transition-colors ${
              activeTab === t.id
                ? 'border-b-2 border-primary text-primary -mb-px'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && (
        <div className="space-y-4">
          {/* Extraction method badge */}
          <div className="flex items-center gap-2">
            <Badge variant="success">{String(ast.extraction_method || 'unknown')}</Badge>
            {pipelineTrace.total_elapsed && (
              <Badge variant="muted">Total: {String(pipelineTrace.total_elapsed)}s</Badge>
            )}
          </div>

          {/* Semantic hierarchy tree */}
          {hierarchy.length > 0 && (
            <div className="rounded-lg border border-border bg-surface p-4">
              <h4 className="text-sm font-semibold text-text mb-3">Document Structure</h4>
              <div className="space-y-1">
                {hierarchy.slice(0, 20).map((node, idx) => {
                  const level = Number(node.level || node.depth || 1);
                  return (
                    <div key={`h-${node.nodeId || idx}`} className="flex items-center gap-2" style={{ paddingLeft: `${(level - 1) * 16}px` }}>
                      <span className="text-[10px] text-text-muted font-mono w-4">{level}</span>
                      <span className={`w-1.5 h-1.5 rounded-full ${level === 1 ? 'bg-primary' : level === 2 ? 'bg-blue-400' : 'bg-gray-300'}`} />
                      <span className="text-xs text-text">{String(node.title || node.name || '—')}</span>
                      {node.pageSpan && (
                        <span className="text-[10px] text-text-muted">p.{JSON.stringify(node.pageSpan)}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Quick facts */}
          {facts.length > 0 && (
            <div className="rounded-lg border border-border bg-surface p-4">
              <h4 className="text-sm font-semibold text-text mb-2">Key Facts ({facts.length})</h4>
              <ul className="space-y-1">
                {facts.slice(0, 8).map((f, idx) => (
                  <li key={`f-${f.factId || idx}`} className="text-xs text-text flex gap-2">
                    <span className="text-text-muted shrink-0">{idx + 1}.</span>
                    <span>{String(f.statement || f.text || '—')}</span>
                    {f.confidence && <Badge variant="muted" className="text-[9px]">{Math.round(Number(f.confidence) * 100)}%</Badge>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Text pages collapsible */}
          {textPages.length > 0 && (
            <details className="rounded-lg border border-border bg-surface">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-text">
                Extracted Text ({textPages.length} pages)
              </summary>
              <div className="px-4 pb-4 space-y-2">
                {textPages.slice(0, 5).map((tp, idx) => (
                  <details key={`tp-${tp.page_index ?? idx}`} className="rounded border border-border/60">
                    <summary className="cursor-pointer px-3 py-1.5 text-xs text-text-muted">
                      Page {Number(tp.page_index ?? idx) + 1}
                    </summary>
                    <pre className="px-3 pb-2 whitespace-pre-wrap text-[11px] text-text-muted max-h-40 overflow-auto">
                      {String(tp.text || '(empty)')}
                    </pre>
                  </details>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {activeTab === 'blocks' && (
        <div className="space-y-3">
          {blocks.length === 0 ? (
            <p className="text-sm text-text-muted">No blocks extracted.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead className="bg-surface">
                  <tr className="border-b border-border">
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Block ID</th>
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Type</th>
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Section</th>
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Title</th>
                  </tr>
                </thead>
                <tbody>
                  {blocks.map((b, idx) => (
                    <tr key={`${b.block_id ?? idx}`} className="border-b border-border/30 hover:bg-surface/50">
                      <td className="py-2 px-3 font-mono text-text-muted">{String(b.block_id || '—')}</td>
                      <td className="py-2 px-3">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${kindColors[String(b.kind)] || 'bg-gray-100 text-gray-700'}`}>
                          {String(b.kind || '—')}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-text-muted">{String(b.section || '—')}</td>
                      <td className="py-2 px-3 text-text max-w-[300px] truncate">{String(b.title || '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'entities' && (
        <div className="space-y-3">
          {entities.length === 0 ? (
            <p className="text-sm text-text-muted">No entities extracted.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {Object.entries(
                  entities.reduce<Record<string, number>>((acc, e) => {
                    const t = String(e.type || 'unknown');
                    acc[t] = (acc[t] || 0) + 1;
                    return acc;
                  }, {})
                ).map(([type, count]) => (
                  <span key={type} className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium ${entityTypeColors[type] || 'bg-gray-100 text-gray-700'}`}>
                    {type}: {count}
                  </span>
                ))}
              </div>
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-xs">
                  <thead className="bg-surface">
                    <tr className="border-b border-border">
                      <th className="py-2.5 px-3 text-left text-text-muted font-medium">ID</th>
                      <th className="py-2.5 px-3 text-left text-text-muted font-medium">Type</th>
                      <th className="py-2.5 px-3 text-left text-text-muted font-medium">Name</th>
                      <th className="py-2.5 px-3 text-left text-text-muted font-medium">Context</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entities.slice(0, 30).map((e, idx) => (
                      <tr key={`${e.entityId || idx}`} className="border-b border-border/30 hover:bg-surface/50">
                        <td className="py-2 px-3 font-mono text-text-muted text-[10px]">{String(e.entityId || '—')}</td>
                        <td className="py-2 px-3">
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${entityTypeColors[String(e.type)] || 'bg-gray-100 text-gray-700'}`}>
                            {String(e.type || '—')}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-text font-medium">{String(e.name || '—')}</td>
                        <td className="py-2 px-3 text-text-muted max-w-[200px] truncate">{String(e.context || '—')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {activeTab === 'slots' && (
        <div className="space-y-3">
          {slots.length === 0 ? (
            <p className="text-sm text-text-muted">No template slots detected.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead className="bg-surface">
                  <tr className="border-b border-border">
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Slot ID</th>
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Type</th>
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Entity Ref</th>
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Current Value</th>
                    <th className="py-2.5 px-3 text-left text-text-muted font-medium">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {slots.slice(0, 30).map((s, idx) => (
                    <tr key={`${s.slotId || idx}`} className="border-b border-border/30 hover:bg-surface/50">
                      <td className="py-2 px-3 font-mono text-text-muted text-[10px]">{String(s.slotId || '—')}</td>
                      <td className="py-2 px-3">
                        <Badge variant="muted">{String(s.slotType || '—')}</Badge>
                      </td>
                      <td className="py-2 px-3 font-mono text-[10px]">{String(s.entityRef || '—')}</td>
                      <td className="py-2 px-3 text-text font-medium">{String(s.currentValue || '—')}</td>
                      <td className="py-2 px-3 text-text-muted max-w-[250px] truncate">{String(s.description || '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'tables' && (
        <div className="space-y-3">
          {tables.length === 0 ? (
            <p className="text-sm text-text-muted">No tables extracted.</p>
          ) : (
            <div className="space-y-3">
              {tables.slice(0, 10).map((t, idx) => (
                <div key={`${t.tableId || idx}`} className="rounded-lg border border-border bg-surface p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant="success">table</Badge>
                    <span className="text-sm font-medium text-text">{String(t.title || `Table ${idx + 1}`)}</span>
                    <span className="text-[10px] text-text-muted">{String(t.pageRef || '')}</span>
                    {t.source && <Badge variant="muted">{String(t.source)}</Badge>}
                  </div>
                  {Array.isArray(t.columns) && (t.columns as string[]).length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-2">
                      {(t.columns as string[]).slice(0, 10).map((col, ci) => (
                        <span key={ci} className="text-[10px] bg-green-50 text-green-700 rounded px-1.5 py-0.5">{col}</span>
                      ))}
                    </div>
                  )}
                  {Array.isArray(t.sampleRows) && (t.sampleRows as unknown[]).length > 0 && (
                    <pre className="text-[10px] text-text-muted bg-gray-50 rounded p-2 overflow-auto max-h-24">
                      {JSON.stringify(t.sampleRows, null, 2)}
                    </pre>
                  )}
                  <p className="text-[10px] text-text-muted mt-1">Rows: {String(t.rowCount || '—')}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'questions' && (
        <div className="space-y-3">
          {questions.length === 0 ? (
            <p className="text-sm text-text-muted">No questions generated.</p>
          ) : (
            <div className="space-y-2">
              {questions.slice(0, 20).map((q, idx) => (
                <div key={`${q.id || idx}`} className="flex gap-3 items-start rounded-lg border border-border bg-surface px-3 py-2">
                  <span className="text-xs text-text-muted font-mono shrink-0 w-5">{idx + 1}</span>
                  <div className="flex-1">
                    <p className="text-xs text-text">{String(q.question || '—')}</p>
                    {(q.section || q.answerType) && (
                      <div className="flex gap-1.5 mt-1">
                        {q.section && <Badge variant="muted">{String(q.section)}</Badge>}
                        {q.answerType && <Badge variant="default">{String(q.answerType)}</Badge>}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'trace' && (
        <div className="space-y-4">
          {Object.keys(passes).length === 0 ? (
            <p className="text-sm text-text-muted">No pipeline trace available. Re-extract with latest backend.</p>
          ) : (
            <>
              {/* Timing bar chart */}
              <div className="rounded-lg border border-border bg-surface p-4">
                <h4 className="text-sm font-semibold text-text mb-3">Pipeline Timing</h4>
                <div className="space-y-2">
                  {Object.entries(passes).map(([name, data]) => {
                    const elapsed = Number(data.elapsed_s || 0);
                    const total = Number(pipelineTrace.total_elapsed || 1);
                    const pct = Math.min(Math.round((elapsed / total) * 100), 100);
                    return (
                      <div key={name} className="flex items-center gap-3">
                        <span className="text-[10px] font-mono text-text-muted w-28 shrink-0 truncate">{name}</span>
                        <div className="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary/70 rounded-full flex items-center justify-end pr-2"
                            style={{ width: `${Math.max(pct, 4)}%` }}
                          >
                            <span className="text-[9px] text-white font-medium">{elapsed}s</span>
                          </div>
                        </div>
                        <span className="text-[10px] text-text-muted w-8 text-right">{pct}%</span>
                      </div>
                    );
                  })}
                </div>
                <p className="text-xs text-text-muted mt-3 border-t border-border pt-2">
                  Total: <strong>{String(pipelineTrace.total_elapsed || 0)}s</strong>
                </p>
              </div>

              {/* Quality metrics */}
              <div className="rounded-lg border border-border bg-surface p-4">
                <h4 className="text-sm font-semibold text-text mb-3">Quality Metrics</h4>
                <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
                  {passes.pass0_rasterize && (
                    <div>
                      <p className="text-[10px] text-text-muted">Images Rasterized</p>
                      <p className="text-sm font-bold">{String((passes.pass0_rasterize as Record<string,unknown>).images || 0)}</p>
                    </div>
                  )}
                  {passes.pass1_layout && (
                    <div>
                      <p className="text-[10px] text-text-muted">Layout Regions</p>
                      <p className="text-sm font-bold">{String((passes.pass1_layout as Record<string,unknown>).total_regions || 0)}</p>
                    </div>
                  )}
                  {passes.pass2_vlm && (
                    <div>
                      <p className="text-[10px] text-text-muted">VLM Success Rate</p>
                      <p className="text-sm font-bold">{String((passes.pass2_vlm as Record<string,unknown>).vlm_success_rate || 0)}%</p>
                    </div>
                  )}
                  {passes.pass3_semantic && (
                    <div>
                      <p className="text-[10px] text-text-muted">Semantic Source</p>
                      <p className="text-sm font-bold">{String((passes.pass3_semantic as Record<string,unknown>).source || '—')}</p>
                    </div>
                  )}
                  {passes.pass1_layout && (
                    <div>
                      <p className="text-[10px] text-text-muted">LayoutLM Used</p>
                      <p className="text-sm font-bold">{(passes.pass1_layout as Record<string,unknown>).layoutlm_used ? '✓ Yes' : '✗ Fallback'}</p>
                    </div>
                  )}
                  {passes.pass3_semantic && (
                    <div>
                      <p className="text-[10px] text-text-muted">Hierarchy Nodes</p>
                      <p className="text-sm font-bold">{String((passes.pass3_semantic as Record<string,unknown>).hierarchy_nodes || 0)}</p>
                    </div>
                  )}
                  {passes.pass5_gemini && (
                    <div>
                      <p className="text-[10px] text-text-muted">Gemini Status</p>
                      <p className="text-sm font-bold">{String((passes.pass5_gemini as Record<string,unknown>).status || '—')}</p>
                    </div>
                  )}
                  {passes.pass4_assembly && (
                    <div>
                      <p className="text-[10px] text-text-muted">Tables Found</p>
                      <p className="text-sm font-bold">{String((passes.pass4_assembly as Record<string,unknown>).tables || 0)}</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Raw trace JSON */}
              <details className="rounded-lg border border-border bg-surface">
                <summary className="cursor-pointer px-4 py-2 text-xs font-medium text-text-muted">
                  Raw trace JSON
                </summary>
                <pre className="px-4 pb-3 text-[10px] text-text-muted overflow-auto max-h-60">
                  {JSON.stringify(pipelineTrace, null, 2)}
                </pre>
              </details>
            </>
          )}
        </div>
      )}
    </div>
  );
}
