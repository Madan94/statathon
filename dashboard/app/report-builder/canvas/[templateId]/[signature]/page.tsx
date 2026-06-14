'use client';

/**
 * Report Canvas — the full generation + BI workspace.
 *
 * Route: /report-builder/canvas/[templateId]/[signature]
 * Entry: from S3.5 handoff button OR standalone binder selector.
 *
 * Layout: [A4 Document Canvas (left)] + [Deep BI Chat (right sidebar)]
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, BarChart3, BookOpen, CheckCircle2, ChevronRight, Clock,
  Download, ExternalLink, FileText, Layers, Loader2, MessageSquare,
  Pause, Pencil, Play, RefreshCw, Settings, Sparkles, StopCircle, Zap,
} from 'lucide-react';

import { ReportDocumentCanvas, type DocBlock } from '@/components/report-builder/render/ReportDocumentCanvas';
import { generatePhaseApi } from '@/lib/api';

/* ═══════════════════════════════════════════════════════════════════════════
   TYPES
   ═══════════════════════════════════════════════════════════════════════════ */

interface QueueItem {
  index: number; plan_id: string; question_id: string;
  component_type: string; title: string; section_path: string[]; status: string;
}

interface ChatMessage {
  id: string;
  role: 'system' | 'assistant' | 'user';
  content: string;
  componentIndex?: number;
  timestamp: number;
  status?: 'thinking' | 'done' | 'error';
  tool?: string;
  toolResult?: Record<string, unknown>;
}

type Phase = 'init' | 'ready' | 'generating' | 'paused' | 'complete';

/* ═══════════════════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════════════════ */

function fmtTime(ms: number) { return ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`; }

function sectionFromPath(path: string[]) {
  if (!path || !path.length) return '';
  return path[path.length - 1];
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════════════════════════════════════════ */

export default function ReportCanvasPage() {
  const params = useParams();
  const templateId = params.templateId as string;
  const signature = params.signature as string;

  // Core state
  const [phase, setPhase] = useState<Phase>('init');
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [blocks, setBlocks] = useState<DocBlock[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [generated, setGenerated] = useState<Set<number>>(new Set());
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatOpen, setChatOpen] = useState(true);

  // Timing
  const [genTimes, setGenTimes] = useState<Map<number, number>>(new Map());
  const abortRef = useRef(false);

  // ─── Add chat message ──────────────────────────────────────────────
  const addChat = useCallback((msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    setChatMessages(prev => [...prev, { ...msg, id: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`, timestamp: Date.now() }]);
  }, []);

  // ─── Load queue ────────────────────────────────────────────────────
  useEffect(() => {
    addChat({ role: 'system', content: `Loading generation queue for ${templateId}...`, status: 'thinking' });

    generatePhaseApi.getGenerationQueue(templateId, signature)
      .then((q) => {
        setQueue(q);
        // Build initial blocks with section hierarchy
        const initialBlocks: DocBlock[] = [];
        let lastPath = '';
        (q || []).forEach((item) => {
          const path = (item.section_path || []).join(' › ');
          if (path && path !== lastPath) {
            // Determine heading level from path depth
            const depth = (item.section_path || []).length;
            initialBlocks.push({
              id: `heading-${item.index}`,
              kind: 'heading',
              content: sectionFromPath(item.section_path),
              title: path,
              status: 'done',
              level: depth <= 1 ? 1 : depth <= 2 ? 2 : 3,
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
          });
        });
        setBlocks(initialBlocks);
        setPhase('ready');
        addChat({ role: 'system', content: `Queue loaded: ${q.length} components across ${new Set(q.map(i => (i.section_path||[]).join('/'))).size} sections. Ready to generate.`, status: 'done' });
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load queue');
        addChat({ role: 'system', content: `Error: ${err instanceof Error ? err.message : 'Failed'}`, status: 'error' });
      });
  }, [templateId, signature, addChat]);

  // ─── Generate single component ────────────────────────────────────
  const generateOne = useCallback(async (idx: number): Promise<boolean> => {
    if (idx >= queue.length) return false;
    const item = queue[idx];
    const t0 = Date.now();

    addChat({ role: 'assistant', content: `Generating: **${item.title}** (${item.component_type})`, componentIndex: idx, status: 'thinking', tool: 'generate_component' });
    setBlocks(prev => prev.map(b => b.componentIndex === idx ? { ...b, status: 'generating' } : b));

    try {
      const result = await generatePhaseApi.generateComponent(templateId, signature, { index: idx, use_llm: true, redo: false });
      const elapsed = Date.now() - t0;
      setGenTimes(prev => new Map([...prev, [idx, elapsed]]));

      // Update block
      const contentObj = result.content || {};
      setBlocks(prev => prev.map(b => b.componentIndex === idx ? {
        ...b,
        content: result.narrative || String(contentObj.text || contentObj.content || contentObj.value || ''),
        title: result.title,
        kind: (result.component_type === 'formula_metric' ? 'metric' : result.component_type) as DocBlock['kind'],
        metricValue: contentObj.value != null ? String(contentObj.value) : undefined,
        metricUnit: contentObj.unit ? String(contentObj.unit) : undefined,
        tableData: (contentObj.items || contentObj.rankingData || contentObj.rows || contentObj.aggregationData) ? contentObj as Record<string, unknown> : undefined,
        status: 'done',
      } : b));

      setGenerated(prev => new Set([...prev, idx]));
      addChat({
        role: 'assistant',
        content: `✓ **${result.title}** generated in ${fmtTime(elapsed)}${result.narrative ? `\n\n> ${result.narrative.slice(0, 150)}${result.narrative.length > 150 ? '...' : ''}` : ''}`,
        componentIndex: idx,
        status: 'done',
      });
      return true;
    } catch (err) {
      setBlocks(prev => prev.map(b => b.componentIndex === idx ? { ...b, status: 'error' } : b));
      addChat({ role: 'assistant', content: `✗ Failed: ${err instanceof Error ? err.message : 'Unknown error'}`, componentIndex: idx, status: 'error' });
      return false;
    }
  }, [queue, templateId, signature, addChat]);

  // ─── Auto-generate all ─────────────────────────────────────────────
  const autoGenerateAll = useCallback(async () => {
    setPhase('generating');
    setGenerating(true);
    abortRef.current = false;
    addChat({ role: 'system', content: `Starting auto-generation of ${queue.length - generated.size} remaining components...` });

    for (let i = currentIndex; i < queue.length; i++) {
      if (abortRef.current) { setPhase('paused'); break; }
      if (generated.has(i)) continue;
      setCurrentIndex(i);
      await generateOne(i);
    }

    setGenerating(false);
    if (!abortRef.current) {
      setPhase('complete');
      addChat({ role: 'system', content: '✓ All components generated. Report ready for review.' });
      // Trigger full assembly
      generatePhaseApi.generate(templateId, signature, { use_llm: true, publish_mode: 'draft' }).catch(() => {});
    }
  }, [queue, currentIndex, generated, generateOne, templateId, signature, addChat]);

  const pauseGeneration = () => { abortRef.current = true; };

  // ─── Single step generate ──────────────────────────────────────────
  const generateNext = useCallback(async () => {
    const next = queue.findIndex((_, i) => !generated.has(i) && i >= currentIndex);
    if (next < 0) return;
    setGenerating(true);
    setCurrentIndex(next);
    await generateOne(next);
    setGenerating(false);
    setCurrentIndex(next + 1);
  }, [queue, currentIndex, generated, generateOne]);

  // ─── Chat submit ───────────────────────────────────────────────────
  const handleChatSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    const msg = chatInput.trim();
    setChatInput('');
    addChat({ role: 'user', content: msg });

    // For now, echo — agent function calling will replace this
    setTimeout(() => {
      addChat({ role: 'assistant', content: `I understand you want: "${msg}". Agent function calling will be connected to the backend Deep BI agent for real modifications. For now, use the canvas controls directly.`, status: 'done' });
    }, 500);
  }, [chatInput, addChat]);

  // ─── Block CRUD ────────────────────────────────────────────────────
  const updateBlock = (id: string, u: Partial<DocBlock>) => setBlocks(prev => prev.map(b => b.id === id ? { ...b, ...u } : b));
  const reorderBlock = (id: string, dir: 'up' | 'down') => setBlocks(prev => {
    const i = prev.findIndex(b => b.id === id); if (i < 0) return prev;
    const t = dir === 'up' ? i - 1 : i + 1; if (t < 0 || t >= prev.length) return prev;
    const n = [...prev]; [n[i], n[t]] = [n[t], n[i]]; return n;
  });
  const deleteBlock = (id: string) => setBlocks(prev => prev.filter(b => b.id !== id));
  const insertBlock = (afterId: string, kind: DocBlock['kind']) => setBlocks(prev => {
    const i = prev.findIndex(b => b.id === afterId);
    const nb: DocBlock = { id: `custom-${Date.now()}`, kind, content: '', status: 'done', level: kind === 'heading' ? 3 : undefined };
    const n = [...prev]; n.splice(i + 1, 0, nb); return n;
  });

  // ─── Computed ──────────────────────────────────────────────────────
  const progress = queue.length > 0 ? Math.round((generated.size / queue.length) * 100) : 0;

  // ─── RENDER ────────────────────────────────────────────────────────
  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* ═══ LEFT: Canvas area ═══ */}
      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        {/* Top toolbar */}
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2">
          <div className="flex items-center gap-3">
            <Link href="/report-builder/binding" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold text-slate-800">
                {templateId.replace(/^tpl_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
              </h1>
              <p className="text-[10px] text-slate-400">{signature.slice(0, 8)} · {generated.size}/{queue.length} components</p>
            </div>
          </div>

          {/* Generation controls */}
          <div className="flex items-center gap-2">
            {/* Progress */}
            <div className="flex items-center gap-2 text-[10px] text-slate-400">
              <div className="h-1 w-16 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-emerald-400 transition-all duration-500" style={{ width: `${progress}%` }} />
              </div>
              <span className="tabular-nums">{progress}%</span>
            </div>

            {phase === 'ready' && (
              <>
                <button onClick={generateNext} disabled={generating} className="flex items-center gap-1.5 rounded-md bg-slate-100 px-3 py-1.5 text-[11px] font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50">
                  <Sparkles className="h-3 w-3" /> Generate next
                </button>
                <button onClick={autoGenerateAll} disabled={generating} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                  <Play className="h-3 w-3" /> Auto-generate all
                </button>
              </>
            )}
            {phase === 'generating' && (
              <button onClick={pauseGeneration} className="flex items-center gap-1.5 rounded-md bg-amber-100 px-3 py-1.5 text-[11px] font-medium text-amber-700 hover:bg-amber-200">
                <Pause className="h-3 w-3" /> Pause
              </button>
            )}
            {phase === 'paused' && (
              <button onClick={autoGenerateAll} className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700">
                <Play className="h-3 w-3" /> Resume
              </button>
            )}
            {phase === 'complete' && (
              <div className="flex items-center gap-2">
                <a href={generatePhaseApi.reportHtmlUrl(templateId, signature)} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-md bg-slate-100 px-2.5 py-1.5 text-[11px] font-medium text-slate-600 hover:bg-slate-200">
                  <ExternalLink className="h-3 w-3" /> HTML
                </a>
                <a href={generatePhaseApi.reportPdfUrl(templateId, signature)} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-md bg-slate-100 px-2.5 py-1.5 text-[11px] font-medium text-slate-600 hover:bg-slate-200">
                  <Download className="h-3 w-3" /> PDF
                </a>
              </div>
            )}

            {/* Toggle chat */}
            <button onClick={() => setChatOpen(o => !o)} className={`rounded-md p-1.5 transition-colors ${chatOpen ? 'bg-blue-50 text-blue-600' : 'text-slate-400 hover:bg-slate-100'}`}>
              <MessageSquare className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Canvas scroll area */}
        <div className="flex-1 overflow-auto bg-slate-100/50 p-6">
          {phase === 'init' ? (
            <div className="flex flex-col items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-slate-300" />
              <p className="mt-3 text-sm text-slate-400">Loading report canvas...</p>
            </div>
          ) : (
            <ReportDocumentCanvas
              blocks={blocks}
              onUpdateBlock={updateBlock}
              onReorderBlock={reorderBlock}
              onDeleteBlock={deleteBlock}
              onInsertBlock={insertBlock}
              readOnly={generating}
              reportTitle={templateId.replace(/^tpl_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
              reportSubtitle={`Generated from dataset ${signature.slice(0, 8)} · ${queue.length} components`}
            />
          )}
        </div>
      </div>

      {/* ═══ RIGHT: Deep BI Chat sidebar ═══ */}
      {chatOpen && (
        <div className="flex w-80 flex-col border-l border-slate-200 bg-white xl:w-96">
          {/* Chat header */}
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-blue-500 to-indigo-600">
                <Sparkles className="h-3 w-3 text-white" />
              </div>
              <span className="text-xs font-semibold text-slate-700">Deep BI Agent</span>
            </div>
            <div className="flex items-center gap-1 text-[9px] text-slate-400">
              <span className="flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span>Active</span>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-auto px-3 py-3 space-y-3">
            {chatMessages.map((msg) => (
              <div key={msg.id} className={`${msg.role === 'user' ? 'ml-6' : ''}`}>
                {msg.role === 'user' ? (
                  <div className="rounded-lg bg-blue-600 px-3 py-2 text-[11px] text-white">
                    {msg.content}
                  </div>
                ) : msg.role === 'system' ? (
                  <div className="flex items-start gap-2 text-[10px] text-slate-400">
                    {msg.status === 'thinking' && <Loader2 className="mt-0.5 h-3 w-3 animate-spin shrink-0" />}
                    {msg.status === 'done' && <CheckCircle2 className="mt-0.5 h-3 w-3 text-emerald-400 shrink-0" />}
                    {msg.status === 'error' && <span className="mt-0.5 h-3 w-3 text-red-400 shrink-0">✗</span>}
                    <span>{msg.content}</span>
                  </div>
                ) : (
                  <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                    <div className="text-[11px] leading-relaxed text-slate-700 whitespace-pre-wrap">
                      {msg.content.split('**').map((part, i) =>
                        i % 2 === 0 ? part : <strong key={i} className="font-semibold">{part}</strong>
                      )}
                    </div>
                    {msg.status === 'thinking' && (
                      <div className="mt-2 flex items-center gap-1.5 text-[9px] text-blue-500">
                        <Loader2 className="h-2.5 w-2.5 animate-spin" /> Working...
                      </div>
                    )}
                    {msg.componentIndex != null && msg.status === 'done' && (
                      <div className="mt-2 flex gap-1">
                        <button className="rounded bg-slate-100 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-200">Inspect</button>
                        <button className="rounded bg-slate-100 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-200">Modify</button>
                        <button className="rounded bg-slate-100 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-200">Regenerate</button>
                      </div>
                    )}
                  </div>
                )}
                <p className="mt-0.5 text-[8px] text-slate-300">
                  {new Date(msg.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                </p>
              </div>
            ))}
          </div>

          {/* Chat input */}
          <form onSubmit={handleChatSubmit} className="border-t border-slate-100 p-3">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <input
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                placeholder="Ask about any component, or give instructions..."
                className="flex-1 bg-transparent text-[11px] text-slate-700 placeholder:text-slate-400 outline-none"
              />
              <button type="submit" disabled={!chatInput.trim()} className="rounded bg-blue-600 px-2 py-1 text-[9px] font-medium text-white disabled:opacity-30 hover:bg-blue-700">
                Send
              </button>
            </div>
            <div className="mt-1.5 flex gap-1.5 text-[8px] text-slate-400">
              <span className="rounded bg-slate-100 px-1.5 py-0.5">Ctrl+Enter to send</span>
              <span className="rounded bg-slate-100 px-1.5 py-0.5">/ for commands</span>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
