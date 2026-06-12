'use client';

import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Upload as UploadIcon,
  Loader2,
  Trash2,
  RefreshCw,
  Link2,
  ArrowRight,
  Eye,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import TemplateExtractionModal, {
  type TemplateExtractionModalPhase,
} from '@/components/report-builder/TemplateExtractionModal';
import {
  TypeFilterDropdown,
  collectTypeOptions,
  useTypeFilter,
} from '@/components/report-builder/TypeFilterDropdown';
import {
  reportBuilderApi,
  ReportTemplate,
  ReportJob,
  TemplateExtractionJob,
} from '@/lib/api';
import { buildEntityNameMap, resolveEntityLabel } from '@/lib/entityDisplayUtils';

export default function ReportBuilderLanding() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-text-muted">Loading Report Builderâ€¦</div>}>
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
  const [extractionModalOpen, setExtractionModalOpen] = useState(false);
  const [extractionModalPhase, setExtractionModalPhase] =
    useState<TemplateExtractionModalPhase>('running');
  const [extractionError, setExtractionError] = useState<string | null>(null);
  const [pendingTemplateName, setPendingTemplateName] = useState('');
  const [extractedTemplateAst, setExtractedTemplateAst] = useState<Record<string, unknown> | null>(null);
  const [viewingTemplateId, setViewingTemplateId] = useState<number | null>(null);
  const [previewTemplateName, setPreviewTemplateName] = useState<string | null>(null);
  const [loadingTemplateAst, setLoadingTemplateAst] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const previewRef = useRef<HTMLDivElement>(null);
  const loadedTemplateIdRef = useRef<number | null>(null);
  const bindingAstId = searchParams.get('binding_ast_id');
  const bindingTemplateId = searchParams.get('template_id');
  const bindingSignature = searchParams.get('signature');
  const bindingStatus = searchParams.get('execution_status');

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

  const loadExtractedTemplate = async (
    templateId: number,
    scrollToPreview = false,
    updateUrl = true
  ) => {
    setViewingTemplateId(templateId);
    setLoadingTemplateAst(true);
    setError(null);
    try {
      const tpl = await reportBuilderApi.getTemplate(templateId);
      loadedTemplateIdRef.current = templateId;
      setPreviewTemplateName(tpl.name);
      setExtractedTemplateAst(
        tpl.ast && typeof tpl.ast === 'object' ? tpl.ast : null
      );
      if (updateUrl) {
        const params = new URLSearchParams(searchParams.toString());
        params.set('templateId', String(templateId));
        router.replace(`/report-builder?${params.toString()}`, { scroll: false });
      }
      if (scrollToPreview) {
        requestAnimationFrame(() => {
          previewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
    } catch (err) {
      loadedTemplateIdRef.current = null;
      setExtractedTemplateAst(null);
      setPreviewTemplateName(null);
      setError(err instanceof Error ? err.message : 'Failed to load template AST');
    } finally {
      setLoadingTemplateAst(false);
    }
  };

  useEffect(() => {
    const tid = searchParams.get('templateId');
    if (!tid || Number.isNaN(Number(tid)) || loading) return;
    const id = Number(tid);
    if (loadedTemplateIdRef.current === id) return;
    void loadExtractedTemplate(id, false, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deep-link load once per template id
  }, [searchParams, loading]);

  const onUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || !uploadName.trim()) return;
    setUploading(true);
    setExtractJob(null);
    setExtractionError(null);
    setExtractionModalPhase('running');
    setPendingTemplateName(uploadName.trim());
    setExtractionModalOpen(true);
    setError(null);
    try {
      const queued = await reportBuilderApi.extractTemplateAsync(uploadName.trim(), uploadFile);
      setExtractJob(queued);
      const final = await reportBuilderApi.pollTemplateExtractJob(queued.id, (job) => {
        setExtractJob(job);
      });
      setExtractJob(final);
      if (final.status === 'failed') {
        setExtractionModalPhase('failed');
        setExtractionError(final.error_message || 'Template extraction failed');
        return;
      }
      if (final.created_template_id) {
        await loadExtractedTemplate(final.created_template_id, true);
      }
      setExtractionModalPhase('success');
      setUploadName('');
      setUploadFile(null);
      await refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Template upload failed';
      setExtractionModalPhase('failed');
      setExtractionError(msg);
      setError(msg);
    } finally {
      setUploading(false);
    }
  };

  const closeExtractionModal = () => {
    setExtractionModalOpen(false);
    setExtractionError(null);
    if (extractionModalPhase !== 'success') {
      setExtractJob(null);
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
      if (viewingTemplateId === id) {
        setViewingTemplateId(null);
        setExtractedTemplateAst(null);
        setPreviewTemplateName(null);
        loadedTemplateIdRef.current = null;
        const params = new URLSearchParams(searchParams.toString());
        params.delete('templateId');
        const qs = params.toString();
        router.replace(qs ? `/report-builder?${qs}` : '/report-builder', { scroll: false });
      }
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
        actions={
          <Link href="/report-builder/binding">
            <Button variant="outline" size="sm">
              <Link2 className="h-4 w-4" /> Bind dataset
            </Button>
          </Link>
        }
      />

      <TemplateExtractionModal
        open={extractionModalOpen}
        templateName={pendingTemplateName || uploadName || 'Template'}
        job={extractJob}
        phase={extractionModalPhase}
        errorMessage={extractionError}
        onClose={closeExtractionModal}
        onViewBlueprint={closeExtractionModal}
        onRetry={closeExtractionModal}
      />

      <div className="space-y-6">
        {error && !extractionModalOpen && <Alert variant="error">{error}</Alert>}

        {bindingAstId && (
          <Alert variant={bindingStatus === 'DEGRADED' ? 'warning' : 'success'}>
            <div className="space-y-1">
              <p className="font-semibold">Execution bundle prepared from binder</p>
              <p className="text-sm">
                Status: <span className="font-mono">{bindingStatus || 'READY'}</span>
                {bindingTemplateId ? (
                  <> · Template: <span className="font-mono">{bindingTemplateId}</span></>
                ) : null}
                {bindingSignature ? (
                  <> · Signature: <span className="font-mono">{bindingSignature}</span></>
                ) : null}
                {' '}· Binding AST: <span className="font-mono">{bindingAstId}</span>
              </p>
            </div>
          </Alert>
        )}

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
                    Extracting full production ASTâ€¦
                  </>
                ) : (
                  <>
                    <UploadIcon className="h-4 w-4 mr-2" />
                    Extract template
                  </>
                )}
              </Button>
            </form>
          </Card>

          {/* Generate */}
          <Card title="3. Generate report">
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
                    Queuingâ€¦
                  </>
                ) : (
                  'Generate report'
                )}
              </Button>
            </form>
          </Card>
        </div>

        {/* Phase 1: bind dataset to template (value-free datasetAST · bindingAST) */}
        <Link href="/report-builder/binding" className="group block">
          <Card className="transition-colors group-hover:border-accent/60">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Link2 className="h-5 w-5" aria-hidden />
                </span>
                <div>
                  <h2 className="text-lg font-semibold text-text">
                    2. Bind dataset to template
                  </h2>
                  <p className="mt-1 max-w-xl text-sm text-text-muted">
                    Map your dataset&apos;s columns to the template&apos;s entities — confirm every match —
                    then clear the coverage gate before generating. Optional, but recommended for new datasets.
                  </p>
                </div>
              </div>
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                Open binding
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
              </span>
            </div>
          </Card>
        </Link>

        {(extractedTemplateAst || loadingTemplateAst) && (
          <div ref={previewRef}>
            <Card
              title="Extracted PDF layout and blueprint"
              description={
                previewTemplateName
                  ? `${previewTemplateName}${viewingTemplateId ? ` (template #${viewingTemplateId})` : ''} — structure, text snippets, table signals and question blueprint from stored AST.`
                  : 'Actual structure, text snippets, table signals and generated question blueprint from uploaded PDF.'
              }
            >
              {loadingTemplateAst && !extractedTemplateAst ? (
                <div className="flex items-center gap-2 py-8 text-sm text-text-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading template AST…
                </div>
              ) : extractedTemplateAst ? (
                <TemplateExtractionPreview ast={extractedTemplateAst} />
              ) : null}
            </Card>
          </div>
        )}

        {/* Templates list */}
        <Card title="Uploaded templates" description="Source PDFs reverse-engineered into block ASTs.">
          {loading ? (
            <p className="text-sm text-text-muted">Loadingâ€¦</p>
          ) : templates.length === 0 ? (
            <p className="text-sm text-text-muted">
              No templates yet â€” the built-in MoSPI default will be used.
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
                    <th className="py-2 pr-4 font-medium text-text-muted">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {templates.map((t) => (
                    <tr
                      key={t.id}
                      className={`border-b border-border/40 ${
                        viewingTemplateId === t.id ? 'bg-accent/5' : ''
                      }`}
                    >
                      <td className="py-2 pr-4">{t.id}</td>
                      <td className="py-2 pr-4 font-medium">
                        <button
                          type="button"
                          onClick={() => loadExtractedTemplate(t.id, true)}
                          className="text-left hover:text-accent hover:underline disabled:opacity-50"
                          disabled={loadingTemplateAst && viewingTemplateId === t.id}
                        >
                          {t.name}
                        </button>
                      </td>
                      <td className="py-2 pr-4">{t.page_count ?? '—'}</td>
                      <td className="py-2 pr-4">{t.block_count}</td>
                      <td className="py-2 pr-4 text-xs">
                        {t.extraction_method ?? '—'}
                      </td>
                      <td className="py-2 pr-4 font-mono text-[10px] text-text-muted">
                        {t.source_hash ? t.source_hash.slice(0, 12) + '…' : '—'}
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => loadExtractedTemplate(t.id, true)}
                            className="text-text-muted hover:text-accent disabled:opacity-50"
                            title="View blueprint"
                            disabled={loadingTemplateAst && viewingTemplateId === t.id}
                          >
                            {loadingTemplateAst && viewingTemplateId === t.id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Eye className="h-4 w-4" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => onDeleteTemplate(t.id)}
                            className="text-red-600 hover:text-red-700"
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
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
                        {j.stage ?? 'â€”'}
                      </td>
                      <td className="py-2 pr-4 font-mono text-[10px] text-text-muted">
                        {j.content_hash ? j.content_hash.slice(0, 12) + 'â€¦' : 'â€”'}
                      </td>
                      <td className="py-2 pr-4">
                        <Link
                          href={`/report-builder/${j.id}`}
                          className="text-primary hover:underline text-xs"
                        >
                          Open canvas â†’
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

  // V2/V3 enterprise AST data â€” pipeline v3 stores all keys at top level
  const enterpriseAst = (ast.enterprise_ast as Record<string, unknown>) || {};
  const assets = (ast.extracted_assets as Record<string, unknown> | undefined) || {};
  const pipelineTrace = (ast.pipeline_trace as Record<string, unknown>) || (enterpriseAst.pipeline_trace as Record<string, unknown>) || {};
  const passes = (pipelineTrace.passes as Record<string, Record<string, unknown>>) || {};

  // Content from enterprise AST or top-level (v3 is top-level)
  const semanticAST = (ast.semanticAST as Record<string, unknown>) || (enterpriseAst.semanticAST as Record<string, unknown>) || {};
  // Gold-standard uses .sections, legacy uses .hierarchy
  const sections = Array.isArray(semanticAST.sections) ? (semanticAST.sections as Array<Record<string, unknown>>) : [];
  const hierarchy = sections.length > 0 ? sections : (Array.isArray(semanticAST.hierarchy) ? (semanticAST.hierarchy as Array<Record<string, unknown>>) : []);
  const entityGraph = (ast.entityGraph as Record<string, unknown>) || (enterpriseAst.entityGraph as Record<string, unknown>) || {};
  const entities = Array.isArray(entityGraph.entities) ? (entityGraph.entities as Array<Record<string, unknown>>) : [];
  const tableAST = (ast.tableAST as Record<string, unknown>) || (enterpriseAst.tableAST as Record<string, unknown>) || {};
  const tables = Array.isArray(tableAST.tables) ? (tableAST.tables as Array<Record<string, unknown>>) : [];
  const factGraph = (ast.factGraph as Record<string, unknown>) || (enterpriseAst.factGraph as Record<string, unknown>) || {};
  const facts = Array.isArray(factGraph.facts) ? (factGraph.facts as Array<Record<string, unknown>>) : [];
  // v3 questions are intent strings; full objects live in blueprint.topics[].questions
  const questionStrings = Array.isArray(ast.questions) ? (ast.questions as string[]) : [];
  const blocks = Array.isArray(ast.blocks) ? (ast.blocks as Array<Record<string, unknown>>) : [];

  // V3 figureAST (proper figures with chartRef, captionTemplate)
  const figureAST = (ast.figureAST as Record<string, unknown>) || {};
  const allFigures = Array.isArray(figureAST.figures) ? (figureAST.figures as Array<Record<string, unknown>>) : [];
  // V3 chartAST (charts with xAxis, yAxis, paletteRef)
  const chartAST = (ast.chartAST as Record<string, unknown>) || {};
  const charts = Array.isArray(chartAST.charts) ? (chartAST.charts as Array<Record<string, unknown>>) : [];
  const chartFigures = charts.length > 0 ? charts : allFigures.filter(f => f.type === 'chart' || Boolean(f.chartType));
  const pureFigures = allFigures.filter(f => !f.chartRef);

  // V3 blueprint â€” directly at ast.blueprint
  const blueprint = (ast.blueprint as Record<string, unknown>) || (enterpriseAst.blueprint as Record<string, unknown>) || {};
  const bpTopics = Array.isArray(blueprint.topics) ? (blueprint.topics as Array<Record<string, unknown>>) : [];
  const bpEntities = Array.isArray(blueprint.entities) ? (blueprint.entities as Array<Record<string, unknown>>) : [];
  const bpTableTemplates = Array.isArray(blueprint.tableTemplates) ? (blueprint.tableTemplates as Array<Record<string, unknown>>) : [];
  const bpFigureTemplates = Array.isArray(blueprint.figureTemplates) ? (blueprint.figureTemplates as Array<Record<string, unknown>>) : [];
  const bpGlossary = (blueprint.glossary as Record<string, string>) || {};
  const bpPalette = (blueprint.palette as Record<string, unknown>) || {};
  const bpRenderProfile = (blueprint.renderProfile as Record<string, unknown>) || {};
  const entityNameById = buildEntityNameMap(bpEntities, entities);

  // Style AST
  const styleAST = (ast.styleAST as Record<string, unknown>) || {};
  const styles = Array.isArray(styleAST.styles) ? (styleAST.styles as Array<Record<string, unknown>>) : [];

  // Content blocks (gold-standard: blocks with biQuery, slot)
  const contentAST = (ast.contentAST as Record<string, unknown>) || {};
  const contentBlocks = Array.isArray(contentAST.blocks) ? (contentAST.blocks as Array<Record<string, unknown>>) : [];

  const textPages = Array.isArray(assets.text_pages) ? (assets.text_pages as Array<Record<string, unknown>>) : [];

  // Check if we have real content (V2 or V1)
  const hasContent = textPages.length > 0 || entities.length > 0 || blocks.length > 0 || hierarchy.length > 0 || charts.length > 0 || bpTopics.length > 0 || tables.length > 0;

  const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'blocks', label: `Blocks (${blocks.length})` },
    { id: 'entities', label: `Entities (${entities.length})` },
    { id: 'tables', label: `Tables (${tables.length})` },
    { id: 'charts', label: `Charts (${allFigures.length})` },
    { id: 'blueprint', label: `Blueprint (${bpTopics.length})` },
    { id: 'questions', label: `Questions (${questionStrings.length})` },
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
    dimension: 'bg-blue-100 text-blue-700',
    measure: 'bg-emerald-100 text-emerald-700',
    filter: 'bg-orange-100 text-orange-700',
    time: 'bg-amber-100 text-amber-700',
    metadata: 'bg-gray-100 text-gray-600',
    org: 'bg-indigo-100 text-indigo-700',
    metric: 'bg-emerald-100 text-emerald-700',
    demographic: 'bg-cyan-100 text-cyan-700',
    location: 'bg-rose-100 text-rose-700',
    resource: 'bg-teal-100 text-teal-700',
  };

  const blockTypeOptions = useMemo(
    () => collectTypeOptions(blocks, (b) => String(b.kind || b.type || 'unknown')),
    [blocks]
  );
  const entityTypeOptions = useMemo(
    () => collectTypeOptions(entities, (e) => String(e.type || e.entityType || 'unknown')),
    [entities]
  );
  const [selectedBlockTypes, setSelectedBlockTypes] = useTypeFilter(blockTypeOptions.types);
  const [selectedEntityTypes, setSelectedEntityTypes] = useTypeFilter(entityTypeOptions.types);

  const filteredBlocks = useMemo(
    () =>
      blocks.filter((b) =>
        selectedBlockTypes.has(String(b.kind || b.type || 'unknown'))
      ),
    [blocks, selectedBlockTypes]
  );
  const filteredEntities = useMemo(
    () =>
      entities.filter((e) =>
        selectedEntityTypes.has(String(e.type || e.entityType || 'unknown'))
      ),
    [entities, selectedEntityTypes]
  );

  return (
    <div className="space-y-4">
      {/* Summary badges */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-6">
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Doc ID</p>
          <p className="text-sm font-mono truncate">{String(ast.doc_id || enterpriseAst.metadata && (enterpriseAst.metadata as Record<string,unknown>).documentId || 'â€”')}</p>
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
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Charts</p>
          <p className="text-sm font-bold">{allFigures.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Topics</p>
          <p className="text-sm font-bold">{bpTopics.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2">
          <p className="text-[10px] text-text-muted uppercase tracking-wider">Time</p>
          <p className="text-sm font-bold">{pipelineTrace.total_elapsed ? `${pipelineTrace.total_elapsed}s` : 'â€”'}</p>
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
            {Boolean(pipelineTrace.total_elapsed) && (
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
                      <span className="text-xs text-text">{String(node.title || node.name || 'â€”')}</span>
                      {Boolean(node.pageSpan) && (
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
                    <span>{String(f.statement || f.text || 'â€”')}</span>
                    {Boolean(f.confidence) && <Badge variant="muted" className="text-[9px]">{Math.round(Number(f.confidence) * 100)}%</Badge>}
                  </li>
                ))}
              </ul>
            </div>
          )}

        </div>
      )}

      {activeTab === 'blocks' && (
        <div className="space-y-3">
          {blocks.length === 0 ? (
            <p className="text-sm text-text-muted">No blocks extracted.</p>
          ) : (
            <>
              <TypeFilterDropdown
                label="Filter block types"
                types={blockTypeOptions.types}
                selected={selectedBlockTypes}
                onChange={setSelectedBlockTypes}
                counts={blockTypeOptions.counts}
                typeColors={kindColors}
              />
              {filteredBlocks.length === 0 ? (
                <p className="text-sm text-text-muted">No blocks match the selected types.</p>
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
                      {filteredBlocks.map((b, idx) => (
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
            </>
          )}
        </div>
      )}

      {activeTab === 'entities' && (
        <div className="space-y-3">
          {entities.length === 0 ? (
            <p className="text-sm text-text-muted">No entities extracted.</p>
          ) : (
            <>
              <TypeFilterDropdown
                label="Filter entity types"
                types={entityTypeOptions.types}
                selected={selectedEntityTypes}
                onChange={setSelectedEntityTypes}
                counts={entityTypeOptions.counts}
                typeColors={entityTypeColors}
              />
              {filteredEntities.length === 0 ? (
                <p className="text-sm text-text-muted">No entities match the selected types.</p>
              ) : (
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
                      {filteredEntities.map((e, idx) => (
                        <tr key={`${e.entityId || idx}`} className="border-b border-border/30 hover:bg-surface/50">
                          <td className="py-2 px-3 font-mono text-text-muted text-[10px]">{String(e.entityId || '—')}</td>
                          <td className="py-2 px-3">
                            <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${entityTypeColors[String(e.type || e.entityType)] || 'bg-gray-100 text-gray-700'}`}>
                              {String(e.type || e.entityType || '—')}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-text font-medium">{String(e.name || '—')}</td>
                          <td className="py-2 px-3 text-text-muted max-w-[200px] truncate">{String(e.context || '—')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
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
                    {Boolean(t.source) && <Badge variant="muted">{String(t.source)}</Badge>}
                  </div>
                  {Array.isArray(t.columns) && (t.columns as unknown[]).length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-2">
                      {(t.columns as unknown[]).slice(0, 10).map((col, ci) => (
                        <span key={ci} className="text-[10px] bg-green-50 text-green-700 rounded px-1.5 py-0.5">
                          {typeof col === 'string' ? col : typeof col === 'object' && col !== null ? String((col as Record<string, unknown>).header || (col as Record<string, unknown>).columnId || JSON.stringify(col)) : String(col)}
                        </span>
                      ))}
                    </div>
                  )}
                  {Array.isArray(t.sampleRows) && (t.sampleRows as unknown[]).length > 0 && (
                    <pre className="text-[10px] text-text-muted bg-gray-50 rounded p-2 overflow-auto max-h-24">
                      {JSON.stringify(t.sampleRows, null, 2)}
                    </pre>
                  )}
                  <p className="text-[10px] text-text-muted mt-1">Rows: {String(t.rowCount || 'â€”')}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'charts' && (
        <div className="space-y-3">
          {allFigures.length === 0 ? (
            <p className="text-sm text-text-muted italic">No charts or figures detected. Check that the PDF contains embedded images or that VLM detected chart regions.</p>
          ) : (
            <>
              {/* Summary stats row */}
              <div className="flex flex-wrap gap-2 pb-1">
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium bg-amber-100 text-amber-700">
                  Total: {allFigures.length}
                </span>
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium bg-blue-100 text-blue-700">
                  Charts: {chartFigures.length}
                </span>
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium bg-gray-100 text-gray-600">
                  Other figures: {pureFigures.length}
                </span>
              </div>

              {/* Chart type distribution */}
              <div className="rounded-lg border border-border bg-surface p-3">
                <h4 className="text-xs font-semibold text-text mb-2">Chart Type Distribution</h4>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(
                    allFigures.reduce<Record<string, number>>((acc, f) => {
                      const t = String((f as Record<string, unknown>).chartType || (f as Record<string, unknown>).type || 'unknown');
                      acc[t] = (acc[t] || 0) + 1;
                      return acc;
                    }, {})
                  ).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
                    <span key={type} className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium ${
                      type.includes('bar') ? 'bg-orange-100 text-orange-700' :
                      type.includes('line') ? 'bg-blue-100 text-blue-700' :
                      type.includes('pie') ? 'bg-pink-100 text-pink-700' :
                      type.includes('scatter') ? 'bg-purple-100 text-purple-700' :
                      type.includes('area') ? 'bg-teal-100 text-teal-700' :
                      type.includes('map') ? 'bg-green-100 text-green-700' :
                      'bg-amber-100 text-amber-700'
                    }`}>
                      {type.replace(/_/g, ' ')}&nbsp;Ã—{count}
                    </span>
                  ))}
                </div>
              </div>

              {/* Per-figure cards */}
              <div className="space-y-2">
                {allFigures.slice(0, 20).map((f, idx) => {
                  const fig = f as Record<string, unknown>;
                  const chartType = String(fig.chartType || fig.type || 'figure');
                  const title = String(fig.title || fig.caption || `Figure on p.${Number(fig.page || 0) + 1}`);
                  const pageNum = Number(fig.page || 0) + 1;
                  const source = String(fig.detectionSource || fig.source || 'unknown');
                  const desc = String(fig.description || fig.vlmDescription || '');
                  return (
                    <div key={`fig-${String(fig.figureId || idx)}`} className="rounded-lg border border-border bg-surface p-3">
                      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                        <span className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-bold ${
                          chartType.includes('bar') ? 'bg-orange-100 text-orange-700' :
                          chartType.includes('line') ? 'bg-blue-100 text-blue-700' :
                          chartType.includes('pie') ? 'bg-pink-100 text-pink-700' :
                          chartType.includes('scatter') ? 'bg-purple-100 text-purple-700' :
                          chartType.includes('area') ? 'bg-teal-100 text-teal-700' :
                          chartType.includes('map') ? 'bg-green-100 text-green-700' :
                          'bg-amber-100 text-amber-700'
                        }`}>
                          {chartType.replace(/_/g, ' ')}
                        </span>
                        <span className="text-xs font-medium text-text flex-1 min-w-0 truncate">{title}</span>
                        <span className="shrink-0 text-[10px] text-text-muted">p.{pageNum}</span>
                      </div>
                      {desc && <p className="text-[10px] text-text-muted mb-1.5 line-clamp-2">{desc}</p>}
                      <div className="flex flex-wrap gap-1">
                        <span className={`text-[9px] rounded px-1.5 py-0.5 font-medium ${
                          source === 'vlm' ? 'bg-indigo-50 text-indigo-600' :
                          source === 'embedded' ? 'bg-green-50 text-green-600' :
                          source === 'layoutlm' ? 'bg-blue-50 text-blue-600' :
                          'bg-gray-100 text-gray-500'
                        }`}>
                          src: {source}
                        </span>
                        {Boolean(fig.figureId) && (
                          <span className="text-[9px] bg-gray-50 text-gray-400 rounded px-1.5 py-0.5 font-mono">{String(fig.figureId)}</span>
                        )}
                        {Boolean(fig.areaFraction) && (
                          <span className="text-[9px] bg-gray-50 text-gray-500 rounded px-1.5 py-0.5">
                            area: {Math.round(Number(fig.areaFraction) * 100)}%
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
                {allFigures.length > 20 && (
                  <p className="text-xs text-text-muted text-center py-1">â€¦and {allFigures.length - 20} more</p>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {activeTab === 'blueprint' && (
        <div className="space-y-4">
          {bpTopics.length === 0 ? (
            <p className="text-sm text-text-muted italic">Blueprint not generated. Re-run extraction to populate blueprint topics.</p>
          ) : (
            <>
              <p className="text-xs text-text-muted">
                {bpTopics.length} topics Â· {bpEntities.length} entities Â· {bpTableTemplates.length} table structures
              </p>

              {/* Topics tree */}
              <div className="space-y-2">
                {bpTopics.map((topicRaw, ti) => {
                  const topic = topicRaw as Record<string, unknown>;
                  const qs = Array.isArray(topic.questions) ? topic.questions as Array<Record<string, unknown>> : [];
                  return (
                    <details key={ti} className="rounded-lg border border-border bg-surface">
                      <summary className="cursor-pointer px-3 py-2.5 text-xs font-medium flex items-center gap-2 list-none">
                        <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary/10 text-primary text-[10px] font-bold shrink-0">{ti + 1}</span>
                        <span className="flex-1 min-w-0 truncate">{String(topic.title || topic.topicId || `Topic ${ti + 1}`)}</span>
                        <span className="shrink-0 text-[10px] text-text-muted ml-auto">{qs.length}q</span>
                        <svg className="shrink-0 w-3 h-3 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
                      </summary>
                      <div className="px-3 pb-3 pt-1 space-y-1.5 border-t border-border/40">
                        {qs.length === 0 && <p className="text-[10px] text-text-muted">No questions</p>}
                        {qs.slice(0, 8).map((q, qi) => (
                          <div key={qi} className="rounded border border-border/50 bg-white/60 p-2">
                            <div className="flex items-start gap-2 flex-wrap">
                              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium ${
                                q.questionType === 'comparison' ? 'bg-blue-100 text-blue-700' :
                                q.questionType === 'trend' ? 'bg-green-100 text-green-700' :
                                q.questionType === 'ranking' ? 'bg-purple-100 text-purple-700' :
                                'bg-gray-100 text-gray-600'
                              }`}>{String(q.questionType || 'describe')}</span>
                              <span className="text-xs text-text flex-1">{String(q.intent || q.questionId || 'â€”')}</span>
                            </div>
                            {Array.isArray(q.requiredEntities) && (q.requiredEntities as Array<Record<string, unknown>>).length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1.5">
                                {(q.requiredEntities as Array<Record<string, unknown>>).slice(0, 5).map((re, ri) => (
                                  <span key={ri} className="text-[9px] bg-indigo-50 text-indigo-700 rounded px-1.5 py-0.5">
                                    {resolveEntityLabel(re.entityRef || re.entityId, entityNameById)}
                                    <span className="opacity-60 ml-0.5">({String(re.role || '?')})</span>
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                        {qs.length > 8 && <p className="text-[10px] text-text-muted">â€¦{qs.length - 8} more questions</p>}
                      </div>
                    </details>
                  );
                })}
              </div>

              {/* Blueprint table structures */}
              {bpTableTemplates.length > 0 && (
                <div className="rounded-lg border border-border bg-surface p-3">
                  <h4 className="text-xs font-semibold text-text mb-2">Table Structures ({bpTableTemplates.length})</h4>
                  <div className="space-y-1.5">
                    {(bpTableTemplates as Array<Record<string, unknown>>).slice(0, 8).map((t, ti) => (
                      <div key={ti} className="flex items-center gap-2 text-[10px]">
                        <span className="font-medium text-text">{String(t.title || t.tableId || `Table ${ti + 1}`)}</span>
                        {Array.isArray(t.columns) && (
                          <span className="text-text-muted">{(t.columns as unknown[]).length} cols</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {activeTab === 'questions' && (
        <div className="space-y-3">
          {questionStrings.length === 0 ? (
            <p className="text-sm text-text-muted">No questions generated.</p>
          ) : (
            <div className="space-y-2">
              {questionStrings.slice(0, 20).map((q, idx) => (
                <div key={`q-${idx}`} className="flex gap-3 items-start rounded-lg border border-border bg-surface px-3 py-2">
                  <span className="text-xs text-text-muted font-mono shrink-0 w-5">{idx + 1}</span>
                  <p className="text-xs text-text">{String(q)}</p>
                </div>
              ))}
              {questionStrings.length > 20 && (
                <p className="text-xs text-text-muted text-center py-1">â€¦and {questionStrings.length - 20} more</p>
              )}
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
                  {(passes.pass2_entities || passes.pass2_vlm) && (
                    <div>
                      <p className="text-[10px] text-text-muted">VLM Success Rate</p>
                      <p className="text-sm font-bold">{String(
                        ((passes.pass2_entities || passes.pass2_vlm) as Record<string,unknown>).vlm_success_rate || 0
                      )}%</p>
                    </div>
                  )}
                  {(passes.pass3_questions || passes.pass3_semantic) && (
                    <div>
                      <p className="text-[10px] text-text-muted">Questions Extracted</p>
                      <p className="text-sm font-bold">{String(
                        ((passes.pass3_questions || passes.pass3_semantic) as Record<string,unknown>).questions ||
                        ((passes.pass3_questions || passes.pass3_semantic) as Record<string,unknown>).source || 'â€”'
                      )}</p>
                    </div>
                  )}
                  {(passes.pass2_5_kg || passes.pass2_5_merge) && (
                    <div>
                      <p className="text-[10px] text-text-muted">KG Entities</p>
                      <p className="text-sm font-bold">{String(
                        ((passes.pass2_5_kg || passes.pass2_5_merge) as Record<string,unknown>).total_entities ||
                        ((passes.pass2_5_kg || passes.pass2_5_merge) as Record<string,unknown>).hierarchy_nodes || 0
                      )}</p>
                    </div>
                  )}
                  {passes.pass4_assembly && (
                    <div>
                      <p className="text-[10px] text-text-muted">Tables Found</p>
                      <p className="text-sm font-bold">{String((passes.pass4_assembly as Record<string,unknown>).tables || 0)}</p>
                    </div>
                  )}
                  {passes.pass4_assembly && (
                    <div>
                      <p className="text-[10px] text-text-muted">Charts</p>
                      <p className="text-sm font-bold">
                        {String(
                          (passes.pass4_assembly as Record<string, unknown>).charts_detected ??
                            (passes.pass4_assembly as Record<string, unknown>).figures ??
                            0
                        )}
                      </p>
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

