'use client';
import { useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import type { PageBlock } from '../engine/useCanvasState';

/* ═══════════════════════════════════════════════════════════════════
   RightPanel — MoSPI Intelligence Assistant.
   Context-aware: shows selected block info + chat.
   ═══════════════════════════════════════════════════════════════════ */

interface ChatMsg { id: string; role: 'user' | 'assistant'; content: string; }

interface Props {
  selectedBlock: PageBlock | null;
  onClose: () => void;
  onRegenerate?: (index: number) => void;
}

export function RightPanel({ selectedBlock, onClose, onRegenerate }: Props) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');

  const send = (msg: string) => {
    if (!msg.trim()) return;
    setMsgs(prev => [...prev, { id: `u-${Date.now()}`, role: 'user', content: msg }]);
    setInput('');
    setTimeout(() => {
      setMsgs(prev => [...prev, { id: `a-${Date.now()}`, role: 'assistant', content: `Processing: "${msg}". Select a block for context-aware actions.` }]);
    }, 300);
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
            {selectedBlock.kind === 'table' && <button className="rounded bg-white border border-slate-200 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-50">Top 5 only</button>}
            {selectedBlock.kind === 'narrative' && <button className="rounded bg-white border border-slate-200 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-50">Make shorter</button>}
            <button className="rounded bg-white border border-slate-200 px-2 py-0.5 text-[9px] font-medium text-slate-600 hover:bg-slate-50">Explain data</button>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-auto p-3 space-y-2">
        {msgs.map(m => (
          <div key={m.id} className={m.role === 'user' ? 'ml-8' : ''}>
            <div className={`rounded-lg px-3 py-2 text-[11px] leading-relaxed ${m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700'}`}>
              {m.content}
            </div>
          </div>
        ))}
        {msgs.length === 0 && (
          <div className="py-8 text-center text-[10px] text-slate-400">
            <Sparkles className="mx-auto h-5 w-5 text-slate-200 mb-2" />
            <p>Select a block, then ask questions</p>
            <p className="mt-0.5">or request modifications.</p>
          </div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={e => { e.preventDefault(); send(input); }} className="border-t border-slate-100 p-2">
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 focus-within:border-blue-300 focus-within:ring-1 focus-within:ring-blue-200">
          <input value={input} onChange={e => setInput(e.target.value)} placeholder="Ask about the selected block..." className="flex-1 bg-transparent text-[11px] text-slate-700 placeholder:text-slate-400 outline-none" />
          <button type="submit" disabled={!input.trim()} className="rounded bg-blue-600 px-2 py-0.5 text-[9px] font-medium text-white disabled:opacity-30">Send</button>
        </div>
      </form>
    </div>
  );
}
