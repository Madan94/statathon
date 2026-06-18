'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, ArrowRight, Check, Loader2, Play, ShieldCheck, Sparkles, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Alert } from '@/components/ui/Alert';
import { QueryIndicatorFilters } from '@/components/report-builder/binding/QueryIndicatorFilters';
import { QueryDataPreviewStep } from '@/components/report-builder/query-flow/QueryDataPreviewStep';
import { SectionBlockView } from '@/components/report-builder/binding/SectionBlockView';
import { buildReportSectionSpec, buildSectionDescription, defaultSectionConfig, type ReportSectionConfig, type SectionComponentType } from '@/lib/reportSection';
import { bindingPhaseApi, generatePhaseApi, type BindingWorkspace } from '@/lib/api';
import { stableHash, type GeneratedSectionBlock, type SectionExecutionResult } from '@/lib/report-section';
import { canvasHandoffStorageKey, type AcceptedPreviewMetadata, type ReportCanvasHandoffBundle } from '@/lib/report-section/canvasHandoff';

function statusVariant(status?: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (status === 'READY') return 'success';
  if (status === 'DEGRADED' || status === 'DRAFT') return 'warning';
  if (status === 'BLOCKED') return 'danger';
  return 'muted';
}

function executeErrorMessage(err: unknown): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { status?: number; data?: { detail?: unknown } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') {
      const payload = detail as { message?: unknown; issues?: Array<{ code?: string; message?: string }> };
      if (Array.isArray(payload.issues) && payload.issues.length) {
        return payload.issues.map((issue) => `${issue.code || 'ISSUE'}: ${issue.message || 'No detail'}`).join('; ');
      }
      if (payload.message) return String(payload.message);
    }
    if (response?.status === 404) return 'The backend route for section execution is not available in the running API process. Restart the FastAPI server with the latest code.';
    return `Backend returned HTTP ${response?.status || 'error'} while executing the slice.`;
  }
  return err instanceof Error ? err.message : 'Could not execute this slice from the backend dataset stash.';
}

type FlowStep = 'scope' | 'data_preview' | 'description' | 'components' | 'preview';

function isFlowStep(value: string | null): value is FlowStep {
  return value === 'scope' || value === 'data_preview' || value === 'description' || value === 'components' || value === 'preview';
}

export default function QueryFlowPage() {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const templateId = String(params.templateId || '');
  const signature = String(params.signature || '');
  const routeStep = searchParams.get('step');
  const templatePath = searchParams.get('templatePath') === 'loop' ? 'loop' : 'pre_existing';
  const workflowMode = searchParams.get('workflowMode') || 'guided_query';
  const [workspace, setWorkspace] = useState<BindingWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sectionConfig, setSectionConfig] = useState<ReportSectionConfig>(() => defaultSectionConfig());
  const [executing, setExecuting] = useState(false);
  const [previewGenerating, setPreviewGenerating] = useState(false);
  const [execution, setExecution] = useState<SectionExecutionResult | null>(null);
  const [blocks, setBlocks] = useState<GeneratedSectionBlock[]>([]);
  const [selectedComponents, setSelectedComponents] = useState<SectionComponentType[]>(['narrative', 'table', 'chart', 'key_finding']);
  const [destinationMode, setDestinationMode] = useState<'existing' | 'new'>('existing');
  const [placementMode, setPlacementMode] = useState<'append_chapter' | 'new_chapter' | 'new_section'>('append_chapter');
  const [flowStep, setFlowStep] = useState<FlowStep>(isFlowStep(routeStep) ? routeStep : 'scope');
  const [selectedTags, setSelectedTags] = useState<string[]>(['official', 'evidence']);
  const [acceptedPreview, setAcceptedPreview] = useState<AcceptedPreviewMetadata | null>(null);
  // Synthesizer (LLM layer) — grounds report prose in the accepted weight JSON
  // plus the officer's description/components.
  const [synthesizing, setSynthesizing] = useState(false);
  const [synthesis, setSynthesis] = useState<{ content: string; keyFindings: string[]; usedLlm: boolean; provider: string; notes: string[] } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return null;
      setLoading(true);
      setError(null);
      return bindingPhaseApi.getWorkspace(templateId, signature);
    })
      .then((data) => {
        if (cancelled || !data) return;
        setWorkspace(data);
        setSectionConfig((prev) => ({
          ...prev,
          chapterTitle: data.template_package?.name || prev.chapterTitle,
          sectionTitle: prev.sectionTitle === 'New Section' ? 'Generated Section' : prev.sectionTitle,
          components: [],
        }));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Could not load the binding workspace for this query flow.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [templateId, signature]);

  const columnStats = useMemo(() => {
    const columns = workspace?.dataset_ast?.columns || [];
    return {
      total: columns.length,
      measures: columns.filter((c) => c.role === 'measure').length,
      dimensions: columns.filter((c) => c.role === 'dimension').length,
      time: columns.filter((c) => c.role === 'time').length,
    };
  }, [workspace?.dataset_ast?.columns]);

  const planStatus = workspace?.reviewed_plan?.status || 'DRAFT';
  const templateLabel = templatePath === 'loop' ? 'Loop template with weighting' : 'Curated MoSPI template';
  const currentMeasure = sectionConfig.measures[0] ?? null;
  const currentDimension = sectionConfig.dimensions[0] ?? null;
  const currentTime = sectionConfig.timeCol ?? null;
  const canExecute = Boolean(workspace && currentMeasure?.col);
  const suggestedDescription = useMemo(() => buildSectionDescription(sectionConfig), [sectionConfig]);
  const activeStep: FlowStep = isFlowStep(routeStep) ? routeStep : flowStep;
  const previewAcceptanceKey = useMemo(() => stableHash({
    filters: sectionConfig.filters,
    dimensions: sectionConfig.dimensions,
    measures: sectionConfig.measures.map((measure) => ({
      col: measure.col,
      label: measure.label,
      agg: measure.agg,
      unit: measure.unit,
      weighted: measure.weighted,
    })),
    timeCol: sectionConfig.timeCol,
    weightCol: sectionConfig.weightCol,
    analysisType: sectionConfig.analysisType,
    sortBy: sectionConfig.sortBy,
    sortOrder: sectionConfig.sortOrder,
  }), [sectionConfig]);
  const previewAccepted = acceptedPreview?.acceptanceKey === previewAcceptanceKey;
  const previewRequest = useMemo(() => {
    if (!workspace) return null;
    return buildReportSectionSpec(
      { ...sectionConfig, components: ['table'] },
      { templateId: workspace.template_id, signature: workspace.signature, datasetId: workspace.dataset_id },
    );
  }, [sectionConfig, workspace]);

  const queryPath = (step: FlowStep) => {
    const next = new URLSearchParams(searchParams.toString());
    next.set('step', step);
    return `/report-builder/query-flow/${encodeURIComponent(templateId)}/${encodeURIComponent(signature)}?${next.toString()}`;
  };

  const goToStep = (step: FlowStep) => {
    setFlowStep(step);
    router.replace(queryPath(step), { scroll: true });
  };

  const descriptionSuggestions = useMemo(() => {
    const measure = currentMeasure?.label || currentMeasure?.col || 'the selected indicator';
    const dimension = currentDimension || 'the selected groups';
    const time = currentTime ? ` over ${currentTime}` : '';
    return [
      {
        title: 'Official summary',
        text: suggestedDescription,
        tags: ['official', 'summary', 'evidence'],
      },
      {
        title: 'Comparison focus',
        text: `Compare ${measure} across ${dimension}${time}, focusing on the largest differences and the number of source rows behind the result.`,
        tags: ['comparison', 'ranking', 'evidence'],
      },
      {
        title: 'Officer note',
        text: `Summarise ${measure} for the selected slice in clear report language, then flag caveats only when evidence or computation warnings require them.`,
        tags: ['official', 'caveat', 'source'],
      },
    ];
  }, [currentDimension, currentMeasure?.col, currentMeasure?.label, currentTime, suggestedDescription]);

  const tagOptions = useMemo(() => {
    const tags = ['official', 'summary', 'comparison', 'ranking', 'trend', 'evidence', 'weighted', 'caveat', 'source'];
    return tags.filter((tag) => tag !== 'trend' || Boolean(currentTime));
  }, [currentTime]);

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) => prev.includes(tag) ? prev.filter((item) => item !== tag) : [...prev, tag]);
  };

  const handleScopeChange = (next: ReportSectionConfig) => {
    setSectionConfig(next);
    setExecution(null);
    setBlocks([]);
    setAcceptedPreview(null);
    setFlowStep('scope');
    if (activeStep !== 'scope') router.replace(queryPath('scope'), { scroll: false });
  };

  const handlePreviewConfigChange = (next: ReportSectionConfig) => {
    setSectionConfig(next);
    setAcceptedPreview(null);
    setBlocks([]);
  };

  const executeSlice = async () => {
    if (!workspace) return;
    if (!currentMeasure?.col) {
      setError('Choose one measure column before executing the slice. Measures are the numeric indicator values the report computes.');
      return;
    }
    setExecuting(true);
    setError(null);
    try {
      const request = buildReportSectionSpec(
        {
          ...sectionConfig,
          components: ['table'],
        },
        { templateId: workspace.template_id, signature: workspace.signature, datasetId: workspace.dataset_id },
      );
      const result = await generatePhaseApi.generateSection(workspace.template_id, workspace.signature, { request: request as unknown as Record<string, unknown> });
      const execLike: SectionExecutionResult = {
        requestId: request.requestId,
        datasetId: request.datasetId,
        rows: Array.from({ length: result.groups }, () => ({ key: {}, value: null, n: 0, rowIds: [] })),
        measure: request.scope.columns.measures[0] ?? null,
        groupBy: request.analysis.groupBy ?? [],
        filterCombinator: request.scope.filterCombinator || 'AND',
        filtersApplied: [],
        rowsScanned: result.rowsScanned,
        rowsAfterFilter: result.rowsAfterFilter,
        cacheHit: false,
        sliceSignature: '',
        warnings: result.warnings ?? [],
      };
      setExecution(execLike);
      setBlocks([]);
      setAcceptedPreview(null);
      goToStep('data_preview');
    } catch (err: unknown) {
      setExecution(null);
      setBlocks([]);
      setError(executeErrorMessage(err));
    } finally {
      setExecuting(false);
    }
  };

  const generateReportPreview = async () => {
    if (!workspace || !execution) return;
    if (!previewAccepted) {
      setError('Accept the Data and Weight Preview before generating report blocks.');
      goToStep('data_preview');
      return;
    }
    if (!selectedComponents.length) {
      setError('Choose at least one output component before generating the report preview.');
      return;
    }
    setPreviewGenerating(true);
    setError(null);
    setSynthesis(null);
    try {
      const request = buildReportSectionSpec(
        {
          ...sectionConfig,
          components: selectedComponents,
        },
        { templateId: workspace.template_id, signature: workspace.signature, datasetId: workspace.dataset_id },
      );
      const result = await generatePhaseApi.generateSection(workspace.template_id, workspace.signature, { request: request as unknown as Record<string, unknown> });
      setBlocks(result.blocks || []);
      goToStep('preview');
    } catch (err: unknown) {
      setBlocks([]);
      setError(executeErrorMessage(err));
    } finally {
      setPreviewGenerating(false);
    }
  };

  const synthesizeReport = async () => {
    if (!workspace) return;
    setSynthesizing(true);
    setError(null);
    try {
      const out = await generatePhaseApi.synthesize(workspace.template_id, workspace.signature, {
        description: sectionConfig.descriptionText || suggestedDescription,
        tags: selectedTags,
        components: selectedComponents.map((type) => ({ type })),
        measures: sectionConfig.measures.map((m) => ({ col: m.col, label: m.label, agg: m.agg, weighted: m.weighted, unit: m.unit })),
        weight_insights: (acceptedPreview?.weightInsights ?? null) as Record<string, unknown> | null,
        blocks: blocks as unknown as Array<Record<string, unknown>>,
        section_title: sectionConfig.sectionTitle,
        chapter_title: sectionConfig.chapterTitle,
        dataset_id: workspace.dataset_id,
        analysis_type: sectionConfig.analysisType,
        max_words: 220,
      });
      setSynthesis({ content: out.content, keyFindings: out.key_findings || [], usedLlm: out.used_llm, provider: out.provider, notes: out.notes || [] });
    } catch (err: unknown) {
      setError(executeErrorMessage(err));
    } finally {
      setSynthesizing(false);
    }
  };

  const sendToCanvas = () => {
    if (!workspace || !blocks.length) return;
    const request = buildReportSectionSpec(
      {
        ...sectionConfig,
        components: selectedComponents,
        mode: placementMode === 'append_chapter' ? 'append' : sectionConfig.mode,
      },
      { templateId: workspace.template_id, signature: workspace.signature, datasetId: workspace.dataset_id },
    );
    // Prepend the AI-synthesized, weight-grounded narrative as the lead block.
    const synthesizedBlocks: GeneratedSectionBlock[] = synthesis
      ? [{
          id: `${request.requestId}-synthesis`,
          index: -1,
          kind: 'narrative',
          title: 'Synthesized summary',
          content: synthesis.content,
          sectionPath: [sectionConfig.chapterTitle, sectionConfig.sectionTitle],
          status: 'done',
          pageIndex: 0,
        }, ...blocks]
      : blocks;
    const bundle: ReportCanvasHandoffBundle = {
      version: 'report.canvas.handoff.v1',
      templateId: workspace.template_id,
      signature: workspace.signature,
      datasetId: workspace.dataset_id,
      generatedAt: new Date().toISOString(),
      sections: [{
        id: request.requestId,
        request,
        blocks: synthesizedBlocks,
        meta: {
          rowsAfterFilter: execution?.rowsAfterFilter,
          rowsScanned: execution?.rowsScanned,
          groups: execution?.rows.length,
          acceptedPreview: previewAccepted ? acceptedPreview : undefined,
        },
        addedAt: Date.now(),
      }],
    };
    sessionStorage.setItem(canvasHandoffStorageKey(workspace.template_id, workspace.signature), JSON.stringify(bundle));
    router.push(`/report-builder/canvas/${encodeURIComponent(workspace.template_id)}/${encodeURIComponent(workspace.signature)}?draftMode=${destinationMode}`);
  };

  const toggleComponent = (component: SectionComponentType) => {
    setSelectedComponents((prev) => prev.includes(component) ? prev.filter((item) => item !== component) : [...prev, component]);
  };

  return (
    <main className="min-h-screen bg-surface px-4 py-6 text-text lg:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Link href="/report-builder/binding" className="inline-flex items-center gap-1 text-xs font-medium text-text-muted hover:text-primary">
              <ArrowLeft className="h-3.5 w-3.5" /> Back to binding
            </Link>
            <h1 className="mt-2 text-2xl font-semibold text-text">Query Flow</h1>
            <p className="mt-1 max-w-3xl text-sm text-text-muted">
              Convert confirmed binding context into section JSON, enrich it with description and component choices, then generate report blocks for the canvas.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default" className="text-[10px]">{templateLabel}</Badge>
            <Badge variant="warning" className="text-[10px] uppercase">{workflowMode.replace('_', ' ')}</Badge>
            <Badge variant={statusVariant(planStatus)} className="text-[10px] uppercase">{planStatus}</Badge>
          </div>
        </div>

        {loading && (
          <Card className="flex items-center gap-3 p-5 text-sm text-text-muted">
            <Loader2 className="h-4 w-4 animate-spin text-primary" /> Loading binding workspace...
          </Card>
        )}

        {error && <Alert variant="error" title="Query Flow could not start">{error}</Alert>}

        {workspace && (
          <div className="space-y-5">
            <Card className="p-4">
              <div className="grid gap-2 md:grid-cols-5">
                {([
                  ['scope', '1. Scope', 'filters + measures'],
                  ['data_preview', '2. Data Preview', 'filtered rows + weights'],
                  ['description', '3. Description', 'narrative intent'],
                  ['components', '4. Components', 'recommended blocks'],
                  ['preview', '5. Preview', 'canvas handoff'],
                ] as const).map(([step, label, hint]) => {
                  const enabled = step === 'scope' || (step === 'data_preview' ? Boolean(execution) : Boolean(execution && previewAccepted));
                  const active = activeStep === step;
                  return (
                    <button
                      key={step}
                      type="button"
                      disabled={!enabled}
                      onClick={() => goToStep(step)}
                      className={`rounded-xl border px-3 py-2 text-left transition-colors ${active ? 'border-primary bg-primary/10 text-primary' : enabled ? 'border-border bg-surface hover:border-primary/40' : 'border-border bg-surface text-text-muted opacity-50'}`}
                    >
                      <p className="text-xs font-semibold">{label}</p>
                      <p className="mt-0.5 text-[10px] text-text-muted">{hint}</p>
                    </button>
                  );
                })}
              </div>
            </Card>

            {activeStep === 'scope' && (
              <>
                <Card className="p-5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
                        <ShieldCheck className="h-4 w-4 text-primary" /> Dataset context
                      </h2>
                      <p className="mt-1 text-xs text-text-muted">Using the dataset and column profile already confirmed in Binding.</p>
                    </div>
                    <Badge variant="default" className="text-[10px]">{workspace.dataset_id}</Badge>
                  </div>
                  <div className="mt-4 grid gap-2 sm:grid-cols-4">
                    {[
                      ['Columns', columnStats.total],
                      ['Dimensions', columnStats.dimensions],
                      ['Measures', columnStats.measures],
                      ['Time', columnStats.time],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-lg border border-border bg-surface px-3 py-2">
                        <p className="text-[10px] uppercase tracking-wide text-text-muted">{label}</p>
                        <p className="text-lg font-semibold text-text">{value}</p>
                      </div>
                    ))}
                  </div>
                </Card>

                <Card className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <h2 className="text-sm font-semibold text-text">What to fill now</h2>
                      <p className="mt-1 text-xs text-text-muted">Choose the measure, optional dimensions/time, and filters. Nothing is sent to canvas from this step.</p>
                    </div>
                    <Badge variant={canExecute ? 'success' : 'warning'} className="text-[10px] uppercase">{canExecute ? 'ready to execute' : 'needs measure'}</Badge>
                  </div>
                  <div className="mt-4 grid gap-2 md:grid-cols-4">
                    <div className="rounded-lg border border-border bg-surface px-3 py-2">
                      <p className="text-[10px] uppercase tracking-wide text-text-muted">Measure</p>
                      <p className="mt-1 truncate text-xs font-semibold text-text">{currentMeasure?.label || currentMeasure?.col || 'Choose numeric indicator'}</p>
                    </div>
                    <div className="rounded-lg border border-border bg-surface px-3 py-2">
                      <p className="text-[10px] uppercase tracking-wide text-text-muted">Group by</p>
                      <p className="mt-1 truncate text-xs font-semibold text-text">{currentDimension || 'Optional'}</p>
                    </div>
                    <div className="rounded-lg border border-border bg-surface px-3 py-2">
                      <p className="text-[10px] uppercase tracking-wide text-text-muted">Time</p>
                      <p className="mt-1 truncate text-xs font-semibold text-text">{currentTime || 'Optional'}</p>
                    </div>
                    <div className="rounded-lg border border-border bg-surface px-3 py-2">
                      <p className="text-[10px] uppercase tracking-wide text-text-muted">Filters</p>
                      <p className="mt-1 truncate text-xs font-semibold text-text">{sectionConfig.filters.length ? `${sectionConfig.filters.length} filter(s)` : 'All rows'}</p>
                    </div>
                  </div>
                </Card>

                <QueryIndicatorFilters
                  file={null}
                  columns={workspace.dataset_ast.columns}
                  config={sectionConfig}
                  onChange={handleScopeChange}
                  templateId={workspace.template_id}
                  signature={workspace.signature}
                  datasetId={workspace.dataset_id}
                  hideTarget
                  hideOutputComponents
                  hideGenerateControls
                  requireMeasure={false}
                />

                <Card className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="max-w-3xl">
                      <h2 className="text-sm font-semibold text-text">Execute the slice</h2>
                      <p className="mt-1 text-xs text-text-muted">This validates the current JSON against the backend-stashed dataset and then opens the Data Preview page.</p>
                    </div>
                    <Button type="button" size="sm" onClick={executeSlice} disabled={!canExecute || executing}>
                      {executing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                      Execute slice
                    </Button>
                  </div>
                </Card>
              </>
            )}

            {activeStep !== 'scope' && !execution && (
              <Card className="p-5">
                <p className="text-sm font-semibold text-text">Execute the slice first</p>
                <p className="mt-1 text-xs text-text-muted">Data preview, description, components, and report preview are unlocked after the data slice runs successfully.</p>
                <Button type="button" size="sm" className="mt-3" onClick={() => goToStep('scope')}>Back to scope</Button>
              </Card>
            )}

            {activeStep === 'data_preview' && execution && previewRequest && (
              <QueryDataPreviewStep
                columns={workspace.dataset_ast.columns}
                config={sectionConfig}
                request={previewRequest}
                execution={execution}
                acceptanceKey={previewAcceptanceKey}
                acceptedPreview={acceptedPreview}
                onConfigChange={handlePreviewConfigChange}
                onAccept={(metadata) => { setAcceptedPreview(metadata); goToStep('description'); }}
                onBack={() => goToStep('scope')}
              />
            )}

            {activeStep !== 'scope' && activeStep !== 'data_preview' && execution && !previewAccepted && (
              <Card className="p-5">
                <p className="text-sm font-semibold text-text">Accept the data preview first</p>
                <p className="mt-1 text-xs text-text-muted">Description and report block generation are locked until the filtered rows, weighting, and aggregation choices are accepted.</p>
                <Button type="button" size="sm" className="mt-3" onClick={() => goToStep('data_preview')}>Open data preview</Button>
              </Card>
            )}

            {activeStep === 'description' && execution && previewAccepted && (
              <Card className="space-y-5 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold text-text">Description</h2>
                    <p className="mt-1 text-xs text-text-muted">{execution.rowsAfterFilter.toLocaleString('en-IN')} of {execution.rowsScanned.toLocaleString('en-IN')} rows matched. Choose a suggestion or write the report intent.</p>
                  </div>
                  <Badge variant="success" className="text-[10px]">slice executed</Badge>
                </div>
                <div className="grid gap-3 lg:grid-cols-3">
                  {descriptionSuggestions.map((suggestion) => (
                    <button
                      key={suggestion.title}
                      type="button"
                      onClick={() => { setSectionConfig((prev) => ({ ...prev, descriptionText: suggestion.text })); setSelectedTags(suggestion.tags); }}
                      className="rounded-xl border border-border bg-surface p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
                    >
                      <p className="text-sm font-semibold text-text">{suggestion.title}</p>
                      <p className="mt-2 text-xs leading-relaxed text-text-muted">{suggestion.text}</p>
                      <div className="mt-3 flex flex-wrap gap-1">
                        {suggestion.tags.map((tag) => <span key={tag} className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary">{tag}</span>)}
                      </div>
                    </button>
                  ))}
                </div>
                <div className="rounded-xl border border-border bg-surface p-4">
                  <label className="block">
                    <span className="text-xs font-semibold uppercase tracking-wide text-text-muted">Final description</span>
                    <textarea
                      value={sectionConfig.descriptionText}
                      onChange={(event) => setSectionConfig((prev) => ({ ...prev, descriptionText: event.target.value }))}
                      rows={4}
                      placeholder={suggestedDescription}
                      className="mt-2 w-full rounded-lg border border-border bg-surface-card px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-primary/20"
                    />
                  </label>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {tagOptions.map((tag) => {
                      const active = selectedTags.includes(tag);
                      return <button key={tag} type="button" onClick={() => toggleTag(tag)} className={`rounded-full border px-2 py-1 text-[10px] ${active ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-surface-card text-text-muted'}`}>{tag}</button>;
                    })}
                  </div>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <Button type="button" variant="outline" onClick={() => goToStep('data_preview')}>Back to data preview</Button>
                  <Button type="button" onClick={() => goToStep('components')} disabled={!sectionConfig.descriptionText.trim()}>Continue to components <ArrowRight className="h-4 w-4" /></Button>
                </div>
              </Card>
            )}

            {activeStep === 'components' && execution && previewAccepted && (
              <Card className="space-y-5 p-5">
                <div>
                  <h2 className="text-base font-semibold text-text">Components and destination</h2>
                  <p className="mt-1 text-xs text-text-muted">Select the report blocks and where this generated section should land after preview.</p>
                </div>
                <div className="grid gap-4 lg:grid-cols-3">
                  <div className="rounded-xl border border-border bg-surface p-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Components</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(['narrative', 'table', 'chart', 'metric', 'key_finding'] as SectionComponentType[]).map((component) => {
                        const active = selectedComponents.includes(component);
                        return (
                          <button key={component} type="button" onClick={() => toggleComponent(component)} className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-medium ${active ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-surface-card text-text-muted'}`}>
                            {active && <Check className="h-3 w-3" />}
                            {component.replace('_', ' ')}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="rounded-xl border border-border bg-surface p-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Canvas</p>
                    <div className="mt-2 grid gap-1.5">
                      {(['existing', 'new'] as const).map((mode) => <button key={mode} type="button" onClick={() => setDestinationMode(mode)} className={`rounded-lg border px-3 py-2 text-left text-xs ${destinationMode === mode ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-surface-card text-text-muted'}`}>{mode === 'existing' ? 'Use existing/select draft' : 'Create new canvas draft'}</button>)}
                    </div>
                  </div>
                  <div className="rounded-xl border border-border bg-surface p-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Placement</p>
                    <div className="mt-2 grid gap-1.5">
                      {([['append_chapter', 'Append at chapter end'], ['new_chapter', 'Create new chapter'], ['new_section', 'Create new section']] as const).map(([mode, label]) => <button key={mode} type="button" onClick={() => setPlacementMode(mode)} className={`rounded-lg border px-3 py-2 text-left text-xs ${placementMode === mode ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-surface-card text-text-muted'}`}>{label}</button>)}
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <Button type="button" variant="outline" onClick={() => goToStep('description')}>Back to description</Button>
                  <Button type="button" onClick={generateReportPreview} disabled={previewGenerating || !selectedComponents.length}>
                    {previewGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    Generate report preview
                  </Button>
                </div>
              </Card>
            )}

            {activeStep === 'preview' && execution && previewAccepted && (
              <Card className="space-y-5 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="text-base font-semibold text-text">Report preview and canvas handoff</h2>
                    <p className="mt-1 text-xs text-text-muted">Review the generated blocks, then send them to the selected canvas draft.</p>
                  </div>
                  <button type="button" onClick={() => { setBlocks([]); goToStep('components'); }} className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs text-text-muted hover:text-text"><X className="h-3.5 w-3.5" /> Close preview</button>
                </div>
                {blocks.length > 0 ? <div className="space-y-3">{blocks.map((block) => <SectionBlockView key={block.id} block={block} />)}</div> : <Alert variant="warning">Generate the report preview from the Components step first.</Alert>}

                {/* Synthesizer LLM layer — composes description + components +
                    weight-insights JSON into grounded report prose. */}
                <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-text"><Sparkles className="h-4 w-4 text-primary" /> AI report synthesizer</h3>
                      <p className="mt-1 text-xs text-text-muted">
                        Feeds your description, tags, components and the accepted weight-insights JSON to the LLM to draft grounded section prose.
                        {acceptedPreview?.weightInsights?.weightingApplied ? ' Weighted figures included.' : ''}
                      </p>
                    </div>
                    <Button type="button" size="sm" onClick={synthesizeReport} disabled={synthesizing}>
                      {synthesizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                      {synthesis ? 'Re-synthesize' : 'Synthesize content'}
                    </Button>
                  </div>
                  {synthesis && (
                    <div className="mt-3 space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={synthesis.usedLlm ? 'success' : 'muted'} className="text-[10px] uppercase">
                          {synthesis.usedLlm ? `LLM · ${synthesis.provider}` : 'deterministic'}
                        </Badge>
                        {acceptedPreview?.weightInsights && (
                          <Badge variant="default" className="text-[10px] uppercase">grounded in weight.insights.v1</Badge>
                        )}
                      </div>
                      <div className="rounded-lg border border-border bg-surface-card p-4">
                        <p className="whitespace-pre-line text-sm leading-relaxed text-text">{synthesis.content}</p>
                      </div>
                      {synthesis.keyFindings.length > 0 && (
                        <div className="rounded-lg border border-border bg-surface-card p-3">
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Key findings</p>
                          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-text">
                            {synthesis.keyFindings.map((finding) => <li key={finding}>{finding}</li>)}
                          </ul>
                        </div>
                      )}
                      {synthesis.notes.length > 0 && (
                        <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-text-muted">
                          {synthesis.notes.map((note) => <li key={note}>{note}</li>)}
                        </ul>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap justify-between gap-2">
                  <Button type="button" variant="outline" onClick={() => goToStep('components')}>Back to components</Button>
                  <Button type="button" onClick={sendToCanvas} disabled={!blocks.length}>Send to canvas <ArrowRight className="h-4 w-4" /></Button>
                </div>
              </Card>
            )}
          </div>
        )}
      </div>
    </main>
  );
}