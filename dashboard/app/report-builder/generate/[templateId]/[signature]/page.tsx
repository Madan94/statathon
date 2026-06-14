'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  AlertCircle, ArrowLeft, ArrowRight, BarChart3, BookOpen, CheckCircle2, ChevronDown,
  Clock, Download, ExternalLink, FileText, FunctionSquare, Layers, Loader2,
  MessageSquare, Pause, Pencil, Play, RefreshCw, SkipForward, Sparkles, StopCircle,
  Table2, Zap,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { ReportDocumentCanvas, type DocBlock } from '@/components/report-builder/render/ReportDocumentCanvas';
import { generatePhaseApi } from '@/lib/api';

// ─── Types ──────────────────────────────────────────────────────────────────

interface QueueItem {
  index: number;
  plan_id: string;
  question_id: string;
  component_type: string;
  title: string;
  section_path: string[];
  status: string;
}

interface TraceEntry {
  ts: number;
  level: 'info' | 'success' | 'error' | 'warn' | 'step';
  message: string;
  detail?: string;
  componentIndex?: number;
}

type Phase = 'loading' | 'ready' | 'generating' | 'preview' | 'auto' | 'paused' | 'complete' | 'error';
type GenMode = 'step' | 'auto';

// ─── Helpers ────────────────────────────────────────────────────────────────

function compIcon(kind: string) {
  if (kind === 'chart' || kind === 'figure') return BarChart3;
  if (kind === 'table') return Table2;
  if (kind === 'formula_metric' || kind === 'metric') return FunctionSquare;
  if (kind === 'narrative' || kind === 'key_finding' || kind === 'heading') return FileText;
  return MessageSquare;
}

function fmtTime(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function sectionHeadings(queue: QueueItem[]): Map<number, string> {
  const map = new Map<number, string>();
  let lastPath = '';
  for (const item of queue) {
    const path = item.section_path.join(' › ');
    if (path && path !== lastPath) {
      map.set(item.index, path);
      lastPath = path;
    }
  }
  return map;
}

// ─── Main Component ─────────────────────────────────────────────────────────

export default function GenerationWorkspacePage() {
  const params = useParams();
  const templateId = params.templateId as string;
  const signature = params.signature as string;

  // Core state
  const [phase, setPhase] = useState<Phase>('loading');
  const [mode, setMode] = useState<GenMode>('step');
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [generated, setGenerated] = useState<Set<number>>(new Set());
  const [errors, setErrors] = useState<Set<number>>(new Set());
  const [blocks, setBlocks] = useState<DocBlock[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Trace log (ChatGPT-style thinking steps)
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const traceRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef(false);

  // Timing
  const [genStartTime, setGenStartTime] = useState(0);
  const [genTimes, setGenTimes] = useState<Map<number, number>>(new Map());
  const [totalElapsed, setTotalElapsed] = useState(0);

  // Sidebar state
  const [sidebarTab, setSidebarTab] = useState<'trace' | 'queue'>('trace');

  const addTrace = useCallback((entry: Omit<TraceEntry, 'ts'>) => {
    setTrace((prev) => [...prev, { ...entry, ts: Date.now() }]);
    setTimeout(() => traceRef.current?.scrollTo({ top: traceRef.current.scrollHeight, behavior: 'smooth' }), 50);
  }, []);

  // ─── Section heading injection ──────────────────────────────────────────

  const headingMap = useRef(new Map<number, string>());

  // ─── Initialize ─────────────────────────────────────────────────────────

  useEffect(() => {
    addTrace({ level: 'step', message: 'Loading generation queue...' });
    generatePhaseApi.getGenerationQueue(templateId, signature)
      .then((q) => {
        setQueue(q);
        headingMap.current = sectionHeadings(q);

        // Build initial blocks with section headings injected
        const initialBlocks: DocBlock[] = [];
        let lastPath = '';
        q.forEach((item) => {
          const path = item.section_path.join(' › ');
          if (path && path !== lastPath) {
            initialBlocks.push({
              id: `heading-${item.index}`,
              kind: 'heading',
              content: item.section_path[item.section_path.length - 1] || path,
              title: path,
              status: 'done',
              level: item.section_path.length <= 1 ? 1 : item.section_path.length <= 2 ? 2 : 3,
            });
            lastPath = path;
          }
          initialBlocks.push({
            id: `block-${item.index}`,
            kind: (item.component_type === 'formula_metric' ? 'metric' : item.component_type) as DocBlock['kind'],
            content: '',
            title: item.title,
            status: 'pending',
            planId: item.plan_id,
            componentIndex: item.index,
            level: item.section_path.length <= 1 ? 2 : 3,
          });
        });

        setBlocks(initialBlocks);
        setPhase('ready');
        addTrace({ level: 'success', message: `Queue loaded: ${q.length} components across ${headingMap.current.size} sections` });
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load queue');
        setPhase('error');
        addTrace({ level: 'error', message: `Failed to load queue: ${err instanceof Error ? err.message : 'unknown error'}` });
      });
  }, [templateId, signature, addTrace]);

  // ─── Generate single component ──────────────────────────────────────────

  const generateOne = useCallback(async (idx: number, redo = false): Promise<boolean> => {
    if (idx >= queue.length) return false;
    const item = queue[idx];
    const t0 = Date.now();

    addTrace({ level: 'step', message: `Thinking about "${item.title}"...`, componentIndex: idx });
    addTrace({ level: 'info', message: `Component type: ${item.component_type}`, detail: `Plan: ${item.plan_id} · Question: ${item.question_id}`, componentIndex: idx });

    setBlocks((prev) => prev.map((b) => b.componentIndex === idx ? { ...b, status: 'generating' } : b));

    try {
      addTrace({ level: 'info', message: `Calling S4 executor → analytics + fill + narrate...`, componentIndex: idx });

      const result = await generatePhaseApi.generateComponent(templateId, signature, {
        index: idx,
        use_llm: true,
        redo,
      });

      const elapsed = Date.now() - t0;
      setGenTimes((prev) => new Map([...prev, [idx, elapsed]]));

      // Build trace from result
      addTrace({ level: 'success', message: `Generated "${result.title}" in ${fmtTime(elapsed)}`, componentIndex: idx });

      if (result.narrative) {
        addTrace({ level: 'info', message: `Narrative: "${result.narrative.slice(0, 120)}${result.narrative.length > 120 ? '...' : ''}"`, componentIndex: idx });
      }
      if (result.content?.value != null) {
        addTrace({ level: 'info', message: `Metric value: ${result.content.value}${result.content.unit ? ` ${result.content.unit}` : ''}`, componentIndex: idx });
      }
      if (result.status) {
        addTrace({ level: 'info', message: `Status: ${result.status} · Progress: ${result.progress_pct}%`, componentIndex: idx });
      }

      // Update block with generated content + structured data
      const contentObj = result.content || {};
      setBlocks((prev) => prev.map((b) => b.componentIndex === idx ? {
        ...b,
        content: result.narrative || String(contentObj.text || contentObj.content || contentObj.value || ''),
        title: result.title,
        kind: (result.component_type === 'formula_metric' ? 'metric' : result.component_type) as DocBlock['kind'],
        metricValue: contentObj.value != null ? String(contentObj.value) : undefined,
        metricUnit: contentObj.unit ? String(contentObj.unit) : undefined,
        // Pass ranking/aggregation data for real table rendering
        tableData: (contentObj.items || contentObj.rankingData || contentObj.rows || contentObj.aggregationData)
          ? contentObj as Record<string, unknown>
          : undefined,
        status: 'done',
      } : b));

      setGenerated((prev) => new Set([...prev, idx]));
      return true;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Generation failed';
      addTrace({ level: 'error', message: `Failed: ${msg}`, componentIndex: idx });
      setBlocks((prev) => prev.map((b) => b.componentIndex === idx ? { ...b, status: 'error' } : b));
      setErrors((prev) => new Set([...prev, idx]));
      return false;
    }
  }, [queue, templateId, signature, addTrace]);

  // ─── Step-by-step controls ──────────────────────────────────────────────

  const generateCurrent = async (redo = false) => {
    if (currentIndex >= queue.length) return;
    setGenerating(true);
    setPhase('generating');
    setError(null);
    setGenStartTime(Date.now());

    const ok = await generateOne(currentIndex, redo);
    if (ok) {
      setPhase('preview');
    } else {
      setError('Generation failed for this component');
      setPhase('preview');
    }
    setGenerating(false);
  };

  const proceedNext = () => {
    const nextIdx = currentIndex + 1;
    if (nextIdx >= queue.length) {
      finishGeneration();
    } else {
      setCurrentIndex(nextIdx);
      setPhase('ready');
    }
  };

  const skipCurrent = () => {
    addTrace({ level: 'warn', message: `Skipped: "${queue[currentIndex]?.title}"`, componentIndex: currentIndex });
    proceedNext();
  };

  const redoCurrent = () => generateCurrent(true);

  // ─── Auto-generate all ─────────────────────────────────────────────────

  const autoGenerateAll = useCallback(async () => {
    setMode('auto');
    setPhase('auto');
    setError(null);
    abortRef.current = false;
    const t0 = Date.now();

    addTrace({ level: 'step', message: `Starting auto-generation of ${queue.length} components...` });

    for (let i = currentIndex; i < queue.length; i++) {
      if (abortRef.current) {
        addTrace({ level: 'warn', message: `Paused at component ${i + 1}/${queue.length}` });
        setCurrentIndex(i);
        setPhase('paused');
        setGenerating(false);
        return;
      }

      setCurrentIndex(i);
      setGenerating(true);

      const ok = await generateOne(i);
      if (!ok) {
        addTrace({ level: 'warn', message: `Error on "${queue[i].title}" — continuing...` });
      }
    }

    setTotalElapsed(Date.now() - t0);
    setGenerating(false);
    finishGeneration();
  }, [queue, currentIndex, generateOne, addTrace]);

  const pauseAutoGenerate = () => {
    abortRef.current = true;
    addTrace({ level: 'warn', message: 'Pause requested...' });
  };

  const resumeAutoGenerate = () => {
    autoGenerateAll();
  };

  // ─── Finish ─────────────────────────────────────────────────────────────

  const finishGeneration = useCallback(() => {
    setPhase('complete');
    addTrace({ level: 'step', message: 'All components processed. Assembling final report...' });

    generatePhaseApi.generate(templateId, signature, { use_llm: true, publish_mode: 'draft' })
      .then(() => addTrace({ level: 'success', message: 'Final report assembled and rendered.' }))
      .catch(() => addTrace({ level: 'warn', message: 'Assembly step skipped (non-fatal).' }));
  }, [templateId, signature, addTrace]);

  // ─── Block CRUD ─────────────────────────────────────────────────────────

  const updateBlock = (id: string, updates: Partial<DocBlock>) => setBlocks((prev) => prev.map((b) => b.id === id ? { ...b, ...updates } : b));
  const reorderBlock = (id: string, dir: 'up' | 'down') => {
    setBlocks((prev) => {
      const idx = prev.findIndex((b) => b.id === id);
      if (idx < 0) return prev;
      const target = dir === 'up' ? idx - 1 : idx + 1;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };
  const deleteBlock = (id: string) => setBlocks((prev) => prev.filter((b) => b.id !== id));
  const insertBlock = (afterId: string, kind: DocBlock['kind']) => {
    setBlocks((prev) => {
      const idx = prev.findIndex((b) => b.id === afterId);
      const newBlock: DocBlock = { id: `custom-${Date.now()}`, kind, content: '', status: 'done', level: kind === 'heading' ? 3 : undefined };
      const next = [...prev];
      next.splice(idx + 1, 0, newBlock);
      return next;
    });
  };

  // ─── Computed ───────────────────────────────────────────────────────────

  const progress = queue.length > 0 ? Math.round((generated.size / queue.length) * 100) : 0;
  const currentItem = queue[currentIndex];
  const nextItem = currentIndex + 1 < queue.length ? queue[currentIndex + 1] : null;
  const avgTime = genTimes.size > 0 ? [...genTimes.values()].reduce((a, b) => a + b, 0) / genTimes.size : 0;
  const remaining = queue.length - generated.size - errors.size;
  const eta = remaining > 0 && avgTime > 0 ? remaining * avgTime : 0;

  // ─── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-7xl space-y-5 pb-12">
      <PageHeader
        title="Report generation"
        description={`${generated.size}/${queue.length} components · ${templateId}`}
        actions={<Link href="/report-builder/binding"><Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" /> Binding</Button></Link>}
      />

      {/* ─── Top bar: progress + controls ─── */}
      <div className="rounded-xl border border-border bg-surface-card shadow-sm">
        {/* Progress section */}
        <div className="px-5 py-3">
          <div className="flex items-center justify-between text-xs text-text-muted">
            <span className="flex items-center gap-2">
              {phase === 'generating' || phase === 'auto' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
              ) : phase === 'complete' ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-success" />
              ) : phase === 'paused' ? (
                <Pause className="h-3.5 w-3.5 text-warning" />
              ) : (
                <Zap className="h-3.5 w-3.5 text-primary" />
              )}
              {phase === 'complete'
                ? 'All components generated'
                : phase === 'auto' || phase === 'generating'
                  ? `Generating ${currentItem?.title || ''}...`
                  : phase === 'paused'
                    ? `Paused at component ${currentIndex + 1}`
                    : `Component ${currentIndex + 1} of ${queue.length}`}
            </span>
            <div className="flex items-center gap-3">
              {avgTime > 0 && (
                <span className="flex items-center gap-1 text-[10px]">
                  <Clock className="h-3 w-3" /> avg {fmtTime(avgTime)}
                  {eta > 0 && <> · ~{fmtTime(eta)} left</>}
                </span>
              )}
              <span className="font-mono">{progress}%</span>
            </div>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border/30">
            <div className="h-full rounded-full bg-gradient-to-r from-primary/40 to-primary transition-all duration-700 ease-out" style={{ width: `${progress}%` }} />
          </div>
          {/* Component segment indicators */}
          {queue.length > 0 && queue.length <= 40 && (
            <div className="mt-1.5 flex gap-px">
              {queue.map((item) => (
                <div
                  key={item.index}
                  className={`h-1 flex-1 rounded-full transition-colors ${
                    generated.has(item.index) ? 'bg-success/60' : errors.has(item.index) ? 'bg-danger/60' : item.index === currentIndex && generating ? 'animate-pulse bg-primary/50' : 'bg-border/30'
                  }`}
                  title={`${item.index + 1}. ${item.title}`}
                />
              ))}
            </div>
          )}
        </div>

        {/* Action bar */}
        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-2.5">
          {/* Left: current component info */}
          <div className="flex items-center gap-2 text-xs">
            {currentItem && (() => { const Icon = compIcon(currentItem.component_type); return <Icon className="h-4 w-4 text-text-muted" />; })()}
            <span className="font-medium text-text">{currentItem?.title || 'Ready'}</span>
            {currentItem && (
              <Badge variant="muted" className="text-[9px]">{currentItem.component_type.replace(/_/g, ' ')}</Badge>
            )}
            {currentItem?.section_path.length ? (
              <span className="hidden text-[10px] text-text-muted sm:inline">
                {currentItem.section_path.join(' › ')}
              </span>
            ) : null}
          </div>

          {/* Right: action buttons */}
          <div className="flex items-center gap-2">
            {/* Step-by-step controls */}
            {phase === 'ready' && (
              <>
                <Button size="sm" onClick={() => generateCurrent()} disabled={generating}>
                  <Sparkles className="h-3.5 w-3.5" /> Generate
                </Button>
                <Button size="sm" variant="outline" onClick={() => autoGenerateAll()} disabled={generating}>
                  <Play className="h-3.5 w-3.5" /> Auto-generate all
                </Button>
              </>
            )}
            {phase === 'preview' && (
              <>
                <Button variant="outline" size="sm" onClick={redoCurrent} disabled={generating}>
                  <RefreshCw className="h-3.5 w-3.5" /> Redo
                </Button>
                <Button variant="outline" size="sm" onClick={skipCurrent} disabled={generating}>
                  <SkipForward className="h-3.5 w-3.5" /> Skip
                </Button>
                <Button size="sm" onClick={proceedNext} disabled={generating}>
                  <ArrowRight className="h-3.5 w-3.5" /> {nextItem ? 'Next' : 'Finish'}
                </Button>
                <div className="mx-1 h-4 w-px bg-border" />
                <Button size="sm" variant="outline" onClick={() => autoGenerateAll()} disabled={generating}>
                  <Play className="h-3.5 w-3.5" /> Continue all
                </Button>
              </>
            )}
            {/* Auto mode controls */}
            {(phase === 'auto' || phase === 'generating') && mode === 'auto' && (
              <Button size="sm" variant="outline" onClick={pauseAutoGenerate}>
                <Pause className="h-3.5 w-3.5" /> Pause
              </Button>
            )}
            {phase === 'paused' && (
              <>
                <Button size="sm" onClick={resumeAutoGenerate}>
                  <Play className="h-3.5 w-3.5" /> Resume
                </Button>
                <Button size="sm" variant="outline" onClick={() => { setMode('step'); setPhase('ready'); }}>
                  <StopCircle className="h-3.5 w-3.5" /> Switch to step
                </Button>
              </>
            )}
            {/* Complete controls */}
            {phase === 'complete' && (
              <>
                <a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer">
                  <Button variant="outline" size="sm"><ExternalLink className="h-3.5 w-3.5" /> HTML</Button>
                </a>
                <a href={generatePhaseApi.reportPdfUrl(templateId, signature)} target="_blank" rel="noreferrer">
                  <Button variant="outline" size="sm"><Download className="h-3.5 w-3.5" /> PDF</Button>
                </a>
                <Link href={`/report-builder/preview?tid=${templateId}&sig=${signature}`}>
                  <Button size="sm"><Pencil className="h-3.5 w-3.5" /> Edit report</Button>
                </Link>
              </>
            )}
          </div>
        </div>

        {/* Stats row */}
        {generated.size > 0 && (
          <div className="flex items-center gap-4 border-t border-border px-5 py-2 text-[10px] text-text-muted">
            <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3 text-success" /> {generated.size} generated</span>
            {errors.size > 0 && <span className="flex items-center gap-1"><AlertCircle className="h-3 w-3 text-danger" /> {errors.size} errors</span>}
            <span className="flex items-center gap-1"><Layers className="h-3 w-3" /> {remaining} remaining</span>
            {totalElapsed > 0 && <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> Total: {fmtTime(totalElapsed)}</span>}
          </div>
        )}
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      {/* ─── Main area: document canvas + trace sidebar ─── */}
      <div className="flex gap-5">
        {/* Document canvas */}
        <div className="min-w-0 flex-1">
          {phase === 'loading' ? (
            <div className="flex flex-col items-center py-20">
              <Loader2 className="h-8 w-8 animate-spin text-primary/30" />
              <p className="mt-3 text-sm text-text-muted">Loading generation queue...</p>
            </div>
          ) : (
            <ReportDocumentCanvas
              blocks={blocks}
              onUpdateBlock={updateBlock}
              onReorderBlock={reorderBlock}
              onDeleteBlock={deleteBlock}
              onInsertBlock={insertBlock}
              readOnly={phase === 'generating' || phase === 'auto'}
              reportTitle={templateId.replace(/^tpl_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
              reportSubtitle={`Generated from dataset ${signature.slice(0, 8)} · ${queue.length} components`}
            />
          )}
        </div>

        {/* ─── Trace + Queue sidebar ─── */}
        <div className="hidden w-72 shrink-0 xl:block">
          <div className="sticky top-4 space-y-3">
            {/* Sidebar tabs */}
            <div className="flex rounded-lg border border-border bg-surface-card p-0.5">
              <button
                type="button"
                onClick={() => setSidebarTab('trace')}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[10px] font-semibold transition-colors ${sidebarTab === 'trace' ? 'bg-primary/10 text-primary' : 'text-text-muted hover:text-text'}`}
              >
                <BookOpen className="h-3 w-3" /> Trace
              </button>
              <button
                type="button"
                onClick={() => setSidebarTab('queue')}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[10px] font-semibold transition-colors ${sidebarTab === 'queue' ? 'bg-primary/10 text-primary' : 'text-text-muted hover:text-text'}`}
              >
                <Layers className="h-3 w-3" /> Queue
              </button>
            </div>

            {/* Trace log (ChatGPT-style thinking) */}
            {sidebarTab === 'trace' && (
              <div className="rounded-xl border border-border bg-surface-card">
                <div className="border-b border-border px-4 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Generation trace
                    {trace.length > 0 && <span className="ml-2 font-mono font-normal text-text-muted">{trace.length}</span>}
                  </p>
                </div>
                <div ref={traceRef} className="max-h-[65vh] overflow-auto">
                  {trace.map((entry, i) => (
                    <div
                      key={i}
                      className={`border-b border-border/50 px-4 py-2 last:border-b-0 ${
                        entry.level === 'step' ? 'bg-primary/3' : ''
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 shrink-0">
                          {entry.level === 'success' ? <CheckCircle2 className="h-3 w-3 text-success" /> :
                           entry.level === 'error' ? <AlertCircle className="h-3 w-3 text-danger" /> :
                           entry.level === 'warn' ? <AlertCircle className="h-3 w-3 text-warning" /> :
                           entry.level === 'step' ? <Sparkles className="h-3 w-3 text-primary" /> :
                           <ChevronDown className="h-3 w-3 text-text-muted" />}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className={`text-[10px] leading-relaxed ${
                            entry.level === 'success' ? 'text-success' :
                            entry.level === 'error' ? 'text-danger' :
                            entry.level === 'warn' ? 'text-warning' :
                            entry.level === 'step' ? 'font-medium text-text' :
                            'text-text-muted'
                          }`}>
                            {entry.message}
                          </p>
                          {entry.detail && (
                            <p className="mt-0.5 text-[9px] text-text-muted">{entry.detail}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                  {trace.length === 0 && (
                    <div className="px-4 py-6 text-center text-[10px] text-text-muted">
                      Generation trace will appear here as components are processed.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Queue list */}
            {sidebarTab === 'queue' && (
              <div className="rounded-xl border border-border bg-surface-card">
                <div className="border-b border-border px-4 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Component queue
                    <span className="ml-2 font-mono font-normal">{generated.size}/{queue.length}</span>
                  </p>
                </div>
                <div className="max-h-[65vh] divide-y divide-border/50 overflow-auto">
                  {queue.map((item) => {
                    const Icon = compIcon(item.component_type);
                    const isDone = generated.has(item.index);
                    const isError = errors.has(item.index);
                    const isCurrent = item.index === currentIndex;
                    const isRunning = isCurrent && generating;
                    const time = genTimes.get(item.index);
                    return (
                      <div
                        key={item.index}
                        className={`flex items-center gap-2 px-4 py-2 text-[10px] transition-colors ${
                          isCurrent ? 'bg-primary/5' : ''
                        }`}
                      >
                        <span className="shrink-0">
                          {isDone ? <CheckCircle2 className="h-3 w-3 text-success" /> :
                           isError ? <AlertCircle className="h-3 w-3 text-danger" /> :
                           isRunning ? <Loader2 className="h-3 w-3 animate-spin text-primary" /> :
                           <span className="flex h-3 w-3 items-center justify-center rounded-full border border-border text-[7px] text-text-muted">{item.index + 1}</span>}
                        </span>
                        <Icon className="h-3 w-3 shrink-0 text-text-muted" />
                        <span className={`min-w-0 flex-1 truncate ${isCurrent ? 'font-medium text-primary' : isDone ? 'text-text-muted' : 'text-text'}`}>
                          {item.title}
                        </span>
                        {time != null && (
                          <span className="shrink-0 font-mono text-[9px] text-text-muted">{fmtTime(time)}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
