'use client';
import { useEffect, useRef, useState } from 'react';
import { Flag } from 'lucide-react';
import type { PageBlock } from '../engine/useCanvasState';
import type { NumberedHeading, TableSplitPart } from '../engine/paginationEngine';
import { EDITABLE_KINDS, MULTILINE_KINDS } from '../engine/canvasTokens';
import { RichTextEditor } from './RichTextEditor';
import { BlockStatus } from './kinds/BlockStatus';
import { BLOCK_REGISTRY } from './registry';

/* ═══════════════════════════════════════════════════════════════════
   BlockRenderer — thin orchestrator for one block.
   • Lifecycle states (generating/pending/error) → BlockStatus.
   • Inline editing (text + metric) → RichTextEditor / numeric input.
   • "Done" content → dispatched to the per-kind component via the
     BLOCK_REGISTRY (one component per kind under kinds/).
   The selection toolbar + drag/resize chrome live in the page wrapper.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  block: PageBlock;
  isSelected: boolean;
  onSelect: () => void;
  onGenerate?: (index: number) => void;
  onUpdate?: (id: string, updates: Partial<PageBlock>) => void;
  /** Add a footnote to this block; returns the marker number (U2). */
  onAddFootnote?: (blockId: string, text: string) => number;
  /** Open-comment count (badge). */
  commentCount?: number;
  /** Whether this block is flagged for attention. */
  flagged?: boolean;
  /** Numeral system for figures (T6). */
  numerals?: 'intl' | 'devanagari';
  /** Decimal §-number + anchor for heading-like blocks (from the packer). */
  numbering?: NumberedHeading;
  /** This block's caption (e.g. "Table 1.1"), when it's a numbered table. */
  tableCaption?: string;
  /** Row window + continuation flags when this is a split table part. */
  splitPart?: TableSplitPart;
}

export function BlockRenderer({ block, isSelected, onSelect, onGenerate, onUpdate, onAddFootnote, commentCount = 0, flagged = false, numerals = 'intl', numbering, tableCaption, splitPart }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const startEdit = () => {
    if (!EDITABLE_KINDS.has(block.kind) || !onUpdate) return;
    // Metric edits its numeric value; everything else edits its text content.
    setDraft(block.kind === 'metric' ? (block.metricValue ?? '') : (block.content || ''));
    setEditing(true);
  };
  const commit = () => {
    if (onUpdate) onUpdate(block.id, block.kind === 'metric' ? { metricValue: draft } : { content: draft });
    setEditing(false);
  };
  const cancel = () => setEditing(false);

  // ── Lifecycle states (generating / pending / error) ──
  if (block.status !== 'done') {
    return <BlockStatus block={block} onGenerate={onGenerate} />;
  }

  // ── Inline editor (text kinds) ──
  if (editing) {
    // Metric edits a single numeric value — keep a simple input.
    if (block.kind === 'metric') {
      return (
        <div onPointerDown={e => e.stopPropagation()} className="rounded ring-2 ring-blue-400 ring-offset-1">
          <input
            ref={inputRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={e => {
              e.stopPropagation();
              if (e.key === 'Escape') { e.preventDefault(); cancel(); }
              if (e.key === 'Enter') { e.preventDefault(); commit(); }
            }}
            inputMode="decimal"
            aria-label="Edit metric value"
            className="w-full rounded bg-white px-2 py-1 text-[12px] text-slate-700 outline-none"
            placeholder="Value…"
          />
        </div>
      );
    }
    // Rich text for narrative / heading / key_finding / source_note (U2).
    return (
      <div onPointerDown={e => e.stopPropagation()}>
        <RichTextEditor
          value={draft}
          multiline={MULTILINE_KINDS.has(block.kind)}
          onCommit={(html) => { if (onUpdate) onUpdate(block.id, { content: html }); setEditing(false); }}
          onCancel={cancel}
          onAddFootnote={onAddFootnote ? (text) => onAddFootnote(block.id, text) : undefined}
        />
      </div>
    );
  }

  // ── DONE: real content, dispatched to the per-kind component ──
  const KindComponent = BLOCK_REGISTRY[block.kind];
  return (
    <div
      onClick={e => { e.stopPropagation(); onSelect(); startEdit(); }}
      className={`relative rounded transition-all ${isSelected ? 'ring-2 ring-blue-400 ring-offset-1 bg-blue-50/10' : 'hover:bg-slate-50/50'}`}
    >
      {/* Review markers (U4): comment count + attention flag — always visible */}
      {(commentCount > 0 || flagged) && (
        <div className="absolute -left-1.5 -top-1.5 z-20 flex items-center gap-0.5">
          {commentCount > 0 && (
            <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-blue-500 px-1 text-[8px] font-bold text-white shadow" title={`${commentCount} open comment(s)`}>{commentCount}</span>
          )}
          {flagged && <Flag className="h-3 w-3 fill-amber-400 text-amber-500" />}
        </div>
      )}

      {KindComponent && (
        <KindComponent
          block={block}
          isSelected={isSelected}
          numerals={numerals}
          numbering={numbering}
          tableCaption={tableCaption}
          splitPart={splitPart}
        />
      )}
    </div>
  );
}
