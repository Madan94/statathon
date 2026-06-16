'use client';
import { useState } from 'react';
import { X, MessageSquare, Flag, CheckCircle2, Circle, Send } from 'lucide-react';
import type { ReviewModel, DocStatus } from '../engine/useReviewModel';

/* ═══════════════════════════════════════════════════════════════════
   ReviewPanel (U4) — editorial review popup: status workflow, open
   comment threads (jump-to-block), attention flags, and the sign-off
   gate that blocks Approval while issues remain.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  review: ReviewModel;
  officer: string;
  onClose: () => void;
  onJumpToBlock: (blockId: string) => void;
  blockTitle: (blockId: string) => string;
}

const STATUS_STEPS: Array<{ id: DocStatus; label: string }> = [
  { id: 'draft', label: 'Draft' },
  { id: 'in_review', label: 'In Review' },
  { id: 'approved', label: 'Approved' },
];

export function ReviewPanel({ review, officer, onClose, onJumpToBlock, blockTitle }: Props) {
  const [reply, setReply] = useState<Record<string, string>>({});
  const threads = review.comments.filter(c => !c.parentId);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/30 backdrop-blur-sm" onClick={onClose}>
      <div className="flex max-h-[82vh] w-[600px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="text-[14px] font-semibold text-slate-800">Review &amp; Sign-off</h2>
            <p className="text-[11px] text-slate-400">
              {review.openComments} open comment{review.openComments !== 1 ? 's' : ''} · {review.openFlags} flag{review.openFlags !== 1 ? 's' : ''}
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1.5 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>

        {/* Status workflow */}
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
          {STATUS_STEPS.map((s, i) => {
            const active = review.status === s.id;
            const disabled = s.id === 'approved' && !review.canSignOff;
            return (
              <div key={s.id} className="flex items-center gap-2">
                <button
                  onClick={() => s.id === 'approved' ? review.approve(officer) : review.setStatus(s.id)}
                  disabled={disabled}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium transition-colors ${
                    active ? 'bg-blue-600 text-white' : disabled ? 'cursor-not-allowed bg-slate-50 text-slate-300' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                  title={disabled ? 'Resolve all comments & flags first' : s.label}
                >
                  {active ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />} {s.label}
                </button>
                {i < STATUS_STEPS.length - 1 && <span className="text-slate-300">→</span>}
              </div>
            );
          })}
        </div>

        {/* Sign-off gate banner */}
        {!review.canSignOff && (
          <div className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-[11px] text-amber-700">
            ⚑ Sign-off blocked — resolve {review.openComments} comment{review.openComments !== 1 ? 's' : ''} and {review.openFlags} flag{review.openFlags !== 1 ? 's' : ''} before approving.
          </div>
        )}
        {review.approval && review.status === 'approved' && (
          <div className="border-b border-emerald-100 bg-emerald-50 px-4 py-2 text-[11px] text-emerald-700">
            ✓ Approved by {review.approval.by} on {new Date(review.approval.at).toLocaleString('en-IN')}.
          </div>
        )}

        {/* Comment threads */}
        <div className="flex-1 overflow-auto p-3">
          {threads.length === 0 && (
            <p className="py-8 text-center text-[11px] text-slate-300">No comments yet. Flag a block or add a comment from its action bar.</p>
          )}
          {threads.map(t => {
            const replies = review.comments.filter(c => c.parentId === t.id);
            return (
              <div key={t.id} className={`mb-2 rounded-lg border p-2.5 ${t.resolved ? 'border-slate-100 bg-slate-50/50 opacity-60' : 'border-slate-200'}`}>
                <button onClick={() => onJumpToBlock(t.blockId)} className="mb-1 flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wide text-blue-500 hover:text-blue-700">
                  <MessageSquare className="h-2.5 w-2.5" /> {blockTitle(t.blockId)}
                </button>
                <p className="text-[11px] text-slate-700"><span className="font-semibold">{t.author}:</span> {t.text}</p>
                {replies.map(r => (
                  <p key={r.id} className="ml-3 mt-1 border-l-2 border-slate-200 pl-2 text-[10px] text-slate-600"><span className="font-semibold">{r.author}:</span> {r.text}</p>
                ))}
                {!t.resolved && (
                  <div className="mt-1.5 flex items-center gap-1">
                    <input
                      value={reply[t.id] || ''}
                      onChange={e => setReply(p => ({ ...p, [t.id]: e.target.value }))}
                      onKeyDown={e => { if (e.key === 'Enter') { review.addComment(t.blockId, officer, reply[t.id] || '', t.id); setReply(p => ({ ...p, [t.id]: '' })); } }}
                      placeholder="Reply…"
                      className="flex-1 rounded border border-slate-200 px-2 py-0.5 text-[10px] outline-none focus:border-blue-300"
                    />
                    <button onClick={() => { review.addComment(t.blockId, officer, reply[t.id] || '', t.id); setReply(p => ({ ...p, [t.id]: '' })); }} className="rounded p-1 text-blue-500 hover:bg-blue-50"><Send className="h-3 w-3" /></button>
                    <button onClick={() => review.resolveComment(t.id)} className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-medium text-emerald-600 hover:bg-emerald-100">Resolve</button>
                  </div>
                )}
              </div>
            );
          })}

          {/* Flagged blocks */}
          {review.flags.size > 0 && (
            <div className="mt-3">
              <p className="mb-1 flex items-center gap-1 text-[9px] font-bold uppercase tracking-wide text-amber-500"><Flag className="h-2.5 w-2.5" /> Needs attention</p>
              {Array.from(review.flags).map(id => (
                <button key={id} onClick={() => onJumpToBlock(id)} className="mb-1 flex w-full items-center justify-between rounded border border-amber-100 bg-amber-50/60 px-2 py-1 text-left text-[10px] text-amber-700 hover:bg-amber-100">
                  <span className="truncate">{blockTitle(id)}</span>
                  <button onClick={e => { e.stopPropagation(); review.toggleFlag(id); }} className="text-[9px] font-medium text-amber-500 hover:text-amber-700">Clear</button>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
