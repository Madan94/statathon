'use client';

/**
 * ReportDocumentCanvas — A4 page-based document editor for generated reports.
 * 
 * Features:
 * - A4-proportioned pages stacked vertically
 * - Blocks appear with soft fade-in animation
 * - Double-click text to edit inline
 * - Floating toolbar on text selection (bold, italic, size)
 * - Hover chart → gear icon → config modal
 * - Drag handles + Ctrl+↑/↓ for reorder
 * - '+' button between blocks to insert new content
 * - Page breaks with page numbers
 */

import { useEffect, useRef, useState } from 'react';
import {
  BarChart3,
  Bold,
  ChevronDown,
  ChevronUp,
  FileText,
  FunctionSquare,
  GripVertical,
  Italic,
  MessageSquare,
  Minus,
  Plus,
  Settings,
  Table2,
  Trash2,
  Type,
  Underline,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';

// ─── Types ──────────────────────────────────────────────────────────────────

export interface DocBlock {
  id: string;
  kind: 'heading' | 'narrative' | 'key_finding' | 'chart' | 'table' | 'metric' | 'source_note' | 'methodology_note' | 'data_caveat' | 'footnote' | 'glossary_term' | 'divider' | 'spacer';
  content: string;
  title?: string;
  level?: number; // heading level 1-4
  chartConfig?: Record<string, unknown>;
  tableData?: Record<string, unknown>;
  metricValue?: string;
  metricUnit?: string;
  status: 'pending' | 'generating' | 'done' | 'error';
  planId?: string;
  componentIndex?: number;
}

interface ReportDocumentCanvasProps {
  blocks: DocBlock[];
  onUpdateBlock?: (id: string, updates: Partial<DocBlock>) => void;
  onReorderBlock?: (id: string, direction: 'up' | 'down') => void;
  onDeleteBlock?: (id: string) => void;
  onInsertBlock?: (afterId: string, kind: DocBlock['kind']) => void;
  readOnly?: boolean;
  className?: string;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function blockIcon(kind: string) {
  if (kind === 'chart') return BarChart3;
  if (kind === 'table') return Table2;
  if (kind === 'metric' || kind === 'formula_metric') return FunctionSquare;
  if (kind === 'heading' || kind === 'narrative' || kind === 'key_finding') return FileText;
  return MessageSquare;
}

function blockLabel(kind: string): string {
  return kind.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

// ─── Inline Editor ──────────────────────────────────────────────────────────

function InlineEditor({ value, onChange, onBlur, level }: {
  value: string;
  onChange: (v: string) => void;
  onBlur: () => void;
  level?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.focus();
      // Place cursor at end
      const range = document.createRange();
      const sel = window.getSelection();
      range.selectNodeContents(ref.current);
      range.collapse(false);
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
  }, []);

  const fontSize = level === 1 ? 'text-2xl' : level === 2 ? 'text-xl' : level === 3 ? 'text-lg' : 'text-sm';

  return (
    <div className="relative">
      {/* Floating toolbar */}
      <div className="absolute -top-10 left-0 z-20 flex items-center gap-0.5 rounded-lg border border-border bg-surface-card px-1 py-0.5 shadow-lg">
        <button type="button" className="rounded p-1.5 text-text-muted hover:bg-border/40 hover:text-text" onClick={() => document.execCommand('bold')}><Bold className="h-3.5 w-3.5" /></button>
        <button type="button" className="rounded p-1.5 text-text-muted hover:bg-border/40 hover:text-text" onClick={() => document.execCommand('italic')}><Italic className="h-3.5 w-3.5" /></button>
        <button type="button" className="rounded p-1.5 text-text-muted hover:bg-border/40 hover:text-text" onClick={() => document.execCommand('underline')}><Underline className="h-3.5 w-3.5" /></button>
        <div className="mx-1 h-4 w-px bg-border" />
        <button type="button" className="rounded p-1.5 text-text-muted hover:bg-border/40 hover:text-text" title="Heading"><Type className="h-3.5 w-3.5" /></button>
      </div>
      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        className={`min-h-[1.5em] rounded-md px-1 py-0.5 outline-none ring-2 ring-primary/30 ${fontSize} leading-relaxed text-slate-700`}
        onInput={(e) => onChange((e.target as HTMLDivElement).innerText)}
        onBlur={onBlur}
        onKeyDown={(e) => { if (e.key === 'Escape') onBlur(); }}
        dangerouslySetInnerHTML={{ __html: value }}
      />
    </div>
  );
}

// ─── Insert Menu ────────────────────────────────────────────────────────────

function InsertMenu({ onInsert, onClose }: { onInsert: (kind: DocBlock['kind']) => void; onClose: () => void }) {
  const items: { kind: DocBlock['kind']; label: string; icon: typeof FileText }[] = [
    { kind: 'narrative', label: 'Text paragraph', icon: FileText },
    { kind: 'heading', label: 'Heading', icon: Type },
    { kind: 'chart', label: 'Chart placeholder', icon: BarChart3 },
    { kind: 'table', label: 'Table placeholder', icon: Table2 },
    { kind: 'metric', label: 'Metric value', icon: FunctionSquare },
    { kind: 'source_note', label: 'Source note', icon: MessageSquare },
    { kind: 'divider', label: 'Divider line', icon: Minus },
  ];

  return (
    <div className="absolute left-1/2 z-30 -translate-x-1/2 rounded-xl border border-border bg-surface-card p-2 shadow-xl" onClick={(e) => e.stopPropagation()}>
      <div className="grid grid-cols-2 gap-1">
        {items.map(({ kind, label, icon: Icon }) => (
          <button
            key={kind}
            type="button"
            onClick={() => { onInsert(kind); onClose(); }}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-text-muted transition-colors hover:bg-surface hover:text-text"
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Document Block ─────────────────────────────────────────────────────────

function DocumentBlock({
  block,
  isFirst,
  onUpdate,
  onReorder,
  onDelete,
  onInsertAfter,
  readOnly,
}: {
  block: DocBlock;
  isFirst: boolean;
  onUpdate?: (updates: Partial<DocBlock>) => void;
  onReorder?: (dir: 'up' | 'down') => void;
  onDelete?: () => void;
  onInsertAfter?: (kind: DocBlock['kind']) => void;
  readOnly?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [showInsert, setShowInsert] = useState(false);
  const [hovered, setHovered] = useState(false);

  const isTextBlock = ['heading', 'narrative', 'key_finding', 'source_note', 'methodology_note', 'data_caveat', 'footnote', 'glossary_term'].includes(block.kind);

  // Animation class for fade-in
  const fadeClass = block.status === 'done' ? 'animate-in fade-in duration-500' : block.status === 'generating' ? 'opacity-50' : '';

  // Divider
  if (block.kind === 'divider') {
    return <div className="my-4 border-t border-slate-200" />;
  }

  // Spacer
  if (block.kind === 'spacer') {
    return <div className="h-8" />;
  }

  return (
    <div
      className={`group relative ${fadeClass}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setShowInsert(false); }}
    >
      {/* Drag handle + controls (appear on hover) */}
      {!readOnly && hovered && (
        <div className="absolute -left-10 top-1 flex flex-col items-center gap-0.5">
          <button type="button" className="rounded p-0.5 text-slate-300 hover:text-slate-500" onClick={() => onReorder?.('up')} title="Move up">
            <ChevronUp className="h-3 w-3" />
          </button>
          <GripVertical className="h-3 w-3 cursor-grab text-slate-300" />
          <button type="button" className="rounded p-0.5 text-slate-300 hover:text-slate-500" onClick={() => onReorder?.('down')} title="Move down">
            <ChevronDown className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* Delete button (top right on hover) */}
      {!readOnly && hovered && (
        <button type="button" onClick={onDelete} className="absolute -right-8 top-1 rounded p-1 text-slate-300 hover:text-danger" title="Remove block">
          <Trash2 className="h-3 w-3" />
        </button>
      )}

      {/* Block content */}
      <div
        className={`rounded-md px-1 py-1 transition-all ${hovered && !readOnly ? 'bg-slate-50 ring-1 ring-slate-200' : ''} ${block.status === 'pending' ? 'opacity-30' : ''}`}
        onDoubleClick={() => { if (isTextBlock && !readOnly) setEditing(true); }}
      >
        {/* Heading */}
        {block.kind === 'heading' && !editing && (
          <h2 className={`font-bold text-slate-800 ${block.level === 1 ? 'text-2xl' : block.level === 2 ? 'text-xl' : block.level === 3 ? 'text-lg' : 'text-base'}`}>
            {block.content || 'Untitled'}
          </h2>
        )}

        {/* Narrative / text blocks */}
        {isTextBlock && block.kind !== 'heading' && !editing && (
          <p className={`leading-relaxed ${block.kind === 'key_finding' ? 'text-sm font-medium text-slate-700 border-l-2 border-primary pl-3' : block.kind === 'source_note' || block.kind === 'footnote' ? 'text-xs italic text-slate-400' : 'text-sm text-slate-600'}`}>
            {block.content || (readOnly ? '' : 'Double-click to edit...')}
          </p>
        )}

        {/* Inline editor */}
        {editing && (
          <InlineEditor
            value={block.content}
            level={block.kind === 'heading' ? block.level : undefined}
            onChange={(v) => onUpdate?.({ content: v })}
            onBlur={() => setEditing(false)}
          />
        )}

        {/* Chart block */}
        {block.kind === 'chart' && (
          <div className="relative my-2 rounded-lg border border-slate-100 bg-gradient-to-br from-slate-50 to-white p-4">
            <div className="flex h-40 items-center justify-center">
              <div className="text-center">
                <BarChart3 className="mx-auto h-8 w-8 text-blue-300" />
                <p className="mt-2 text-xs text-slate-400">{block.title || 'Chart'}</p>
              </div>
            </div>
            {!readOnly && hovered && (
              <button type="button" className="absolute right-2 top-2 rounded-full border border-border bg-white p-1.5 text-slate-400 shadow-sm hover:text-text" title="Configure chart">
                <Settings className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}

        {/* Table block */}
        {block.kind === 'table' && (
          <div className="relative my-2 rounded-lg border border-slate-100 bg-slate-50 p-3">
            <div className="flex h-20 items-center justify-center">
              <Table2 className="h-6 w-6 text-emerald-300" />
              <p className="ml-2 text-xs text-slate-400">{block.title || 'Data table'}</p>
            </div>
            {!readOnly && hovered && (
              <button type="button" className="absolute right-2 top-2 rounded-full border border-border bg-white p-1.5 text-slate-400 shadow-sm hover:text-text" title="Configure table">
                <Settings className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}

        {/* Metric block */}
        {block.kind === 'metric' && (
          <div className="my-2 flex items-baseline gap-2">
            <span className="text-3xl font-bold text-primary">{block.metricValue || '—'}</span>
            {block.metricUnit && <span className="text-sm text-slate-400">{block.metricUnit}</span>}
            {block.title && <span className="text-xs text-slate-400">— {block.title}</span>}
          </div>
        )}

        {/* Status indicator */}
        {block.status === 'generating' && (
          <div className="mt-1 flex items-center gap-1 text-[10px] text-primary">
            <div className="h-1 w-1 animate-pulse rounded-full bg-primary" />
            Generating...
          </div>
        )}
      </div>

      {/* Insert button between blocks */}
      {!readOnly && (
        <div className="relative flex h-4 items-center justify-center">
          {hovered && (
            <button
              type="button"
              onClick={() => setShowInsert(!showInsert)}
              className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm transition-all hover:border-primary hover:text-primary"
            >
              <Plus className="h-3 w-3" />
            </button>
          )}
          {showInsert && <InsertMenu onInsert={(kind) => onInsertAfter?.(kind)} onClose={() => setShowInsert(false)} />}
        </div>
      )}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function ReportDocumentCanvas({
  blocks,
  onUpdateBlock,
  onReorderBlock,
  onDeleteBlock,
  onInsertBlock,
  readOnly = false,
  className,
}: ReportDocumentCanvasProps) {
  // Split blocks into pages (~10 blocks per page for A4)
  const BLOCKS_PER_PAGE = 8;
  const pages: DocBlock[][] = [];
  for (let i = 0; i < blocks.length; i += BLOCKS_PER_PAGE) {
    pages.push(blocks.slice(i, i + BLOCKS_PER_PAGE));
  }
  if (pages.length === 0) pages.push([]);

  return (
    <div className={`space-y-8 ${className || ''}`}>
      {pages.map((pageBlocks, pageIdx) => (
        <div
          key={pageIdx}
          className="relative mx-auto w-[210mm] min-h-[297mm] rounded-sm border border-slate-200 bg-white px-[25mm] py-[20mm] shadow-md"
          style={{ maxWidth: '794px' }}
        >
          {/* Page content */}
          <div className="space-y-3">
            {pageBlocks.map((block, bIdx) => (
              <DocumentBlock
                key={block.id}
                block={block}
                isFirst={pageIdx === 0 && bIdx === 0}
                onUpdate={onUpdateBlock ? (u) => onUpdateBlock(block.id, u) : undefined}
                onReorder={onReorderBlock ? (d) => onReorderBlock(block.id, d) : undefined}
                onDelete={onDeleteBlock ? () => onDeleteBlock(block.id) : undefined}
                onInsertAfter={onInsertBlock ? (k) => onInsertBlock(block.id, k) : undefined}
                readOnly={readOnly}
              />
            ))}

            {/* Empty page placeholder */}
            {pageBlocks.length === 0 && (
              <div className="flex h-48 items-center justify-center text-sm text-slate-300">
                Content will appear here as components generate
              </div>
            )}
          </div>

          {/* Page number */}
          <div className="absolute bottom-4 left-0 right-0 text-center text-[10px] text-slate-300">
            Page {pageIdx + 1} of {pages.length}
          </div>
        </div>
      ))}
    </div>
  );
}
