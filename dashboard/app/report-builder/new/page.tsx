'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Loader2, ChevronLeft, ChevronRight, Play } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import WizardStepper from '@/components/report-builder/WizardStepper';
import BlockMappingTable, { BlockRow } from '@/components/report-builder/BlockMappingTable';
import FilterConfigForm from '@/components/report-builder/FilterConfigForm';
import {
  authApi,
  AuthUser,
  DataFilterSpec,
  ReadyAnalysis,
  reportBuilderApi,
  ReportTemplate,
} from '@/lib/api';

function blocksFromAst(ast: Record<string, unknown>): BlockRow[] {
  const raw = (ast.blocks as unknown[]) || [];
  return raw.map((b) => {
    const row = b as Record<string, unknown>;
    const hints = (row.hints as Record<string, string>) || {};
    return {
      block_id: String(row.block_id || ''),
      kind: String(row.kind || 'narrative'),
      title: String(row.title || ''),
      section: String(row.section || 'general'),
      required: Boolean(row.required ?? true),
      hints: { source: hints.source, engine: hints.engine },
    };
  });
}

export default function ReportBuilderWizardPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [user, setUser] = useState<AuthUser | null>(null);
  const [analyses, setAnalyses] = useState<ReadyAnalysis[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [analysisId, setAnalysisId] = useState<number | null>(null);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [blocks, setBlocks] = useState<BlockRow[]>([]);
  const [filterConfig, setFilterConfig] = useState<DataFilterSpec>({});
  const [uploadName, setUploadName] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [jsonFile, setJsonFile] = useState<File | null>(null);

  useEffect(() => {
    Promise.all([
      authApi.me(),
      reportBuilderApi.listReadyAnalyses(),
      reportBuilderApi.listTemplates(),
    ])
      .then(([me, ready, tpls]) => {
        setUser(me);
        setAnalyses(ready);
        setTemplates(tpls);
      })
      .catch(() => setError('Failed to load wizard data'));
  }, []);

  const selectedAnalysis = analyses.find((a) => a.analysis_id === analysisId);

  const loadTemplateAst = async (id: number) => {
    const t = await reportBuilderApi.getTemplate(id);
    if (t.ast) setBlocks(blocksFromAst(t.ast as Record<string, unknown>));
    if (t.filter_config) setFilterConfig(t.filter_config as DataFilterSpec);
  };

  const saveBlocksToTemplate = async () => {
    if (!templateId) return;
    const t = await reportBuilderApi.getTemplate(templateId);
    const ast = { ...(t.ast as Record<string, unknown>), blocks };
    await reportBuilderApi.updateTemplate(templateId, {
      ast,
      filter_config: filterConfig,
    });
  };

  const onCloneDefault = async () => {
    setLoading(true);
    setError(null);
    try {
      const t = await reportBuilderApi.cloneDefaultTemplate();
      setTemplateId(t.id);
      setBlocks(blocksFromAst(t.ast));
      await reportBuilderApi.listTemplates().then(setTemplates);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Clone failed');
    } finally {
      setLoading(false);
    }
  };

  const onUploadTemplate = async () => {
    if (!uploadFile || !uploadName.trim()) return;
    setLoading(true);
    try {
      const t = await reportBuilderApi.uploadTemplate(uploadName.trim(), uploadFile);
      setTemplateId(t.id);
      setBlocks(blocksFromAst(t.ast));
      await reportBuilderApi.listTemplates().then(setTemplates);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  const onImportJsonTemplate = async () => {
    if (!jsonFile || !uploadName.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const text = await jsonFile.text();
      const ast = JSON.parse(text) as Record<string, unknown>;
      const t = await reportBuilderApi.importJsonTemplate(
        uploadName.trim(),
        ast,
        'Imported from JSON AST',
        ast.document ? 'energy_chapter' : undefined
      );
      setTemplateId(t.id);
      setBlocks(blocksFromAst(t.ast));
      await reportBuilderApi.listTemplates().then(setTemplates);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'JSON import failed');
    } finally {
      setLoading(false);
    }
  };

  const onGenerate = async () => {
    if (!analysisId) {
      setError('Select a completed analysis');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (templateId) await saveBlocksToTemplate();
      const job = await reportBuilderApi.generate(analysisId, templateId, filterConfig);
      router.push(`/report-builder/${job.id}`);
    } catch (e) {
      const ax = e as { response?: { data?: { detail?: string } } };
      setError(ax.response?.data?.detail || (e instanceof Error ? e.message : 'Generate failed'));
    } finally {
      setLoading(false);
    }
  };

  const next = async () => {
    if (step === 3 && templateId) {
      try {
        await saveBlocksToTemplate();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to save blocks');
        return;
      }
    }
    if (step === 1 && !analysisId) {
      setError('Select a data source (completed analysis)');
      return;
    }
    setError(null);
    setStep((s) => Math.min(5, s + 1));
  };

  return (
    <div>
      <PageHeader
        title="New report"
        description="Template-based builder — configure data, blocks, and filters before generation."
        actions={
          <Link href="/report-builder" className="text-sm text-primary hover:underline">
            Back to jobs
          </Link>
        }
      />

      <WizardStepper current={step} />

      {error && <Alert variant="error" className="mb-4">{error}</Alert>}

      {step === 0 && (
        <Card title="Officer context">
          {user ? (
            <dl className="grid sm:grid-cols-3 gap-4 text-sm">
              <div>
                <dt className="text-xs text-text-muted uppercase">Name</dt>
                <dd className="font-medium">{user.full_name || '—'}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted uppercase">Email</dt>
                <dd className="font-medium">{user.email}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted uppercase">Role</dt>
                <dd className="font-medium">{user.officer_role || '—'}</dd>
              </div>
            </dl>
          ) : (
            <Loader2 className="h-6 w-6 animate-spin" />
          )}
        </Card>
      )}

      {step === 1 && (
        <Card title="Data source" description="Pick a dataset with completed semantic analysis.">
          {analyses.length === 0 ? (
            <p className="text-sm text-text-muted">
              No completed analyses.{' '}
              <Link href="/upload" className="text-primary underline">
                Upload a dataset
              </Link>{' '}
              and run analysis first.
            </p>
          ) : (
            <select
              className="w-full rounded-lg border border-border px-3 py-2 bg-surface"
              value={analysisId ?? ''}
              onChange={(e) => setAnalysisId(Number(e.target.value) || null)}
            >
              <option value="">— Select analysis —</option>
              {analyses.map((a) => (
                <option key={a.analysis_id} value={a.analysis_id}>
                  #{a.analysis_id} — {a.filename} ({a.row_count}×{a.column_count})
                </option>
              ))}
            </select>
          )}
          {selectedAnalysis && (
            <p className="mt-3 text-xs text-text-muted">
              Upload status: {selectedAnalysis.upload_status || 'UPLOADED'}
            </p>
          )}
        </Card>
      )}

      {step === 2 && (
        <Card title="Template" className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={onCloneDefault} disabled={loading}>
              Use MoSPI default
            </Button>
          </div>
          <div className="flex flex-wrap gap-2 items-end">
            <input
              type="text"
              placeholder="Template name"
              className="rounded-lg border border-border px-3 py-2 text-sm flex-1 min-w-[160px]"
              value={uploadName}
              onChange={(e) => setUploadName(e.target.value)}
            />
            <input
              type="file"
              accept="application/pdf"
              className="text-sm"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
            />
            <Button type="button" size="sm" onClick={onUploadTemplate} disabled={loading || !uploadFile}>
              Upload PDF
            </Button>
          </div>
          <div className="flex flex-wrap gap-2 items-end border-t border-border pt-4">
            <input
              type="file"
              accept="application/json,.json,.txt"
              className="text-sm flex-1 min-w-[200px]"
              onChange={(e) => setJsonFile(e.target.files?.[0] || null)}
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={onImportJsonTemplate}
              disabled={loading || !jsonFile || !uploadName.trim()}
            >
              Import JSON AST
            </Button>
            <span className="text-xs text-text-muted w-full">
              Use your <code className="text-text">ast.json.txt</code> (Energy Reserves chapter) here.
            </span>
          </div>
          <div>
            <label className="text-xs text-text-muted block mb-1">Or select existing</label>
            <select
              className="w-full rounded-lg border border-border px-3 py-2 bg-surface"
              value={templateId ?? ''}
              onChange={async (e) => {
                const id = Number(e.target.value) || null;
                setTemplateId(id);
                if (id) await loadTemplateAst(id);
              }}
            >
              <option value="">— Built-in at generate time —</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.block_count} blocks)
                </option>
              ))}
            </select>
          </div>
          {blocks.length > 0 && (
            <p className="text-xs text-[#64748b]">{blocks.length} blocks loaded</p>
          )}
        </Card>
      )}

      {step === 3 && (
        <Card title="Block mapping" description="Map each block to analysis data sources.">
          {blocks.length === 0 ? (
            <p className="text-sm text-text-muted">Select or upload a template in the previous step.</p>
          ) : (
            <BlockMappingTable blocks={blocks} onChange={setBlocks} />
          )}
        </Card>
      )}

      {step === 4 && (
        <Card title="Data filters" description="Ingestion filter engine — applied before Scribe/Verifier.">
          <FilterConfigForm value={filterConfig} onChange={setFilterConfig} />
        </Card>
      )}

      {step === 5 && (
        <Card title="Review & generate">
          <ul className="text-sm space-y-2 mb-6 text-text-muted">
            <li>Analysis ID: <strong className="text-text">{analysisId ?? '—'}</strong></li>
            <li>Template ID: <strong className="text-text">{templateId ?? 'builtin default'}</strong></li>
            <li>Blocks: <strong className="text-text">{blocks.length}</strong></li>
            <li>Pipeline: Template AST → KG → Filters → Scribe → Verifier → PDF</li>
          </ul>
          <Button onClick={onGenerate} disabled={loading || !analysisId} size="lg">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <Play className="h-4 w-4 mr-2" />
            )}
            Generate report
          </Button>
        </Card>
      )}

      <div className="flex justify-between mt-8">
        <Button
          type="button"
          variant="secondary"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
        >
          <ChevronLeft className="h-4 w-4 mr-1" /> Back
        </Button>
        {step < 5 && (
          <Button type="button" onClick={next}>
            Next <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        )}
      </div>
    </div>
  );
}
