'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, ArrowRight, BarChart3, CheckCircle2, Download, ExternalLink, FileText, FunctionSquare, Loader2, MessageSquare, Pencil, Play, RefreshCw, SkipForward, Sparkles, Table2, Zap } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { ReportDocumentCanvas, type DocBlock } from '@/components/report-builder/render/ReportDocumentCanvas';
import { generatePhaseApi } from '@/lib/api';

interface QueueItem { index: number; plan_id: string; question_id: string; component_type: string; title: string; section_path: string[]; status: string; }
type Phase = 'loading' | 'ready' | 'generating' | 'preview' | 'complete' | 'error';

function compIcon(kind: string) {
  if (kind === 'chart' || kind === 'figure') return BarChart3;
  if (kind === 'table') return Table2;
  if (kind === 'formula_metric' || kind === 'metric') return FunctionSquare;
  if (kind === 'narrative' || kind === 'key_finding' || kind === 'heading') return FileText;
  return MessageSquare;
}

export default function GenerationWorkspacePage() {
  const params = useParams();
  const templateId = params.templateId as string;
  const signature = params.signature as string;

  const [phase, setPhase] = useState<Phase>('loading');
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [generated, setGenerated] = useState<Set<number>>(new Set());
  const [blocks, setBlocks] = useState<DocBlock[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLog, setStatusLog] = useState<string[]>([]);

  const addLog = useCallback((msg: string) => setStatusLog((prev) => [...prev.slice(-8), msg]), []);

  useEffect(() => {
    addLog('Loading generation queue...');
    generatePhaseApi.getGenerationQueue(templateId, signature)
      .then((q) => {
        setQueue(q);
        // Initialize blocks from queue
        setBlocks(q.map((item) => ({
          id: `block-${item.index}`,
          kind: (item.component_type === 'formula_metric' ? 'metric' : item.component_type) as DocBlock['kind'],
          content: '',
          title: item.title,
          status: 'pending' as const,
          planId: item.plan_id,
          componentIndex: item.index,
          level: item.section_path.length <= 1 ? 2 : 3,
        })));
        setPhase('ready');
        addLog(`Queue loaded: ${q.length} components to generate`);
      })
      .catch((err) => { setError(err instanceof Error ? err.message : 'Failed to load queue'); setPhase('error'); });
  }, [templateId, signature, addLog]);

  const generateCurrent = async (redo = false) => {
    if (currentIndex >= queue.length) return;
    setGenerating(true);
    setPhase('generating');
    setError(null);

    const item = queue[currentIndex];
    addLog(`Generating: ${item.title} (${item.component_type})...`);

    // Mark block as generating
    setBlocks((prev) => prev.map((b) => b.componentIndex === currentIndex ? { ...b, status: 'generating' as const } : b));

    try {
      const result = await generatePhaseApi.generateComponent(templateId, signature, {
        index: currentIndex,
        use_llm: true,
        redo,
      });

      addLog(`✓ Generated: ${result.title} (${result.component_type})`);
      if (result.narrative) addLog(`  Narrative: "${result.narrative.slice(0, 80)}..."`);

      // Update block with generated content
      setBlocks((prev) => prev.map((b) => b.componentIndex === currentIndex ? {
        ...b,
        content: result.narrative || String(result.content?.text || result.content?.content || result.content?.value || ''),
        title: result.title,
        kind: (result.component_type === 'formula_metric' ? 'metric' : result.component_type) as DocBlock['kind'],
        metricValue: result.content?.value ? String(result.content.value) : undefined,
        metricUnit: result.content?.unit ? String(result.content.unit) : undefined,
        status: 'done' as const,
      } : b));

      setGenerated((prev) => new Set([...prev, currentIndex]));
      setPhase('preview');
    } catch (err) {
      addLog(`✗ Error: ${err instanceof Error ? err.message : 'Failed'}`);
      setBlocks((prev) => prev.map((b) => b.componentIndex === currentIndex ? { ...b, status: 'error' as const } : b));
      setError(err instanceof Error ? err.message : 'Generation failed');
      setPhase('preview'); // still show controls
    } finally {
      setGenerating(false);
    }
  };

  const proceedNext = () => {
    const nextIdx = currentIndex + 1;
    if (nextIdx >= queue.length) {
      setPhase('complete');
      addLog('All components generated. Assembling final report...');
      generatePhaseApi.generate(templateId, signature, { use_llm: true, publish_mode: 'draft' })
        .then(() => addLog('✓ Final report assembled'))
        .catch(() => addLog('⚠ Assembly skipped'));
    } else {
      setCurrentIndex(nextIdx);
      setPhase('ready');
    }
  };

  const skipNext = () => { setCurrentIndex((i) => Math.min(i + 2, queue.length - 1)); setPhase('ready'); };
  const redoCurrent = () => generateCurrent(true);

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

  const progress = queue.length > 0 ? Math.round((generated.size / queue.length) * 100) : 0;
  const currentItem = queue[currentIndex];
  const nextItem = currentIndex + 1 < queue.length ? queue[currentIndex + 1] : null;

  return (
    <div className="mx-auto max-w-7xl space-y-5 pb-12">
      <PageHeader
        title="Report generation"
        description={`${generated.size}/${queue.length} components · ${templateId}`}
        actions={<Link href="/report-builder/binding"><Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" /> Binding</Button></Link>}
      />

      {/* Top bar: progress + controls */}
      <div className="rounded-xl border border-border bg-surface-card">
        {/* Progress */}
        <div className="px-5 py-3">
          <div className="flex items-center justify-between text-xs text-text-muted">
            <span className="flex items-center gap-2">
              {phase === 'generating' ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : phase === 'complete' ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <Zap className="h-3.5 w-3.5 text-primary" />}
              {phase === 'complete' ? 'All components generated' : phase === 'generating' ? `Generating ${currentItem?.title || ''}...` : `Component ${currentIndex + 1} of ${queue.length}`}
            </span>
            <span className="font-mono">{progress}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border/30">
            <div className="h-full rounded-full bg-primary/50 transition-all duration-700" style={{ width: `${progress}%` }} />
          </div>
        </div>

        {/* Action bar */}
        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-2.5">
          {/* Left: current component info */}
          <div className="flex items-center gap-2 text-xs">
            {currentItem && (() => { const Icon = compIcon(currentItem.component_type); return <Icon className="h-4 w-4 text-text-muted" />; })()}
            <span className="font-medium text-text">{currentItem?.title || 'Ready'}</span>
            {currentItem && <Badge variant="muted" className="text-[9px]">{currentItem.component_type.replace(/_/g, ' ')}</Badge>}
          </div>

          {/* Right: action buttons */}
          <div className="flex items-center gap-2">
            {phase === 'ready' && (
              <Button size="sm" onClick={() => generateCurrent()} disabled={generating}>
                <Sparkles className="h-3.5 w-3.5" /> Generate
              </Button>
            )}
            {phase === 'preview' && (
              <>
                <Button variant="outline" size="sm" onClick={redoCurrent} disabled={generating}><RefreshCw className="h-3.5 w-3.5" /> Redo</Button>
                {nextItem && <Button variant="outline" size="sm" onClick={skipNext} disabled={generating}><SkipForward className="h-3.5 w-3.5" /> Skip</Button>}
                <Button size="sm" onClick={proceedNext} disabled={generating}><ArrowRight className="h-3.5 w-3.5" /> {nextItem ? 'Next' : 'Finish'}</Button>
              </>
            )}
            {phase === 'complete' && (
              <>
                <a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><ExternalLink className="h-3.5 w-3.5" /> HTML</Button></a>
                <a href={generatePhaseApi.reportPdfUrl(templateId, signature)} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><Download className="h-3.5 w-3.5" /> PDF</Button></a>
                <Link href={`/report-builder/preview?tid=${templateId}&sig=${signature}`}><Button size="sm"><Pencil className="h-3.5 w-3.5" /> Edit</Button></Link>
              </>
            )}
          </div>
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      {/* Main area: document canvas + activity log */}
      <div className="flex gap-5">
        {/* Document canvas */}
        <div className="min-w-0 flex-1">
          {phase === 'loading' ? (
            <div className="flex flex-col items-center py-20"><Loader2 className="h-8 w-8 animate-spin text-primary/30" /><p className="mt-3 text-sm text-text-muted">Loading...</p></div>
          ) : (
            <ReportDocumentCanvas
              blocks={blocks}
              onUpdateBlock={updateBlock}
              onReorderBlock={reorderBlock}
              onDeleteBlock={deleteBlock}
              onInsertBlock={insertBlock}
              readOnly={phase === 'generating'}
            />
          )}
        </div>

        {/* Activity log sidebar */}
        <div className="hidden w-64 shrink-0 xl:block">
          <div className="sticky top-4 rounded-xl border border-border bg-surface-card">
            <div className="border-b border-border px-4 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Activity log</p>
            </div>
            <div className="max-h-[50vh] overflow-auto p-3">
              {statusLog.map((msg, i) => (
                <p key={i} className="mb-1.5 text-[10px] leading-relaxed text-text-muted">
                  {msg.startsWith('✓') ? <span className="text-success">{msg}</span> : msg.startsWith('✗') ? <span className="text-danger">{msg}</span> : msg.startsWith('⚠') ? <span className="text-warning">{msg}</span> : msg}
                </p>
              ))}
              {statusLog.length === 0 && <p className="text-[10px] text-text-muted">Waiting to start...</p>}
            </div>

            {/* Queue mini-list */}
            <div className="border-t border-border px-4 py-3">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-text-muted">Queue</p>
              {queue.slice(Math.max(0, currentIndex - 1), currentIndex + 4).map((item) => (
                <div key={item.index} className={`mb-1 flex items-center gap-1.5 text-[10px] ${item.index === currentIndex ? 'font-medium text-primary' : generated.has(item.index) ? 'text-success' : 'text-text-muted'}`}>
                  {generated.has(item.index) ? <CheckCircle2 className="h-2.5 w-2.5" /> : item.index === currentIndex && generating ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <span className="h-2.5 w-2.5 text-center text-[8px]">{item.index + 1}</span>}
                  <span className="truncate">{item.title}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
