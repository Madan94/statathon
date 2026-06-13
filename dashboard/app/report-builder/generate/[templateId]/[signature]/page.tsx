'use client';

/**
 * Generation Workspace — S4→S6 pipeline execution with live report canvas.
 * 
 * URL: /report-builder/generate/[templateId]/[signature]
 * 
 * Shows:
 * 1. Pipeline progress header (S4 Execution → S5 Assembly → S6 Render)
 * 2. Live report canvas (components stream in with animation)
 * 3. Export bar after completion (PDF, HTML, Edit, Publish)
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  Download,
  FileText,
  FunctionSquare,
  Loader2,
  MessageSquare,
  Pencil,
  Play,
  Table2,
  XCircle,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Card } from '@/components/ui/Card';
import { generatePhaseApi } from '@/lib/api';
import type { ReportAST } from '@/lib/report/types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ReportBlock = Record<string, any>;

// ─── Types ──────────────────────────────────────────────────────────────────

type PipelineStage = 'idle' | 'executing' | 'assembling' | 'rendering' | 'complete' | 'failed';

interface GenerationState {
  stage: PipelineStage;
  progress: number; // 0-100
  startedAt: number | null;
  completedAt: number | null;
  error: string | null;
  report: ReportAST | null;
  statsMessage: string;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function stageLabel(stage: PipelineStage): string {
  switch (stage) {
    case 'idle': return 'Ready to generate';
    case 'executing': return 'S4 — Executing analytics & formulas';
    case 'assembling': return 'S5 — Assembling report & narrating';
    case 'rendering': return 'S6 — Rendering HTML & charts';
    case 'complete': return 'Generation complete';
    case 'failed': return 'Generation failed';
  }
}

function stageIndex(stage: PipelineStage): number {
  if (stage === 'idle') return -1;
  if (stage === 'executing') return 0;
  if (stage === 'assembling') return 1;
  if (stage === 'rendering') return 2;
  if (stage === 'complete') return 3;
  return -1;
}

function componentIcon(kind: string) {
  if (kind === 'chart' || kind === 'figure') return BarChart3;
  if (kind === 'table') return Table2;
  if (kind === 'formula_metric' || kind === 'metric') return FunctionSquare;
  if (kind === 'narrative' || kind === 'key_finding' || kind === 'heading') return FileText;
  return MessageSquare;
}

function elapsed(start: number | null): string {
  if (!start) return '';
  const ms = Date.now() - start;
  if (ms < 1000) return '<1s';
  return `${Math.round(ms / 1000)}s`;
}

// ─── Pipeline Progress Header ───────────────────────────────────────────────

function PipelineProgress({ state }: { state: GenerationState }) {
  const stages = ['S4 Execute', 'S5 Assemble', 'S6 Render'];
  const current = stageIndex(state.stage);

  return (
    <div className="rounded-2xl border border-border bg-surface-card p-4 shadow-sm">
      {/* Stage indicators */}
      <div className="flex items-center justify-between gap-2">
        {stages.map((label, i) => {
          const isDone = current > i;
          const isActive = current === i;
          const isFailed = state.stage === 'failed' && isActive;
          return (
            <div key={label} className="flex flex-1 items-center gap-2">
              <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-all ${isDone ? 'bg-success text-white' : isActive ? (isFailed ? 'bg-danger text-white' : 'bg-primary text-white animate-pulse') : 'bg-border text-text-muted'}`}>
                {isDone ? <CheckCircle2 className="h-4 w-4" /> : isActive ? (isFailed ? <XCircle className="h-4 w-4" /> : <Loader2 className="h-4 w-4 animate-spin" />) : <span className="text-xs font-bold">{i + 1}</span>}
              </div>
              <div className="min-w-0">
                <p className={`text-xs font-semibold ${isDone ? 'text-success' : isActive ? 'text-primary' : 'text-text-muted'}`}>{label}</p>
              </div>
              {i < stages.length - 1 && (
                <div className={`mx-2 h-0.5 flex-1 rounded ${isDone ? 'bg-success' : 'bg-border'}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Status bar */}
      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-text-muted">
        <span>{stageLabel(state.stage)}</span>
        <div className="flex items-center gap-3">
          {state.startedAt && <span>{elapsed(state.startedAt)} elapsed</span>}
          {state.statsMessage && <span className="text-text">{state.statsMessage}</span>}
          {state.stage === 'complete' && <Badge variant="success">READY</Badge>}
          {state.stage === 'failed' && <Badge variant="danger">FAILED</Badge>}
        </div>
      </div>

      {/* Progress bar */}
      {state.stage !== 'idle' && state.stage !== 'complete' && state.stage !== 'failed' && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${state.progress}%` }}
          />
        </div>
      )}
    </div>
  );
}

// ─── Report Canvas ──────────────────────────────────────────────────────────

function ReportCanvas({ report, templateId, signature }: { report: ReportAST | null; templateId: string; signature: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom as new content appears
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [report]);

  if (!report) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-text-muted">
        <Play className="h-10 w-10 mb-3 opacity-30" />
        <p className="text-sm">Click &quot;Generate report&quot; to start the pipeline</p>
        <p className="mt-1 text-xs">The report will appear here as each section is computed</p>
      </div>
    );
  }

  const sections = report.semanticAST?.sections || [];
  const blocks = report.contentAST?.blocks || [];
  const metadata = report.metadata || {};

  return (
    <div ref={scrollRef} className="max-h-[65vh] space-y-4 overflow-auto rounded-xl border border-border bg-white p-6 shadow-inner">
      {/* Report title */}
      {metadata.title && (
        <div className="border-b border-border pb-4 animate-in fade-in slide-in-from-top-2 duration-500">
          <h1 className="text-2xl font-bold text-slate-800">{String(metadata.title)}</h1>
          {metadata.status && <Badge variant="muted" className="mt-2">{String(metadata.period?.current || metadata.status)}</Badge>}
        </div>
      )}

      {/* Sections from semantic AST */}
      {sections.length > 0 && sections.map((section, sIdx) => (
        <div
          key={section.sectionId || `s-${sIdx}`}
          className="animate-in fade-in slide-in-from-bottom-3 duration-700"
          style={{ animationDelay: `${sIdx * 150}ms` }}
        >
          <div className="mb-2 flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${(section.level || 1) === 1 ? 'bg-primary' : (section.level || 1) === 2 ? 'bg-accent' : 'bg-success'}`} />
            <h2 className={`font-semibold text-slate-700 ${(section.level || 1) === 1 ? 'text-xl' : (section.level || 1) === 2 ? 'text-lg' : 'text-base'}`}>
              {String(typeof section.title === 'object' ? (section.title as Record<string, string>)?.['en-IN'] || '' : section.title || '')}
            </h2>
          </div>
        </div>
      ))}

      {/* Content blocks */}
      {blocks.length > 0 && (
        <div className="space-y-3">
          {blocks.map((block: ReportBlock, bIdx: number) => {
            const kind = String(block.kind || block.type || 'text');
            const Icon = componentIcon(kind);
            return (
              <div
                key={block.id || block.componentId || `b-${bIdx}`}
                className="rounded-lg border border-border bg-slate-50 p-4 transition-all animate-in fade-in slide-in-from-left-4 duration-500"
                style={{ animationDelay: `${bIdx * 100}ms` }}
              >
                <div className="mb-2 flex items-center gap-2">
                  <Icon className="h-4 w-4 text-slate-400" />
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{kind}</span>
                </div>

                {/* Narrative / text */}
                {(kind === 'narrative' || kind === 'key_finding' || kind === 'heading' || kind === 'text') && (
                  <p className="text-sm leading-relaxed text-slate-700">{String(block.content || block.text || block.value || '')}</p>
                )}

                {/* Chart */}
                {(kind === 'chart' || kind === 'figure') && (
                  <div className="flex h-40 items-center justify-center rounded-lg bg-gradient-to-br from-primary/5 to-accent/5 border border-primary/10">
                    <div className="text-center">
                      <BarChart3 className="mx-auto h-8 w-8 text-primary/40" />
                      <p className="mt-1 text-xs text-slate-500">{String(block.title || block.caption || 'Chart')}</p>
                    </div>
                  </div>
                )}

                {/* Table */}
                {kind === 'table' && (
                  <div className="overflow-auto rounded border border-slate-200">
                    <div className="flex h-24 items-center justify-center bg-slate-50">
                      <div className="text-center">
                        <Table2 className="mx-auto h-6 w-6 text-slate-400" />
                        <p className="mt-1 text-xs text-slate-500">{String(block.title || block.caption || 'Table')}</p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Metric */}
                {(kind === 'metric' || kind === 'formula_metric') && (
                  <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-bold text-primary">{String(block.value || block.content || '—')}</span>
                    {block.unit && <span className="text-sm text-slate-500">{String(block.unit)}</span>}
                  </div>
                )}

                {/* Source/methodology notes */}
                {(kind === 'source_note' || kind === 'methodology_note' || kind === 'footnote' || kind === 'data_caveat') && (
                  <p className="text-xs italic text-slate-500">{String(block.content || block.text || block.value || '')}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Fallback when no structured content yet */}
      {sections.length === 0 && blocks.length === 0 && (
        <div className="py-8 text-center text-sm text-slate-400">
          Report generated but no structured content found in the AST.
          <br />
          <a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer" className="mt-2 inline-block text-primary underline">
            View server-rendered HTML instead
          </a>
        </div>
      )}
    </div>
  );
}

// ─── Export Bar ──────────────────────────────────────────────────────────────

function ExportBar({ templateId, signature }: { templateId: string; signature: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-success/25 bg-success/5 p-4">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="h-5 w-5 text-success" />
        <div>
          <p className="text-sm font-semibold text-text">Report generated successfully</p>
          <p className="text-xs text-text-muted">All components rendered. Ready for download, editing, or publication.</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <a href={generatePhaseApi.reportPdfUrl(templateId, signature)} target="_blank" rel="noreferrer">
          <Button size="sm"><Download className="h-3.5 w-3.5" /> PDF</Button>
        </a>
        <a href={generatePhaseApi.reportPdfUrl(templateId, signature, { engine: 'latex' })} target="_blank" rel="noreferrer">
          <Button size="sm" variant="outline"><Download className="h-3.5 w-3.5" /> LaTeX PDF</Button>
        </a>
        <a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer">
          <Button size="sm" variant="outline"><FileText className="h-3.5 w-3.5" /> HTML</Button>
        </a>
        <Link href={`/report-builder/preview?tid=${templateId}&sig=${signature}`}>
          <Button size="sm" variant="outline"><Pencil className="h-3.5 w-3.5" /> Edit & Customize</Button>
        </Link>
      </div>
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function GenerationWorkspacePage() {
  const params = useParams();
  const templateId = params.templateId as string;
  const signature = params.signature as string;

  const [state, setState] = useState<GenerationState>({
    stage: 'idle',
    progress: 0,
    startedAt: null,
    completedAt: null,
    error: null,
    report: null,
    statsMessage: '',
  });

  const generate = async () => {
    setState((s) => ({ ...s, stage: 'executing', progress: 10, startedAt: Date.now(), error: null, statsMessage: 'Computing analytics...' }));

    try {
      // Simulate progress stages (the backend does it all in one call)
      const progressTimer = setInterval(() => {
        setState((s) => {
          if (s.stage === 'executing' && s.progress < 40) return { ...s, progress: s.progress + 5 };
          if (s.stage === 'assembling' && s.progress < 75) return { ...s, progress: s.progress + 3 };
          if (s.stage === 'rendering' && s.progress < 95) return { ...s, progress: s.progress + 2 };
          return s;
        });
      }, 300);

      // Move through stages
      setTimeout(() => setState((s) => ({ ...s, stage: 'assembling', progress: 45, statsMessage: 'Narrating & filling slots...' })), 2000);
      setTimeout(() => setState((s) => ({ ...s, stage: 'rendering', progress: 78, statsMessage: 'Rendering charts & tables...' })), 4000);

      // Actual API call
      const result = await generatePhaseApi.generate(templateId, signature, { use_llm: false });
      clearInterval(progressTimer);

      // Fetch the generated report
      const report = await generatePhaseApi.getReport(templateId, signature) as ReportAST;

      setState({
        stage: 'complete',
        progress: 100,
        startedAt: state.startedAt,
        completedAt: Date.now(),
        error: null,
        report,
        statsMessage: `Generated in ${elapsed(state.startedAt || Date.now())}`,
      });
    } catch (err) {
      setState((s) => ({
        ...s,
        stage: 'failed',
        progress: 0,
        error: err instanceof Error ? err.message : 'Generation failed',
        statsMessage: '',
      }));
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Generation Workspace"
        description={`Template: ${templateId} · Signature: ${signature}`}
        actions={
          <Link href="/report-builder/binding">
            <Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" /> Back to binding</Button>
          </Link>
        }
      />

      {/* Pipeline Progress */}
      <PipelineProgress state={state} />

      {/* Error */}
      {state.error && <Alert variant="error">{state.error}</Alert>}

      {/* Generate button (when idle) */}
      {state.stage === 'idle' && (
        <div className="flex justify-center py-4">
          <Button size="lg" onClick={generate}>
            <Play className="h-5 w-5" /> Generate report
          </Button>
        </div>
      )}

      {/* Live Report Canvas */}
      <ReportCanvas report={state.report} templateId={templateId} signature={signature} />

      {/* Export bar (when complete) */}
      {state.stage === 'complete' && (
        <ExportBar templateId={templateId} signature={signature} />
      )}
    </div>
  );
}
