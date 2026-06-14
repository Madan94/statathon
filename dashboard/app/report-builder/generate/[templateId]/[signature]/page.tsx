'use client';

/**
 * Step-by-step Generation Workspace
 * URL: /report-builder/generate/[templateId]/[signature]
 * 
 * Generates components ONE AT A TIME with officer control:
 * - Load queue → show first component preview
 * - Officer clicks "Generate" → runs single component
 * - Shows result with Redo / Proceed Next / Skip options
 * - Repeats until all components done
 * - Final: export bar (PDF/HTML/Edit)
 */

import { useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock,
  Download,
  ExternalLink,
  FileText,
  FunctionSquare,
  Loader2,
  MessageSquare,
  Pencil,
  Play,
  RefreshCw,
  SkipForward,
  Sparkles,
  Table2,
  XCircle,
  Zap,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
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

interface GeneratedComponent {
  index: number;
  component_type: string;
  title: string;
  narrative: string;
  content: Record<string, unknown>;
}

type Phase = 'loading' | 'ready' | 'generating' | 'preview' | 'complete' | 'error';

// ─── Helpers ────────────────────────────────────────────────────────────────

function compIcon(kind: string) {
  if (kind === 'chart' || kind === 'figure') return BarChart3;
  if (kind === 'table') return Table2;
  if (kind === 'formula_metric' || kind === 'metric') return FunctionSquare;
  if (kind === 'narrative' || kind === 'key_finding' || kind === 'heading') return FileText;
  return MessageSquare;
}

function compColor(kind: string): string {
  if (kind === 'chart' || kind === 'figure') return 'text-blue-500';
  if (kind === 'table') return 'text-emerald-500';
  if (kind === 'formula_metric' || kind === 'metric') return 'text-purple-500';
  if (kind === 'narrative' || kind === 'key_finding') return 'text-amber-500';
  return 'text-slate-400';
}

// ─── Queue Sidebar ──────────────────────────────────────────────────────────

function QueueSidebar({ queue, currentIndex, generated }: { queue: QueueItem[]; currentIndex: number; generated: Set<number> }) {
  return (
    <div className="w-64 shrink-0 rounded-xl border border-border bg-surface-card">
      <div className="border-b border-border px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Generation queue</p>
        <p className="mt-0.5 text-[10px] text-text-muted">{generated.size}/{queue.length} complete</p>
      </div>
      <div className="max-h-[55vh] overflow-auto p-2">
        {queue.map((item) => {
          const Icon = compIcon(item.component_type);
          const isDone = generated.has(item.index);
          const isCurrent = item.index === currentIndex;
          return (
            <div
              key={item.index}
              className={`mb-1 flex items-center gap-2 rounded-lg px-3 py-2 text-xs transition-all ${isCurrent ? 'bg-primary/10 ring-1 ring-primary/20' : isDone ? 'bg-success/5' : 'hover:bg-surface'}`}
            >
              <div className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${isDone ? 'bg-success/15 text-success' : isCurrent ? 'bg-primary/15 text-primary' : 'bg-border/40 text-text-muted'}`}>
                {isDone ? <CheckCircle2 className="h-3 w-3" /> : isCurrent ? <Loader2 className="h-3 w-3 animate-spin" /> : <span className="text-[8px] font-bold">{item.index + 1}</span>}
              </div>
              <div className="min-w-0 flex-1">
                <p className={`truncate font-medium ${isCurrent ? 'text-primary' : isDone ? 'text-success' : 'text-text-muted'}`}>{item.title}</p>
                <p className="flex items-center gap-1 text-[9px] text-text-muted">
                  <Icon className={`h-2.5 w-2.5 ${compColor(item.component_type)}`} />
                  {item.component_type.replace(/_/g, ' ')}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Next Preview Modal ─────────────────────────────────────────────────────

function NextPreviewModal({
  nextItem,
  onProceed,
  onRedo,
  onSkip,
  currentResult,
  generating,
}: {
  nextItem: QueueItem | null;
  onProceed: () => void;
  onRedo: () => void;
  onSkip: () => void;
  currentResult: GeneratedComponent | null;
  generating: boolean;
}) {
  if (!currentResult) return null;
  const Icon = compIcon(currentResult.component_type);

  return (
    <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
      {/* Current result */}
      <div className="mb-4">
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <Icon className={`h-4 w-4 ${compColor(currentResult.component_type)}`} />
          <span className="font-medium uppercase tracking-wide">{currentResult.component_type.replace(/_/g, ' ')}</span>
          <Badge variant="success" className="ml-auto">Generated</Badge>
        </div>
        <h3 className="mt-2 text-sm font-semibold text-text">{currentResult.title}</h3>
        {currentResult.narrative && (
          <p className="mt-2 rounded-lg border border-border bg-white p-3 text-sm leading-relaxed text-slate-600">
            {currentResult.narrative}
          </p>
        )}
      </div>

      {/* Divider */}
      <div className="my-4 border-t border-border" />

      {/* Next preview */}
      {nextItem && (
        <div className="mb-4 rounded-lg border border-border bg-surface p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Next up</p>
          <div className="mt-1.5 flex items-center gap-2">
            {(() => { const NIcon = compIcon(nextItem.component_type); return <NIcon className={`h-4 w-4 ${compColor(nextItem.component_type)}`} />; })()}
            <span className="text-sm font-medium text-text">{nextItem.title}</span>
            <Badge variant="muted" className="ml-auto text-[9px]">{nextItem.component_type.replace(/_/g, ' ')}</Badge>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onRedo} disabled={generating}>
            <RefreshCw className="h-3.5 w-3.5" /> Redo
          </Button>
          <Button variant="outline" size="sm" onClick={onSkip} disabled={generating || !nextItem}>
            <SkipForward className="h-3.5 w-3.5" /> Skip next
          </Button>
        </div>
        <Button size="sm" onClick={onProceed} disabled={generating}>
          {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
          {nextItem ? 'Proceed next' : 'Finish'}
        </Button>
      </div>
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function GenerationWorkspacePage() {
  const params = useParams();
  const templateId = params.templateId as string;
  const signature = params.signature as string;

  const [phase, setPhase] = useState<Phase>('loading');
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [generated, setGenerated] = useState<Set<number>>(new Set());
  const [results, setResults] = useState<GeneratedComponent[]>([]);
  const [currentResult, setCurrentResult] = useState<GeneratedComponent | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  // Load queue on mount
  useEffect(() => {
    generatePhaseApi.getGenerationQueue(templateId, signature)
      .then((q) => { setQueue(q); setPhase('ready'); })
      .catch((err) => { setError(err instanceof Error ? err.message : 'Failed to load queue'); setPhase('error'); });
  }, [templateId, signature]);

  const generateCurrent = async (redo = false) => {
    setGenerating(true);
    setError(null);
    if (!startTime) setStartTime(Date.now());

    try {
      const result = await generatePhaseApi.generateComponent(templateId, signature, {
        index: currentIndex,
        use_llm: true,
        redo,
      });
      const comp: GeneratedComponent = {
        index: result.index,
        component_type: result.component_type,
        title: result.title,
        narrative: result.narrative,
        content: result.content,
      };
      setCurrentResult(comp);
      setResults((prev) => [...prev.filter((r) => r.index !== comp.index), comp]);
      setGenerated((prev) => new Set([...prev, comp.index]));
      setPhase('preview');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const proceedNext = () => {
    const nextIdx = currentIndex + 1;
    if (nextIdx >= queue.length) {
      setPhase('complete');
      // Trigger full assembly
      generatePhaseApi.generate(templateId, signature, { use_llm: true, publish_mode: 'draft' }).catch(() => {});
    } else {
      setCurrentIndex(nextIdx);
      setCurrentResult(null);
      setPhase('ready');
    }
  };

  const skipNext = () => {
    const skipIdx = currentIndex + 2;
    if (skipIdx >= queue.length) {
      proceedNext();
    } else {
      setCurrentIndex(skipIdx);
      setCurrentResult(null);
      setPhase('ready');
    }
  };

  const redoCurrent = () => generateCurrent(true);

  const progress = queue.length > 0 ? Math.round((generated.size / queue.length) * 100) : 0;
  const nextItem = currentIndex + 1 < queue.length ? queue[currentIndex + 1] : null;

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-12">
      <PageHeader
        title="Generation workspace"
        description={`Step-by-step report generation · ${generated.size}/${queue.length} components`}
        actions={<Link href="/report-builder/binding"><Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" /> Binding</Button></Link>}
      />

      {/* Progress bar */}
      <div className="rounded-xl border border-border bg-surface-card px-5 py-3">
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span className="flex items-center gap-2">
            <Zap className="h-3.5 w-3.5 text-primary" />
            {phase === 'complete' ? 'All components generated' : phase === 'generating' ? 'Generating...' : `Component ${currentIndex + 1} of ${queue.length}`}
          </span>
          <span>{progress}%</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border/40">
          <div className="h-full rounded-full bg-primary/60 transition-all duration-700" style={{ width: `${progress}%` }} />
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      {/* Main content: sidebar + canvas */}
      <div className="flex gap-5">
        {/* Queue sidebar */}
        {queue.length > 0 && (
          <QueueSidebar queue={queue} currentIndex={currentIndex} generated={generated} />
        )}

        {/* Main canvas area */}
        <div className="min-w-0 flex-1 space-y-4">
          {/* Loading state */}
          {phase === 'loading' && (
            <div className="flex flex-col items-center py-16"><Loader2 className="h-8 w-8 animate-spin text-primary/40" /><p className="mt-3 text-sm text-text-muted">Loading generation queue...</p></div>
          )}

          {/* Ready: show current component to generate */}
          {phase === 'ready' && queue[currentIndex] && (
            <div className="rounded-2xl border border-border bg-surface-card p-6">
              <div className="flex items-center gap-3">
                {(() => { const Icon = compIcon(queue[currentIndex].component_type); return <div className={`flex h-12 w-12 items-center justify-center rounded-full bg-primary/10`}><Icon className="h-6 w-6 text-primary" /></div>; })()}
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Ready to generate</p>
                  <h2 className="text-lg font-semibold text-text">{queue[currentIndex].title}</h2>
                  <div className="mt-1 flex items-center gap-2 text-xs text-text-muted">
                    <Badge variant="muted">{queue[currentIndex].component_type.replace(/_/g, ' ')}</Badge>
                    {queue[currentIndex].section_path.length > 0 && (
                      <span className="flex items-center gap-1">
                        {queue[currentIndex].section_path.map((s, i) => (
                          <span key={i} className="flex items-center gap-0.5">
                            {i > 0 && <ChevronRight className="h-3 w-3" />}
                            <span>{s}</span>
                          </span>
                        ))}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="mt-6 flex justify-center">
                <Button size="lg" onClick={() => generateCurrent()} disabled={generating}>
                  {generating ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}
                  Generate this component
                </Button>
              </div>
            </div>
          )}

          {/* Generating state */}
          {phase === 'generating' && (
            <div className="flex flex-col items-center py-12">
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
              <p className="mt-4 text-sm font-medium text-text">Generating with Azure GPT-4o...</p>
              <p className="mt-1 text-xs text-text-muted">Running analytics → narrating → rendering</p>
            </div>
          )}

          {/* Preview: show result with actions */}
          {phase === 'preview' && (
            <NextPreviewModal
              nextItem={nextItem}
              onProceed={proceedNext}
              onRedo={redoCurrent}
              onSkip={skipNext}
              currentResult={currentResult}
              generating={generating}
            />
          )}

          {/* Complete state */}
          {phase === 'complete' && (
            <div className="rounded-2xl border border-border bg-surface-card p-6 text-center">
              <CheckCircle2 className="mx-auto h-12 w-12 text-success" />
              <h2 className="mt-4 text-xl font-semibold text-text">Report generation complete</h2>
              <p className="mt-2 text-sm text-text-muted">{generated.size} components generated successfully</p>
              <div className="mt-6 flex flex-wrap justify-center gap-3">
                <a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer">
                  <Button variant="outline"><ExternalLink className="h-4 w-4" /> View HTML</Button>
                </a>
                <a href={generatePhaseApi.reportPdfUrl(templateId, signature)} target="_blank" rel="noreferrer">
                  <Button variant="outline"><Download className="h-4 w-4" /> Download PDF</Button>
                </a>
                <Link href={`/report-builder/preview?tid=${templateId}&sig=${signature}`}>
                  <Button><Pencil className="h-4 w-4" /> Edit & publish</Button>
                </Link>
              </div>
            </div>
          )}

          {/* Generated results trail */}
          {results.length > 0 && phase !== 'complete' && (
            <div ref={canvasRef} className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Generated so far</p>
              {results.map((r) => {
                const Icon = compIcon(r.component_type);
                return (
                  <div key={r.index} className="rounded-lg border border-slate-100 bg-slate-50/50 p-3 text-xs">
                    <div className="flex items-center gap-2">
                      <Icon className={`h-3.5 w-3.5 ${compColor(r.component_type)}`} />
                      <span className="font-medium text-text">{r.title}</span>
                      <CheckCircle2 className="ml-auto h-3.5 w-3.5 text-success" />
                    </div>
                    {r.narrative && <p className="mt-1.5 line-clamp-2 text-slate-500">{r.narrative}</p>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
