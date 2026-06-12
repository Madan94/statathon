'use client';

import { Suspense, useEffect, useState } from 'react';
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
  reportBuilderApi,
  ReportTemplate,
  ReportJob,
  TemplateExtractionJob,
} from '@/lib/api';
import { buildTemplateAstHref } from '@/lib/templateRouteUtils';

export type ReportPlatformMode = 'ast-generator' | 'report-builder';

export function ReportPlatformPage({
  mode,
  basePath,
}: {
  mode: ReportPlatformMode;
  basePath: string;
}) {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-text-muted">Loading…</div>}>
      <ReportBuilderContent mode={mode} basePath={basePath} />
    </Suspense>
  );
}

function ReportBuilderContent({
  mode,
  basePath,
}: {
  mode: ReportPlatformMode;
  basePath: string;
}) {
  const isAstGenerator = mode === 'ast-generator';
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
  const [lastCreatedTemplate, setLastCreatedTemplate] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
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

  const openTemplateAst = (template: Pick<ReportTemplate, 'id' | 'name'>) => {
    router.push(buildTemplateAstHref(template));
  };

  useEffect(() => {
    if (!isAstGenerator || loading) return;
    const tid = searchParams.get('templateId');
    if (!tid || Number.isNaN(Number(tid))) return;
    const id = Number(tid);
    const tpl = templates.find((t) => t.id === id);
    if (tpl) {
      router.replace(buildTemplateAstHref(tpl));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- legacy ?templateId= deep links
  }, [searchParams, loading, templates, isAstGenerator]);

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
        setLastCreatedTemplate({
          id: final.created_template_id,
          name: uploadName.trim() || pendingTemplateName,
        });
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

  const viewCreatedBlueprint = () => {
    closeExtractionModal();
    const fromJob =
      extractJob?.created_template_id != null
        ? {
            id: extractJob.created_template_id,
            name:
              lastCreatedTemplate?.name ||
              pendingTemplateName ||
              templates.find((t) => t.id === extractJob.created_template_id)?.name ||
              'template',
          }
        : null;
    const target = lastCreatedTemplate ?? fromJob;
    if (target) {
      openTemplateAst(target);
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
        title={isAstGenerator ? 'Report AST Generator' : 'Report Builder'}
        description={
          isAstGenerator
            ? 'Upload MoSPI PDFs and inspect reverse-engineered template ASTs and blueprints.'
            : 'Bind datasets to templates and generate block-based reports from completed analyses.'
        }
        actions={
          !isAstGenerator ? (
            <Link href="/report-builder/binding">
              <Button variant="outline" size="sm">
                <Link2 className="h-4 w-4" /> Bind dataset
              </Button>
            </Link>
          ) : undefined
        }
      />

      {isAstGenerator && (
      <TemplateExtractionModal
        open={extractionModalOpen}
        templateName={pendingTemplateName || uploadName || 'Template'}
        job={extractJob}
        phase={extractionModalPhase}
        errorMessage={extractionError}
        onClose={closeExtractionModal}
        onViewBlueprint={viewCreatedBlueprint}
        onRetry={closeExtractionModal}
      />
      )}

      <div className="space-y-6">
        {error && !extractionModalOpen && <Alert variant="error">{error}</Alert>}

        {!isAstGenerator && bindingAstId && (
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

        {isAstGenerator && (
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
            </form>
          </Card>
        )}

        {!isAstGenerator && (
          <>
            <Link href="/report-builder/binding" className="group block">
              <Card className="transition-colors group-hover:border-accent/60">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Link2 className="h-5 w-5" aria-hidden />
                    </span>
                    <div>
                      <h2 className="text-lg font-semibold text-text">
                        1. Bind dataset to template
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
          </>
        )}

        {isAstGenerator && (
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
                    <tr key={t.id} className="border-b border-border/40">
                      <td className="py-2 pr-4">{t.id}</td>
                      <td className="py-2 pr-4 font-medium">
                        <button
                          type="button"
                          onClick={() => openTemplateAst(t)}
                          className="text-left hover:text-accent hover:underline"
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
                            onClick={() => openTemplateAst(t)}
                            className="text-text-muted hover:text-accent"
                            title="View blueprint"
                          >
                            <Eye className="h-4 w-4" />
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
        )}

        {!isAstGenerator && (
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
        )}
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

