'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ChevronDown, ChevronRight, ClipboardCheck, Eye, FileWarning,
  LayoutGrid, Loader2, Lock, MessageSquare, RotateCcw, Search, ShieldCheck,
  Sparkles, Wand2, Wrench, X,
} from 'lucide-react';
import type { PageBlock } from '../engine/useCanvasState';
import type { ChatMessage } from '../engine/useCanvasAgent';
import type { Suggestion } from '../engine/assistantOrchestrator';

/* ═══════════════════════════════════════════════════════════════════
   RightPanel — governed MoSPI Co-Pilot.
   Tabs separate chat from tools/evidence/layout/review so the rail stays calm.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  selectedBlock: PageBlock | null;
  messages: ChatMessage[];
  busy: boolean;
  onSend: (msg: string) => void;
  onClose: () => void;
  onRegenerate?: (index: number) => void;
  onInsert?: (text: string) => void;
  suggestions?: Suggestion[];
}

type Tab = 'ask' | 'tools' | 'evidence' | 'layout' | 'review';

function renderRich(content: string) {
  return content.split('\n').map((line, i) => {
    const quote = line.startsWith('> ');
    const body = quote ? line.slice(2) : line;
    const parts = body.split(/(\*\*[^*]+\*\*)/g).map((seg, j) =>
      seg.startsWith('**') && seg.endsWith('**')
        ? <strong key={j} className="font-semibold">{seg.slice(2, -2)}</strong>
        : <span key={j}>{seg}</span>
    );
    return <p key={i} className={quote ? 'border-l-2 border-slate-300 pl-2 italic text-slate-500' : ''}>{parts.length ? parts : '\u00A0'}</p>;
  });
}

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
            <thead className="bg-slate-50 text-slate-500"><tr>{cols.slice(0, 5).map(c => <th key={c} className="px-1.5 py-0.5 text-left font-semibold">{c}</th>)}</tr></thead>
            <tbody>
              {table.rows.slice(0, 8).map((row, ri) => (
                <tr key={ri} className="border-t border-slate-100">{cols.slice(0, 5).map(c => <td key={c} className="px-1.5 py-0.5 text-slate-600">{String(row[c] ?? '')}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function provenanceOf(block: PageBlock | null): Record<string, unknown> | null {
  if (!block) return null;
  const td = block.tableData as Record<string, unknown> | undefined;
  return (td?.provenance as Record<string, unknown> | undefined) || null;
}

function rowsOf(block: PageBlock | null): Array<Record<string, unknown>> {
  const td = block?.tableData as Record<string, unknown> | undefined;
  const rows = (td?.items || td?.rankingData || td?.aggregationData || td?.rows || []) as Array<Record<string, unknown>>;
  return Array.isArray(rows) ? rows : [];
}

export function RightPanel({ selectedBlock, messages, busy, onSend, onClose, onRegenerate, onInsert, suggestions = [] }: Props) {
  const [input, setInput] = useState('');
  const [tab, setTab] = useState<Tab>('ask');
  const scrollRef = useRef<HTMLDivElement>(null);
  const provenance = useMemo(() => provenanceOf(selectedBlock), [selectedBlock]);
  const dataRows = useMemo(() => rowsOf(selectedBlock), [selectedBlock]);

  useEffect(() => {
    if (tab === 'ask') scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, tab]);

  const submit = (msg: string) => {
    if (!msg.trim() || busy) return;
    onSend(msg);
    setInput('');
    setTab('ask');
  };

  const tabs: Array<{ id: Tab; label: string; icon: typeof MessageSquare }> = [
    { id: 'ask', label: 'Ask', icon: MessageSquare },
    { id: 'tools', label: 'Tools', icon: Wrench },
    { id: 'evidence', label: 'Evidence', icon: ShieldCheck },
    { id: 'layout', label: 'Layout', icon: LayoutGrid },
    { id: 'review', label: 'Review', icon: ClipboardCheck },
  ];

  return (
    <div className="flex w-[340px] shrink-0 flex-col border-l border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-blue-600"><Sparkles className="h-3 w-3 text-white" /></div>
          <div className="min-w-0">
            <p className="truncate text-[12px] font-semibold text-slate-800">MoSPI Co-Pilot</p>
            <p className="truncate text-[9px] text-slate-400">Ask · Tools · Evidence · Layout · Review</p>
          </div>
        </div>
        <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100" title="Close co-pilot"><X className="h-3.5 w-3.5" /></button>
      </div>

      <div className="grid grid-cols-5 border-b border-slate-100 bg-slate-50">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)} className={`flex flex-col items-center gap-0.5 px-1 py-2 text-[8px] font-semibold uppercase tracking-wide ${tab === id ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`} title={label}>
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </div>

      {selectedBlock && selectedBlock.status === 'done' && (
        <div className="border-b border-slate-100 bg-slate-50/70 p-3">
          <p className="text-[9px] font-bold uppercase tracking-wide text-slate-400">Selected {selectedBlock.kind}</p>
          <p className="mt-1 truncate text-[11px] font-medium text-slate-700">{selectedBlock.title}</p>
        </div>
      )}

      {tab === 'ask' && (
        <>
          <div ref={scrollRef} className="flex-1 space-y-2 overflow-auto p-3">
            {messages.map(m => (
              <div key={m.id} className={m.role === 'user' ? 'ml-8' : ''}>
                <div className={`space-y-1 rounded-lg px-3 py-2 text-[11px] leading-relaxed ${m.role === 'user' ? 'bg-blue-600 text-white' : m.role === 'system' ? 'border border-slate-100 bg-slate-50 text-slate-500' : 'bg-slate-100 text-slate-700'}`}>
                  {m.tool === 'deep_bi' && m.bound !== undefined && (
                    m.bound ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-1.5 py-0.5 text-[8px] font-semibold text-emerald-700"><Lock className="h-2.5 w-2.5" /> Bound</span>
                      : <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-1.5 py-0.5 text-[8px] font-semibold text-amber-700"><Search className="h-2.5 w-2.5" /> Exploratory</span>
                  )}
                  {renderRich(m.content)}
                  {m.provenance && (m.provenance.columns.length > 0 || m.provenance.rows > 0) && (
                    <p className="pt-0.5 text-[8px] text-slate-400">{m.provenance.columns.length > 0 && <>Columns: <span className="font-mono text-slate-500">{m.provenance.columns.slice(0, 3).join(', ')}</span> · </>}{m.provenance.rows > 0 && <>{m.provenance.rows.toLocaleString()} rows</>}</p>
                  )}
                  {m.resultTable && m.resultTable.rows.length > 0 && <ResultRows table={m.resultTable} />}
                  {m.tool && <p className="pt-0.5 text-[8px] uppercase tracking-wide text-slate-400">via {m.tool}</p>}
                  {m.tool === 'deep_bi' && m.bound === false && <p className="text-[8px] text-amber-600">⚠ Unconfirmed column. <Link href="/report-builder/binding" className="underline hover:text-amber-800">Bind it ▸</Link></p>}
                  {m.insertText && onInsert && <button onClick={() => onInsert(m.insertText!)} className="mt-1 rounded bg-blue-600 px-2 py-0.5 text-[9px] font-medium text-white hover:bg-blue-700">+ Insert</button>}
                </div>
              </div>
            ))}
            {busy && <div className="flex items-center gap-2 px-3 py-2 text-[10px] text-slate-400"><Loader2 className="h-3 w-3 animate-spin" /> Thinking…</div>}
            {messages.length === 0 && !busy && <div className="py-8 text-center text-[10px] text-slate-400"><Sparkles className="mx-auto mb-2 h-5 w-5 text-slate-200" /><p className="font-medium text-slate-500">Ask about data, layout, or wording</p><p className="mt-0.5">Use Tools for safe one-click actions.</p></div>}
          </div>

          {suggestions.length > 0 && (
            <div className="border-t border-slate-100 bg-slate-50/60 px-3 py-2">
              <p className="mb-1.5 flex items-center gap-1 text-[8px] font-bold uppercase tracking-wide text-slate-400"><Sparkles className="h-2.5 w-2.5 text-indigo-400" /> Suggested</p>
              <div className="flex flex-col gap-1">
                {suggestions.slice(0, 4).map(s => <button key={s.id} onClick={() => onSend(s.command)} className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-left text-[10px] font-medium text-slate-600 hover:bg-slate-100"><Wand2 className="h-2.5 w-2.5 shrink-0" /><span className="truncate">{s.label}</span></button>)}
              </div>
            </div>
          )}

          <form onSubmit={e => { e.preventDefault(); submit(input); }} className="border-t border-slate-100 p-2">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 focus-within:border-blue-300 focus-within:ring-1 focus-within:ring-blue-200">
              <Wand2 className="h-3 w-3 text-slate-300" />
              <input value={input} onChange={e => setInput(e.target.value)} placeholder="Ask anything, or describe a change…" className="flex-1 bg-transparent text-[11px] text-slate-700 placeholder:text-slate-400 outline-none" />
              <button type="submit" disabled={!input.trim() || busy} className="rounded bg-blue-600 px-2 py-0.5 text-[9px] font-medium text-white hover:bg-blue-700 disabled:opacity-30">Send</button>
            </div>
          </form>
        </>
      )}

      {tab === 'tools' && (
        <div className="flex-1 space-y-3 overflow-auto p-3">
          <p className="text-[10px] text-slate-500">Safe officer tools for the selected block and current draft.</p>
          <div className="grid grid-cols-2 gap-2">
            <button disabled={!selectedBlock} onClick={() => selectedBlock && onRegenerate?.(selectedBlock.index)} className="rounded-lg border border-slate-200 p-3 text-left text-[11px] font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"><RotateCcw className="mb-1 h-4 w-4 text-blue-500" />Regenerate</button>
            <button disabled={!selectedBlock} onClick={() => selectedBlock && submit(`inspect ${selectedBlock.index}`)} className="rounded-lg border border-slate-200 p-3 text-left text-[11px] font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"><Eye className="mb-1 h-4 w-4 text-indigo-500" />Inspect</button>
            <button disabled={!selectedBlock || selectedBlock.kind !== 'narrative'} onClick={() => selectedBlock && submit(`shorter ${selectedBlock.index}`)} className="rounded-lg border border-slate-200 p-3 text-left text-[11px] font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"><Wand2 className="mb-1 h-4 w-4 text-emerald-500" />Shorten</button>
            <button onClick={() => submit('repack layout')} className="rounded-lg border border-slate-200 p-3 text-left text-[11px] font-medium text-slate-700 hover:bg-slate-50"><LayoutGrid className="mb-1 h-4 w-4 text-slate-500" />Repack</button>
          </div>
        </div>
      )}

      {tab === 'evidence' && (
        <div className="flex-1 space-y-3 overflow-auto p-3 text-[11px] text-slate-600">
          {!selectedBlock ? <p className="rounded border border-dashed border-slate-200 p-4 text-center text-slate-400">Select a table, chart, metric, or generated block to inspect evidence.</p> : <>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><p className="font-semibold text-slate-800">{selectedBlock.title}</p><p className="mt-1 text-slate-500">Kind: {selectedBlock.kind}</p></div>
            {provenance ? <div className="space-y-2 rounded-lg border border-emerald-100 bg-emerald-50/60 p-3">
              <p className="font-semibold text-emerald-800">Evidence attached</p>
              {Object.entries(provenance).map(([k, v]) => <p key={k}><span className="font-medium">{k}:</span> {Array.isArray(v) ? v.join(', ') : String(v)}</p>)}
            </div> : <p className="rounded border border-amber-200 bg-amber-50 p-3 text-amber-700">No provenance payload found on this block yet.</p>}
            {dataRows.length > 0 && <ResultRows table={{ columns: Object.keys(dataRows[0] || {}), rows: dataRows }} />}
          </>}
        </div>
      )}

      {tab === 'layout' && (
        <div className="flex-1 space-y-3 overflow-auto p-3 text-[11px] text-slate-600">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><p className="font-semibold text-slate-800">Layout assistant</p><p className="mt-1">Use these actions to balance the document without changing data.</p></div>
          <button onClick={() => submit('repack layout')} className="w-full rounded-md bg-blue-600 px-3 py-2 text-left font-medium text-white hover:bg-blue-700">Repack / balance pages</button>
          <button disabled={!selectedBlock} onClick={() => selectedBlock && submit(`fit ${selectedBlock.index}`)} className="w-full rounded-md border border-slate-200 px-3 py-2 text-left font-medium hover:bg-slate-50 disabled:opacity-40">Fit selected block</button>
          <button onClick={() => submit('layout status')} className="w-full rounded-md border border-slate-200 px-3 py-2 text-left font-medium hover:bg-slate-50">Explain page spacing</button>
        </div>
      )}

      {tab === 'review' && (
        <div className="flex-1 space-y-3 overflow-auto p-3 text-[11px] text-slate-600">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><p className="font-semibold text-slate-800">Review readiness</p><p className="mt-1">Check warnings, evidence and final export readiness before sign-off.</p></div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded border border-emerald-100 bg-emerald-50 p-3"><p className="text-[9px] uppercase text-emerald-600">Evidence</p><p className="text-lg font-semibold text-emerald-700">{provenance ? 'OK' : '—'}</p></div>
            <div className="rounded border border-amber-100 bg-amber-50 p-3"><p className="text-[9px] uppercase text-amber-600">Warnings</p><p className="text-lg font-semibold text-amber-700">0</p></div>
          </div>
          <button onClick={() => submit('review issues')} className="w-full rounded-md border border-slate-200 px-3 py-2 text-left font-medium hover:bg-slate-50"><FileWarning className="mr-1 inline h-3.5 w-3.5" />List review issues</button>
        </div>
      )}
    </div>
  );
}
