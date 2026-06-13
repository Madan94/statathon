'use client';

import { useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, ArrowRight, BarChart3, BookOpen, CheckCircle2, Clock, Download, ExternalLink, FileText, FunctionSquare, Loader2, MessageSquare, Pencil, Play, Sparkles, Table2, XCircle, Zap } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { generatePhaseApi } from '@/lib/api';
import type { ReportAST } from '@/lib/report/types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ReportBlock = Record<string, any>;
type PipelineStage = 'idle' | 'executing' | 'assembling' | 'rendering' | 'complete' | 'failed';

interface GenState {
  stage: PipelineStage;
  progress: number;
  startedAt: number | null;
  completedAt: number | null;
  error: string | null;
  report: ReportAST | null;
  message: string;
}

function elapsed(start: number | null): string {
  if (!start) return '';
  const s = Math.round((Date.now() - start) / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function compIcon(kind: string) {
  if (kind === 'chart' || kind === 'figure') return BarChart3;
  if (kind === 'table') return Table2;
  if (kind === 'formula_metric' || kind === 'metric') return FunctionSquare;
  if (kind === 'narrative' || kind === 'key_finding' || kind === 'heading') return FileText;
  return MessageSquare;
}

const STAGES = [
  { key: 'executing', label: 'Analytics', desc: 'Formulas & aggregations', icon: Zap },
  { key: 'assembling', label: 'Assembly', desc: 'Slots & narratives', icon: Sparkles },
  { key: 'rendering', label: 'Render', desc: 'Charts & layout', icon: BookOpen },
] as const;

function PipelineHeader({ state }: { state: GenState }) {
  const idx = STAGES.findIndex((s) => s.key === state.stage);
  const done = state.stage === 'complete';
  const fail = state.stage === 'failed';
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface-card shadow-sm">
      <div className="flex items-stretch divide-x divide-border">
        {STAGES.map((s, i) => {
          const isDone = done || idx > i;
          const isActive = idx === i && !done && !fail;
          const Icon = s.icon;
          return (
            <div key={s.key} className={`flex flex-1 items-center gap-3 px-5 py-4 transition-colors duration-500 ${isDone ? 'bg-success/5' : isActive ? 'bg-primary/5' : ''}`}>
              <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all duration-500 ${isDone ? 'bg-success/15 text-success' : isActive ? 'bg-primary/15 text-primary' : 'bg-border/40 text-text-muted'}`}>
                {isDone ? <CheckCircle2 className="h-4 w-4" /> : isActive ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
              </div>
              <div className="min-w-0">
                <p className={`text-sm font-semibold ${isDone ? 'text-success' : isActive ? 'text-primary' : 'text-text-muted'}`}>{s.label}</p>
                <p className="mt-0.5 truncate text-[11px] text-text-muted">{s.desc}</p>
              </div>
            </div>
          );
        })}
      </div>
      <div className="border-t border-border px-5 py-2.5">
        <div className="flex items-center justify-between text-xs text-text-muted">
          <div className="flex items-center gap-2">
            {!done && !fail && state.stage !== 'idle' && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
            {done && <CheckCircle2 className="h-3.5 w-3.5 text-success" />}
            {fail && <XCircle className="h-3.5 w-3.5 text-danger" />}
            <span>{state.message}</span>
          </div>
          <div className="flex items-center gap-3">
            {state.startedAt && <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{elapsed(state.startedAt)}</span>}
            {done && <Badge variant="success">Done</Badge>}
            {fail && <Badge variant="danger">Failed</Badge>}
          </div>
        </div>
        {state.stage !== 'idle' && !done && !fail && (
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-border/40">
            <div className="h-full rounded-full bg-primary/50 transition-all duration-700 ease-out" style={{ width: `${state.progress}%` }} />
          </div>
        )}
        {done && <div className="mt-2 h-1 rounded-full bg-success/20"><div className="h-full w-full rounded-full bg-success" /></div>}
      </div>
    </div>
  );
}

function IdleView({ onGenerate, templateId, signature }: { onGenerate: () => void; templateId: string; signature: string }) {
  return (
    <div className="flex flex-col items-center py-16">
      <div className="flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-primary/10 to-accent/10">
        <Play className="h-9 w-9 text-primary" />
      </div>
      <h2 className="mt-5 text-xl font-semibold text-text">Ready to generate</h2>
      <p className="mt-2 max-w-md text-center text-sm text-text-muted">
        Run the full analytics pipeline, generate narratives, and render your publication-ready report.
      </p>
      <div className="mt-3 flex items-center gap-2 text-xs text-text-muted">
        <Badge variant="muted">{templateId}</Badge>
        <span className="font-mono">{signature}</span>
      </div>
      <Button size="lg" className="mt-8" onClick={onGenerate}>
        <Sparkles className="h-5 w-5" /> Generate report
      </Button>
    </div>
  );
}

function ReportCanvas({ report, templateId, signature }: { report: ReportAST; templateId: string; signature: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' }); }, [report]);

  const sections = report.semanticAST?.sections || [];
  const blocks = report.contentAST?.blocks || [];
  const metadata = report.metadata || {};

  return (
    <div className="rounded-2xl border border-border bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-text-muted" /><span className="text-sm font-semibold text-text">Report</span>{metadata.title && <span className="text-xs text-text-muted">— {String(metadata.title)}</span>}</div>
        <div className="flex gap-2">{sections.length > 0 && <Badge variant="muted">{sections.length} sections</Badge>}{blocks.length > 0 && <Badge variant="muted">{blocks.length} blocks</Badge>}</div>
      </div>
      <div ref={ref} className="max-h-[60vh] overflow-auto p-6 space-y-3">
        {sections.map((s, i) => (
          <div key={s.sectionId || `s-${i}`} className="py-1">
            <div className="flex items-center gap-2">
              <div className={`h-2 w-2 rounded-full ${(s.level || 1) <= 1 ? 'bg-primary' : 'bg-accent'}`} />
              <h3 className={`font-semibold text-slate-700 ${(s.level || 1) <= 1 ? 'text-lg' : 'text-base'}`}>
                {String(typeof s.title === 'object' ? (s.title as Record<string, string>)?.['en-IN'] || '' : s.title || '')}
              </h3>
            </div>
          </div>
        ))}
        {blocks.map((b: ReportBlock, i: number) => {
          const kind = String(b.kind || b.type || 'text');
          const Icon = compIcon(kind);
          return (
            <div key={b.id || `b-${i}`} className="rounded-xl border border-slate-100 bg-slate-50/50 p-4">
              <div className="mb-2 flex items-center gap-2"><Icon className="h-3.5 w-3.5 text-slate-400" /><span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">{kind.replace(/_/g, ' ')}</span></div>
              {(kind === 'narrative' || kind === 'key_finding' || kind === 'heading' || kind === 'text') && <p className="text-sm leading-relaxed text-slate-600">{String(b.content || b.text || b.value || '')}</p>}
              {(kind === 'chart' || kind === 'figure') && <div className="flex h-32 items-center justify-center rounded-lg border border-slate-100 bg-gradient-to-br from-slate-100 to-white"><BarChart3 className="h-6 w-6 text-primary/25" /></div>}
              {kind === 'table' && <div className="flex h-16 items-center justify-center rounded-lg border border-slate-100 bg-slate-50"><Table2 className="h-5 w-5 text-slate-300" /></div>}
              {(kind === 'metric' || kind === 'formula_metric') && <span className="text-2xl font-bold text-primary">{String(b.value || '—')}</span>}
              {(kind === 'source_note' || kind === 'methodology_note' || kind === 'footnote' || kind === 'data_caveat' || kind === 'glossary_term') && <p className="text-xs italic text-slate-400">{String(b.content || b.text || '')}</p>}
            </div>
          );
        })}
        {sections.length === 0 && blocks.length === 0 && (
          <div className="py-10 text-center"><p className="text-sm text-slate-400">Report generated</p><a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm text-primary hover:underline">View rendered HTML <ExternalLink className="h-3 w-3" /></a></div>
        )}
      </div>
    </div>
  );
}

function ActionsBar({ templateId, signature }: { templateId: string; signature: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-success/10"><CheckCircle2 className="h-5 w-5 text-success" /></div>
          <div><p className="text-sm font-semibold text-text">Report ready</p><p className="text-xs text-text-muted">Download, customize, or publish</p></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><ExternalLink className="h-3.5 w-3.5" /> HTML</Button></a>
          <a href={generatePhaseApi.reportPdfUrl(templateId, signature)} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><Download className="h-3.5 w-3.5" /> PDF</Button></a>
          <a href={generatePhaseApi.reportPdfUrl(templateId, signature, { engine: 'latex' })} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><Download className="h-3.5 w-3.5" /> LaTeX</Button></a>
          <Link href={`/report-builder/preview?tid=${templateId}&sig=${signature}`}><Button size="sm"><Pencil className="h-3.5 w-3.5" /> Edit & publish</Button></Link>
        </div>
      </div>
    </div>
  );
}

export default function GenerationWorkspacePage() {
  const params = useParams();
  const templateId = params.templateId as string;
  const signature = params.signature as string;
  const [state, setState] = useState<GenState>({ stage: 'idle', progress: 0, startedAt: null, completedAt: null, error: null, report: null, message: 'Ready to generate' });

  const generate = async () => {
    const t0 = Date.now();
    setState({ stage: 'executing', progress: 15, startedAt: t0, completedAt: null, error: null, report: null, message: 'Computing analytics...' });
    const timer = setInterval(() => setState((s) => {
      if (s.stage === 'executing' && s.progress < 38) return { ...s, progress: s.progress + 3 };
      if (s.stage === 'assembling' && s.progress < 72) return { ...s, progress: s.progress + 2 };
      if (s.stage === 'rendering' && s.progress < 92) return { ...s, progress: s.progress + 1 };
      return s;
    }), 400);
    const t1 = setTimeout(() => setState((s) => ({ ...s, stage: 'assembling', progress: 42, message: 'Filling slots & narrating...' })), 2500);
    const t2 = setTimeout(() => setState((s) => ({ ...s, stage: 'rendering', progress: 75, message: 'Rendering layout...' })), 5000);
    try {
      await generatePhaseApi.generate(templateId, signature, { use_llm: false });
      const report = await generatePhaseApi.getReport(templateId, signature) as ReportAST;
      clearInterval(timer); clearTimeout(t1); clearTimeout(t2);
      setState({ stage: 'complete', progress: 100, startedAt: t0, completedAt: Date.now(), error: null, report, message: `Done in ${elapsed(t0)}` });
    } catch (err) {
      clearInterval(timer); clearTimeout(t1); clearTimeout(t2);
      setState((s) => ({ ...s, stage: 'failed', progress: 0, error: err instanceof Error ? err.message : 'Generation failed', message: 'Failed' }));
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-5 pb-12">
      <PageHeader title="Generation workspace" description="Execute the analytics pipeline and assemble your report." actions={<Link href="/report-builder/binding"><Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" /> Binding</Button></Link>} />
      <PipelineHeader state={state} />
      {state.error && <Alert variant="error">{state.error}</Alert>}
      {state.stage === 'idle' && <IdleView onGenerate={generate} templateId={templateId} signature={signature} />}
      {state.report && <ReportCanvas report={state.report} templateId={templateId} signature={signature} />}
      {!state.report && state.stage !== 'idle' && state.stage !== 'failed' && (
        <div className="flex flex-col items-center py-12"><Loader2 className="h-8 w-8 animate-spin text-primary/40" /><p className="mt-3 text-sm text-text-muted">{state.message}</p></div>
      )}
      {state.stage === 'complete' && <ActionsBar templateId={templateId} signature={signature} />}
      {state.stage === 'failed' && <div className="flex justify-center py-4"><Button variant="outline" onClick={generate}><ArrowRight className="h-4 w-4" /> Retry</Button></div>}
    </div>
  );
}
