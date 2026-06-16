'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Sparkles, X, Loader2, Lock, Search, ChevronRight, ChevronDown, Play, AlertTriangle, Wand2 } from 'lucide-react';
import type { PageBlock } from '../engine/useCanvasState';
import type { ChatMessage } from '../engine/useCanvasAgent';
import type { Suggestion } from '../engine/assistantOrchestrator';

/* ═══════════════════════════════════════════════════════════════════
   RightPanel — MoSPI Intelligence Co-Pilot (S4).
   Context-aware: a proactive "Suggested for you" rail (from the S3
   brain), rich result cards, officer-language input, live agent chat.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  selectedBlock: PageBlock | null;
  messages: ChatMessage[];
  busy: boolean;
  onSend: (msg: string) => void;
  onClose: () => void;
  onRegenerate?: (index: number) => void;
  onInsert?: (text: string) => void;
  /** Proactive suggestions from the orchestrator (S3 ③ / S4 rail). */
  suggestions?: Suggestion[];
}

/** Minimal markdown: **bold**, lines, and `> ` blockquotes. */
function renderRich(content: string) {
  return content.split('\n').map((line, i) => {
    const quote = line.startsWith('> ');
    const body = quote ? line.slice(2) : line;
    const parts = body.split(/(\*\*[^*]+\*\*)/g).map((seg, j) =>
      seg.startsWith('**') && seg.endsWith('**')
        ? <strong key={j} className="font-semibold">{seg.slice(2, -2)}</strong>
        : <span key={j}>{seg}</span>
    );
    return (
      <p key={i} className={quote ? 'border-l-2 border-slate-300 pl-2 italic text-slate-500' : ''}>
        {parts.length ? parts : '\u00A0'}
      </p>
    );
  });
}

/** Collapsible 'Show data' — the top result rows an answer is based on. */
function ResultRows({ table }: { table: { columns: string[]; rows: Array<Record<string, unknown>> } }) {
  const [open, setOpen] = useState(false);
  const cols = table.columns.length ? table.columns : Object.keys(table.rows[0] || {});
  return (
    <div className="pt-0.5">
      <button onClick={() => setOpen(o => !o)} className="inline-flex items-center gap-0.5 text-[8px] font-medium text-blue-600 hover:text-blue-800">
        {open ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
        {open ? 'Hide data' : `Show data (${table.rows.length})`}
      </button>
      {open && (
        <div className="mt-1 overflow-auto rounded border border-slate-200 bg-white">
          <table className="w-full text-[8px]">
            <thead className="bg-slate-50 text-slate-500">
              <tr>{cols.slice(0, 5).map(c => <th key={c} className="px-1.5 py-0.5 text-left font-semibold">{c}</th>)}</tr>
            </thead>
            <tbody>
              {table.rows.slice(0, 8).map((row, ri) => (
                <tr key={ri} className="border-t border-slate-100">
                  {cols.slice(0, 5).map(c => <td key={c} className="px-1.5 py-0.5 text-slate-600">{String(row[c] ?? '')}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function RightPanel({ selectedBlock, messages, busy, onSend, onClose, onRegenerate, onInsert, suggestions = [] }: Props) {
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const submit = (msg: string) => {
    if (!msg.trim() || busy) return;
    onSend(msg);
    setInput('');
  };

  return (
    <div className="w-80 shrink-0 border-l border-slate-200 bg-white flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-gradient-to-br from-blue-500 to-indigo-600">
            <Sparkles className="h-2.5 w-2.5 text-white" />
          </div>
          <span className="text-[11px] font-semibold text-slate-700">MoSPI Intelligence Assistant</span>
        </div>
        <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100"><X className="h-3.5 w-3.5" /></button>
      </div>

      {/* Context card */}
      {selectedBlock && selectedBlock.status === 'done' && (
        <div className="border-b border-slate-100 bg-slate-50/50 p-3">
          <p className="text-[9px] font-bold uppercase tracking-wide text-slate-400">Selected: {selectedBlock.kind}</p>
          <p className="mt-1 truncate text-[11px] font-medium text-slate-700">{selectedBlock.title}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            <button onClick={() => onRegenerate?.(selectedBlock.index)} className="rounded bg-white border border-slate-200 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-50">Regenerate</button>
            <button onClick={() => submit(`inspect ${selectedBlock.index}`)} className="rounded bg-white border border-slate-200 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-50">Explain data</button>
            {selectedBlock.kind === 'narrative' && <button onClick={() => submit(`shorter ${selectedBlock.index}`)} className="rounded bg-white border border-slate-200 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-50">Make shorter</button>}
          </div>
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-3 space-y-2">
        {messages.map(m => (
          <div key={m.id} className={m.role === 'user' ? 'ml-8' : ''}>
            <div className={`rounded-lg px-3 py-2 text-[11px] leading-relaxed space-y-1 ${
              m.role === 'user' ? 'bg-blue-600 text-white'
              : m.role === 'system' ? 'bg-slate-50 text-slate-500 border border-slate-100'
              : 'bg-slate-100 text-slate-700'}`}>
              {/* Bound / exploratory trust badge (deep_bi answers only) */}
              {m.tool === 'deep_bi' && m.bound !== undefined && (
                m.bound ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-1.5 py-0.5 text-[8px] font-semibold text-emerald-700">
                    <Lock className="h-2.5 w-2.5" /> Bound · confirmed binding
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-1.5 py-0.5 text-[8px] font-semibold text-amber-700">
                    <Search className="h-2.5 w-2.5" /> Exploratory · not confirmed
                  </span>
                )
              )}
              {renderRich(m.content)}
              {/* Provenance footer (decision B): columns + rows scanned */}
              {m.provenance && (m.provenance.columns.length > 0 || m.provenance.rows > 0) && (
                <p className="pt-0.5 text-[8px] text-slate-400">
                  {m.provenance.columns.length > 0 && (
                    <>Resolved: <span className="font-mono text-slate-500">{m.provenance.columns.slice(0, 3).join(', ')}</span>{m.provenance.columns.length > 3 ? ` +${m.provenance.columns.length - 3}` : ''} · </>
                  )}
                  {m.provenance.rows > 0 && <>{m.provenance.rows.toLocaleString()} rows</>}
                </p>
              )}
              {/* Collapsible result rows the answer is based on */}
              {m.resultTable && m.resultTable.rows.length > 0 && <ResultRows table={m.resultTable} />}
              {m.tool && <p className="pt-0.5 text-[8px] uppercase tracking-wide text-slate-400">via {m.tool}</p>}
              {/* Exploratory answers offer a deep-link back to the binder */}
              {m.tool === 'deep_bi' && m.bound === false && (
                <p className="text-[8px] text-amber-600">
                  ⚠ This used an unconfirmed column.{' '}
                  <Link href="/report-builder/binding" className="underline hover:text-amber-800">Bind it ▸</Link>
                </p>
              )}
              {m.insertText && onInsert && (
                <button
                  onClick={() => onInsert(m.insertText!)}
                  className="mt-1 rounded bg-blue-600 px-2 py-0.5 text-[9px] font-medium text-white hover:bg-blue-700"
                >
                  + Insert into report
                </button>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 px-3 py-2 text-[10px] text-slate-400">
            <Loader2 className="h-3 w-3 animate-spin" /> Thinking…
          </div>
        )}
        {messages.length === 0 && !busy && (
          <div className="py-6 text-center text-[10px] text-slate-400">
            <Sparkles className="mx-auto h-5 w-5 text-slate-200 mb-2" />
            <p className="font-medium text-slate-500">Your report co-pilot</p>
            <p className="mt-0.5">Ask in plain words — or pick a suggestion below.</p>
          </div>
        )}
      </div>

      {/* Proactive "Suggested for you" rail (S3 ③ / S4) */}
      {suggestions.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/60 px-3 py-2">
          <p className="mb-1.5 flex items-center gap-1 text-[8px] font-bold uppercase tracking-wide text-slate-400">
            <Sparkles className="h-2.5 w-2.5 text-indigo-400" /> Suggested for you
          </p>
          <div className="flex flex-col gap-1">
            {suggestions.map(s => (
              <button
                key={s.id}
                onClick={() => onSend(s.command)}
                className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-left text-[10px] font-medium transition-colors ${
                  s.kind === 'generate' ? 'border-blue-100 bg-blue-50/60 text-blue-700 hover:bg-blue-100'
                  : s.kind === 'quality' ? 'border-amber-100 bg-amber-50/60 text-amber-700 hover:bg-amber-100'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-100'
                }`}
              >
                {s.kind === 'generate' ? <Play className="h-2.5 w-2.5 shrink-0" />
                  : s.kind === 'quality' ? <AlertTriangle className="h-2.5 w-2.5 shrink-0" />
                  : <Wand2 className="h-2.5 w-2.5 shrink-0" />}
                <span className="truncate">{s.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input — officer language, no @ jargon */}
      <form onSubmit={e => { e.preventDefault(); submit(input); }} className="border-t border-slate-100 p-2">
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 focus-within:border-blue-300 focus-within:ring-1 focus-within:ring-blue-200">
          <Wand2 className="h-3 w-3 text-slate-300" />
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(input); } }}
            placeholder="Ask anything, or describe a change…"
            className="flex-1 bg-transparent text-[11px] text-slate-700 placeholder:text-slate-400 outline-none"
          />
          <button type="submit" disabled={!input.trim() || busy} className="rounded bg-blue-600 px-2 py-0.5 text-[9px] font-medium text-white disabled:opacity-30 hover:bg-blue-700">Send</button>
        </div>
        <p className="mt-1 text-[8px] text-slate-300 text-center">e.g. “trim this”, “what’s pending?”, “which state leads?” · Ctrl+Enter</p>
      </form>
    </div>
  );
}
