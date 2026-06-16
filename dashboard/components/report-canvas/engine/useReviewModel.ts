'use client';
import { useCallback, useMemo, useState } from 'react';

/* ═══════════════════════════════════════════════════════════════════
   Review model (U4) — editorial layer for the report.

   • Per-block comment threads (add / reply / resolve).
   • Per-block "needs attention" flags.
   • Document status workflow: Draft → In Review → Approved.
   • Sign-off gate: a report cannot reach Approved / Final-export while
     open comments or attention flags remain.
   ═══════════════════════════════════════════════════════════════════ */

export type DocStatus = 'draft' | 'in_review' | 'approved';

export interface Comment {
  id: string;
  blockId: string;
  author: string;
  text: string;
  at: number;
  resolved: boolean;
  parentId?: string;     // reply target
}

export interface ReviewModel {
  status: DocStatus;
  setStatus: (s: DocStatus) => void;
  comments: Comment[];
  flags: Set<string>;            // blockIds flagged "needs attention"
  addComment: (blockId: string, author: string, text: string, parentId?: string) => void;
  resolveComment: (id: string) => void;
  deleteComment: (id: string) => void;
  toggleFlag: (blockId: string) => void;
  commentCount: (blockId: string) => number;        // OPEN comments on a block
  openComments: number;
  openFlags: number;
  /** Whether the report can advance to Approved / export Final. */
  canSignOff: boolean;
  /** Audit record of the last approval (who + when). */
  approval: { by: string; at: number } | null;
  approve: (by: string) => boolean;
}

export function useReviewModel(): ReviewModel {
  const [status, setStatusRaw] = useState<DocStatus>('draft');
  const [comments, setComments] = useState<Comment[]>([]);
  const [flags, setFlags] = useState<Set<string>>(new Set());
  const [approval, setApproval] = useState<{ by: string; at: number } | null>(null);

  const addComment = useCallback((blockId: string, author: string, text: string, parentId?: string) => {
    if (!text.trim()) return;
    setComments(prev => [...prev, {
      id: `cmt-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      blockId, author: author || 'Officer', text: text.trim(), at: Date.now(), resolved: false, parentId,
    }]);
  }, []);

  const resolveComment = useCallback((id: string) => {
    setComments(prev => prev.map(c => c.id === id ? { ...c, resolved: true } : c));
  }, []);

  const deleteComment = useCallback((id: string) => {
    setComments(prev => prev.filter(c => c.id !== id && c.parentId !== id));
  }, []);

  const toggleFlag = useCallback((blockId: string) => {
    setFlags(prev => {
      const next = new Set(prev);
      if (next.has(blockId)) next.delete(blockId); else next.add(blockId);
      return next;
    });
  }, []);

  const openComments = useMemo(() => comments.filter(c => !c.resolved && !c.parentId).length, [comments]);
  const openFlags = flags.size;
  const canSignOff = openComments === 0 && openFlags === 0;

  const commentCount = useCallback((blockId: string) =>
    comments.filter(c => c.blockId === blockId && !c.resolved && !c.parentId).length, [comments]);

  const setStatus = useCallback((s: DocStatus) => {
    // Gate: cannot move to Approved with open issues.
    if (s === 'approved' && (openComments > 0 || openFlags > 0)) return;
    setStatusRaw(s);
  }, [openComments, openFlags]);

  const approve = useCallback((by: string): boolean => {
    if (openComments > 0 || openFlags > 0) return false;
    setApproval({ by: by || 'Officer', at: Date.now() });
    setStatusRaw('approved');
    return true;
  }, [openComments, openFlags]);

  return {
    status, setStatus, comments, flags, addComment, resolveComment, deleteComment,
    toggleFlag, commentCount, openComments, openFlags, canSignOff, approval, approve,
  };
}
