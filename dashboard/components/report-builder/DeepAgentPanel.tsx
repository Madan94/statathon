'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Brain, Send, Loader2, CheckCircle2, AlertTriangle, XCircle,
  BarChart3, Table2, Hash, FileText, GripVertical, Sparkles,
  Database, Network, BookOpen, History, Shield, ChevronDown, ChevronRight,
} from 'lucide-react';
import { reportBuilderApi, RenderedBlock } from '@/lib/api';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ContextStatus {
  dataset?: { loaded: boolean; rows: number; columns: number; col_sample: string[] };
  knowledge_graph?: { backend: string; available: boolean; note?: string };
  stm?: { backend: string; available: boolean };
  ltm?: { backend: string; available: boolean };
  rulebooks?: { available: boolean };
  analysis?: {
    semantic_mapped_columns: number;
    clusters: number;
    anomaly_candidates: number;
    imputation_candidates: number;
    has_schema_graph: boolean;
  };
  domains?: Record<string, number>;
}

interface DeepTurn {
  turn_id: string;
  query: string;
  role: 'user' | 'assistant';
  text: string;
  blocks: RenderedBlock[];
  plan?: { intent: string; target_domains: string[]; sub_intents: string[] };
  analytics?: { mode: string; error?: string };
  context_used?: { resolved_columns: string[]; kg_neighbors_count: number };
  verifier?: { overall_status: string } | null;
  error?: string | null;
  created_at: string;
}

interface Props {
  jobId: number;
  onDragBlock?: (block: RenderedBlock) => void;
}

const DRAG_MIME = 'application/x-statathon-block';

// ── Context panel ─────────────────────────────────────────────────────────────

function ContextPanel({ jobId }: { jobId: number }) {
  const [ctx, setCtx] = useState<ContextStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data-loading gate for the per-job context fetch
    setLoading(true);
    fetch(`/api/backend/report-builder/jobs/${jobId}/context`, { credentials: 'include' })
      .then((r) => r.json())
      .then(setCtx)
      .catch(() => setCtx(null))
      .finally(() => setLoading(false));
  }, [jobId]);

  const StatusDot = ({ ok }: { ok: boolean }) => (
    <span className={`inline-block h-2 w-2 rounded-full mr-1.5 ${ok ? 'bg-success' : 'bg-error'}`} />
  );

  if (loading) {
    return (
      <div className="p-3 text-xs text-text-muted flex items-center gap-2">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading context…
      </div>
    );
  }

  const rows = [
    { icon: Database, label: 'Dataset', ok: ctx?.dataset?.loaded ?? false,
      detail: ctx?.dataset ? `${ctx.dataset.rows.toLocaleString()} rows × ${ctx.dataset.columns} cols` : '—' },
    { icon: Network, label: 'Knowledge Graph', ok: ctx?.knowledge_graph?.available ?? false,
      detail: ctx?.knowledge_graph?.backend ?? '—' },
    { icon: Brain, label: 'STM', ok: ctx?.stm?.available ?? false,
      detail: ctx?.stm?.backend ?? '—' },
    { icon: History, label: 'LTM / Qdrant', ok: ctx?.ltm?.available ?? false,
      detail: ctx?.ltm?.backend ?? '—' },
    { icon: BookOpen, label: 'Rulebooks', ok: ctx?.rulebooks?.available ?? false, detail: '—' },
  ];

  const analysis = ctx?.analysis;
  const domains = ctx?.domains ? Object.entries(ctx.domains) : [];

  return (
    <div className="border-b border-border">
      <button
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-text-muted hover:text-text"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-primary" /> Agent Context
        </span>
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {rows.map(({ icon: Icon, label, ok, detail }) => (
            <div key={label} className="flex items-center gap-2 text-xs">
              <StatusDot ok={ok} />
              <Icon className="h-3 w-3 text-text-muted shrink-0" />
              <span className="font-medium text-text w-28 shrink-0">{label}</span>
              <span className="text-text-muted truncate">{detail}</span>
            </div>
          ))}

          {analysis && (
            <div className="mt-2 pt-2 border-t border-border grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <div className="text-text-muted">Mapped columns</div>
              <div className="text-text font-medium">{analysis.semantic_mapped_columns}</div>
              <div className="text-text-muted">Clusters</div>
              <div className="text-text font-medium">{analysis.clusters}</div>
              <div className="text-text-muted">Anomalies</div>
              <div className="text-text font-medium">{analysis.anomaly_candidates}</div>
              <div className="text-text-muted">Imputation targets</div>
              <div className="text-text font-medium">{analysis.imputation_candidates}</div>
            </div>
          )}

          {domains.length > 0 && (
            <div className="mt-2 pt-2 border-t border-border text-xs">
              <p className="text-text-muted mb-1 font-semibold uppercase tracking-wide">Active domains</p>
              <div className="flex flex-wrap gap-1">
                {domains.slice(0, 10).map(([d, n]) => (
                  <span key={d} className="px-1.5 py-0.5 bg-accent/10 text-primary rounded text-[10px]">
                    {d} ({n})
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Block chip (draggable output) ─────────────────────────────────────────────

function BlockChip({
  block,
  onDrag,
}: {
  block: RenderedBlock;
  onDrag?: (block: RenderedBlock) => void;
}) {
  const icons: Record<string, React.ElementType> = {
    narrative: FileText,
    table: Table2,
    chart: BarChart3,
    metric: Hash,
  };
  const Icon = icons[block.kind] ?? FileText;
  const verifier = block.verifier as { overall_status?: string } | null | undefined;
  const vstatus = verifier?.overall_status;

  const handleDragStart = (e: React.DragEvent) => {
    const raw = JSON.stringify({ block, fromCanvas: false });
    e.dataTransfer.setData(DRAG_MIME, raw);
    e.dataTransfer.setData('text/plain', raw);
    e.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      className="flex items-center gap-1.5 px-2 py-1 rounded-lg border border-border bg-surface text-xs cursor-grab hover:border-primary/50 hover:bg-primary/5 transition-colors"
      title="Drag into report canvas"
    >
      <GripVertical className="h-3 w-3 text-text-muted shrink-0" />
      <Icon className="h-3 w-3 text-primary shrink-0" />
      <span className="truncate max-w-[120px] text-text">{block.title || block.kind}</span>
      {vstatus === 'pass' && <CheckCircle2 className="h-3 w-3 text-success shrink-0" />}
      {vstatus === 'warn' && <AlertTriangle className="h-3 w-3 text-warning shrink-0" />}
      {vstatus === 'fail' && <XCircle className="h-3 w-3 text-error shrink-0" />}
    </div>
  );
}

// ── Turn bubble ───────────────────────────────────────────────────────────────

function TurnBubble({ turn, onDrag }: { turn: DeepTurn; onDrag?: (b: RenderedBlock) => void }) {
  const isUser = turn.role === 'user';

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] bg-primary text-white rounded-2xl rounded-br-sm px-3 py-2 text-sm">
          {turn.query || turn.text}
        </div>
      </div>
    );
  }

  const plan = turn.plan;
  const ctx = turn.context_used;

  return (
    <div className="flex flex-col gap-2">
      {/* Intent badge */}
      {plan?.intent && (
        <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
          <Brain className="h-3 w-3 text-primary" />
          <span className="font-semibold text-primary uppercase tracking-wide">{plan.intent}</span>
          {plan.target_domains?.length > 0 && (
            <span>· {plan.target_domains.join(', ')}</span>
          )}
          {ctx?.kg_neighbors_count ? (
            <span>· {ctx.kg_neighbors_count} KG neighbors</span>
          ) : null}
        </div>
      )}

      {/* Narrative text */}
      {turn.text && (
        <div className="bg-surface border border-border rounded-xl px-3 py-2.5 text-sm text-text leading-relaxed">
          {turn.text}
        </div>
      )}

      {/* Error */}
      {turn.error && (
        <div className="text-xs text-error bg-error/10 border border-error/20 rounded-lg px-3 py-2">
          {turn.error}
        </div>
      )}

      {/* Draggable block chips */}
      {turn.blocks && turn.blocks.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] text-text-muted self-center">Drag to report:</span>
          {turn.blocks.map((b) => (
            <BlockChip key={b.block_id} block={b} onDrag={onDrag} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Suggested questions ────────────────────────────────────────────────────────

const SUGGESTIONS = [
  'What are the top anomalies in this dataset?',
  'Show correlation between numeric columns',
  'Summarize missing values by column',
  'Compare groups by key metric',
  'Forecast trends for the next 6 periods',
  'Run statistical significance tests',
  'Which domains have most missing data?',
  'Generate an executive summary narrative',
];

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function DeepAgentPanel({ jobId, onDragBlock }: Props) {
  const [turns, setTurns] = useState<DeepTurn[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns]);

  const submit = useCallback(async (q?: string) => {
    const text = (q ?? query).trim();
    if (!text || loading) return;
    setQuery('');
    setError(null);
    setLoading(true);

    const userTurn: DeepTurn = {
      turn_id: Math.random().toString(36).slice(2),
      query: text,
      role: 'user',
      text,
      blocks: [],
      created_at: new Date().toISOString(),
    };
    setTurns((prev) => [...prev, userTurn]);

    try {
      const res = await fetch(`/api/backend/report-builder/jobs/${jobId}/deep-chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'DeepAgent error');
      }
      const data = await res.json();
      const assistantTurn: DeepTurn = {
        ...data,
        query: text,
        role: 'assistant',
        text: data.text || '',
        blocks: data.blocks || [],
      };
      setTurns((prev) => [...prev, assistantTurn]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'DeepAgent failed';
      setError(msg);
      setTurns((prev) => [
        ...prev,
        {
          turn_id: 'err',
          query: text,
          role: 'assistant',
          text: '',
          blocks: [],
          error: msg,
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [jobId, query, loading]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-surface-card rounded-xl border border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-surface shrink-0">
        <Brain className="h-4 w-4 text-primary" />
        <div>
          <p className="text-sm font-semibold text-text">DeepAgent BI</p>
          <p className="text-[10px] text-text-muted">
            Planner → Retrieval → Analytics → Scribe → Verifier
          </p>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Shield className="h-3.5 w-3.5 text-success" />
          <span className="text-[10px] text-text-muted">Verified</span>
        </div>
      </div>

      {/* Context panel */}
      <ContextPanel jobId={jobId} />

      {/* Chat area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
        {turns.length === 0 && (
          <div className="space-y-3">
            <p className="text-xs text-text-muted text-center">
              Ask any analytical question. The DeepAgent will plan, retrieve, analyse and verify
              before responding.
            </p>
            <div className="grid grid-cols-1 gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="text-left text-xs px-3 py-2 rounded-lg border border-border hover:border-primary/40 hover:bg-primary/5 text-text-muted hover:text-text transition-colors"
                  onClick={() => submit(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn) => (
          <TurnBubble key={turn.turn_id} turn={turn} onDrag={onDragBlock} />
        ))}

        {loading && (
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
            <span>Planning → Retrieving → Analysing → Writing → Verifying…</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="shrink-0 px-4 pb-4 pt-2 border-t border-border">
        {error && (
          <p className="text-xs text-error mb-2">{error}</p>
        )}
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            className="flex-1 resize-none rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-primary/30 min-h-[40px] max-h-[120px]"
            placeholder="Ask anything about the data…"
            value={query}
            rows={1}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          <button
            onClick={() => submit()}
            disabled={loading || !query.trim()}
            className="h-10 w-10 shrink-0 rounded-xl bg-primary text-white flex items-center justify-center hover:bg-primary/90 disabled:opacity-40 transition-colors"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
        <p className="text-[10px] text-text-muted mt-1.5 text-center">
          Enter to send · Shift+Enter for new line · Drag chips into report
        </p>
      </div>
    </div>
  );
}
