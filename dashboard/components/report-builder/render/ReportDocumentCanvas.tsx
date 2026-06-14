'use client';

/**
 * ReportDocumentCanvas — A4 page-based document editor for generated reports.
 *
 * Features:
 * - A4-proportioned pages stacked vertically with page numbers
 * - Blocks appear with soft fade-in animation as they generate
 * - Double-click text to edit inline with floating toolbar (B/I/U)
 * - Hover chart/table → gear icon → config modal
 * - Drag handles + ↑/↓ for reorder
 * - '+' button between blocks to insert new content
 * - Error state rendering with retry suggestion
 * - Generating pulse animation
 * - Print-optimized CSS
 */

import { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  BarChart3,
  Bold,
  ChevronDown,
  ChevronUp,
  FileText,
  FunctionSquare,
  GripVertical,
  Italic,
  Loader2,
  MessageSquare,
  Minus,
  Plus,
  Settings,
  Table2,
  Trash2,
  Type,
  Underline,
} from 'lucide-react';

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

const TEXT_KINDS = new Set([
  'heading', 'narrative', 'key_finding', 'source_note',
  'methodology_note', 'data_caveat', 'footnote', 'glossary_term',
]);

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
      <div className="absolute -top-10 left-0 z-20 flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white px-1 py-0.5 shadow-lg print:hidden">
        <button type="button" className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={() => document.execCommand('bold')}><Bold className="h-3.5 w-3.5" /></button>
        <button type="button" className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={() => document.execCommand('italic')}><Italic className="h-3.5 w-3.5" /></button>
        <button type="button" className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={() => document.execCommand('underline')}><Underline className="h-3.5 w-3.5" /></button>
        <div className="mx-1 h-4 w-px bg-slate-200" />
        <button type="button" className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="Heading"><Type className="h-3.5 w-3.5" /></button>
      </div>
      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        className={`min-h-[1.5em] rounded-md px-1 py-0.5 outline-none ring-2 ring-blue-200 ${fontSize} leading-relaxed text-slate-700`}
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
    { kind: 'key_finding', label: 'Key finding', icon: FileText },
    { kind: 'chart', label: 'Chart placeholder', icon: BarChart3 },
    { kind: 'table', label: 'Table placeholder', icon: Table2 },
    { kind: 'metric', label: 'Metric value', icon: FunctionSquare },
    { kind: 'source_note', label: 'Source note', icon: MessageSquare },
    { kind: 'divider', label: 'Divider line', icon: Minus },
  ];

  return (
    <div className="absolute left-1/2 z-30 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-2 shadow-xl print:hidden" onClick={(e) => e.stopPropagation()}>
      <div className="grid grid-cols-2 gap-1">
        {items.map(({ kind, label, icon: Icon }) => (
          <button
            key={kind}
            type="button"
            onClick={() => { onInsert(kind); onClose(); }}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-800"
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Generating Skeleton ────────────────────────────────────────────────────

function GeneratingSkeleton({ title }: { title?: string }) {
  return (
    <div className="space-y-2 py-1">
      <div className="flex items-center gap-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />
        <span className="text-xs font-medium text-blue-500">Generating{title ? `: ${title}` : ''}...</span>
      </div>
      <div className="space-y-1.5">
        <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
        <div className="h-3 w-4/5 animate-pulse rounded bg-slate-100" style={{ animationDelay: '0.1s' }} />
        <div className="h-3 w-3/5 animate-pulse rounded bg-slate-100" style={{ animationDelay: '0.2s' }} />
      </div>
    </div>
  );
}

// ─── Error Block ────────────────────────────────────────────────────────────

function ErrorBlock({ title }: { title?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 px-3 py-2">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
      <div>
        <p className="text-xs font-medium text-red-600">Failed to generate{title ? `: ${title}` : ''}</p>
        <p className="mt-0.5 text-[10px] text-red-400">This component encountered an error. Use &quot;Redo&quot; to retry.</p>
      </div>
    </div>
  );
}

// ─── Document Block ─────────────────────────────────────────────────────────

function DocumentBlock({
  block,
  onUpdate,
  onReorder,
  onDelete,
  onInsertAfter,
  readOnly,
}: {
  block: DocBlock;
  onUpdate?: (updates: Partial<DocBlock>) => void;
  onReorder?: (dir: 'up' | 'down') => void;
  onDelete?: () => void;
  onInsertAfter?: (kind: DocBlock['kind']) => void;
  readOnly?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [showInsert, setShowInsert] = useState(false);
  const [hovered, setHovered] = useState(false);

  const isTextBlock = TEXT_KINDS.has(block.kind);

  // Divider
  if (block.kind === 'divider') {
    return <div className="my-6 border-t border-slate-200" />;
  }

  // Spacer
  if (block.kind === 'spacer') {
    return <div className="h-10" />;
  }

  // Animation classes
  const animClass = block.status === 'done' ? 'animate-in fade-in slide-in-from-bottom-2 duration-500' : '';

  return (
    <div
      className={`group relative ${animClass}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setShowInsert(false); }}
    >
      {/* Drag handle + controls (appear on hover) */}
      {!readOnly && hovered && (
        <div className="absolute -left-10 top-1 flex flex-col items-center gap-0.5 print:hidden">
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
        <button type="button" onClick={onDelete} className="absolute -right-8 top-1 rounded p-1 text-slate-300 hover:text-red-400 print:hidden" title="Remove block">
          <Trash2 className="h-3 w-3" />
        </button>
      )}

      {/* Block content */}
      <div
        className={`rounded-md px-1 py-1 transition-all ${hovered && !readOnly ? 'bg-slate-50 ring-1 ring-slate-200' : ''} ${block.status === 'pending' ? 'opacity-20' : ''}`}
        onDoubleClick={() => { if (isTextBlock && !readOnly && block.status === 'done') setEditing(true); }}
      >
        {/* ─ Generating state ─ */}
        {block.status === 'generating' && <GeneratingSkeleton title={block.title} />}

        {/* ─ Error state ─ */}
        {block.status === 'error' && <ErrorBlock title={block.title} />}

        {/* ─ Pending ghost ─ */}
        {block.status === 'pending' && (
          <div className="flex items-center gap-2 py-1">
            <span className="h-2 w-2 rounded-full bg-slate-200" />
            <span className="text-[10px] text-slate-300">{block.title || blockLabel(block.kind)}</span>
          </div>
        )}

        {/* ─ Done content ─ */}
        {block.status === 'done' && !editing && (
          <>
            {/* Heading */}
            {block.kind === 'heading' && (
              <h2 className={`font-bold text-slate-800 ${block.level === 1 ? 'mt-6 text-2xl' : block.level === 2 ? 'mt-4 text-xl' : block.level === 3 ? 'mt-3 text-lg' : 'mt-2 text-base'}`}>
                {block.content || 'Untitled'}
              </h2>
            )}

            {/* Narrative */}
            {block.kind === 'narrative' && (
              <p className="text-sm leading-relaxed text-slate-600">
                {block.content || (readOnly ? '' : 'Double-click to edit...')}
              </p>
            )}

            {/* Key finding */}
            {block.kind === 'key_finding' && (
              <div className="rounded-lg border-l-3 border-blue-400 bg-blue-50/50 px-4 py-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-blue-500">Key Finding</p>
                <p className="mt-1 text-sm font-medium leading-relaxed text-slate-700">
                  {block.content || 'Key finding content'}
                </p>
              </div>
            )}

            {/* Source note */}
            {(block.kind === 'source_note' || block.kind === 'footnote') && (
              <p className="text-[11px] italic text-slate-400">
                {block.kind === 'source_note' ? 'Source: ' : ''}{block.content}
              </p>
            )}

            {/* Methodology / data caveat / glossary */}
            {(block.kind === 'methodology_note' || block.kind === 'data_caveat' || block.kind === 'glossary_term') && (
              <div className={`rounded-md px-3 py-2 text-xs ${block.kind === 'data_caveat' ? 'border border-amber-100 bg-amber-50 text-amber-700' : 'bg-slate-50 text-slate-500'}`}>
                <span className="font-semibold">{blockLabel(block.kind)}:</span> {block.content}
              </div>
            )}

            {/* Chart block */}
            {block.kind === 'chart' && (
              <div className="relative my-3 overflow-hidden rounded-xl border border-slate-100 bg-gradient-to-br from-slate-50 to-white">
                <div className="flex h-48 items-center justify-center">
                  <div className="text-center">
                    <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50">
                      <BarChart3 className="h-7 w-7 text-blue-300" />
                    </div>
                    <p className="text-sm font-medium text-slate-500">{block.title || 'Chart'}</p>
                    <p className="mt-1 text-[10px] text-slate-300">Chart visualization will render here</p>
                  </div>
                </div>
                {!readOnly && hovered && (
                  <button type="button" className="absolute right-3 top-3 rounded-full border border-slate-200 bg-white p-2 text-slate-400 shadow-sm hover:text-slate-600 print:hidden" title="Configure chart">
                    <Settings className="h-4 w-4" />
                  </button>
                )}
              </div>
            )}

            {/* Table block */}
            {block.kind === 'table' && (
              <div className="relative my-3 overflow-hidden rounded-xl border border-slate-100 bg-slate-50/50">
                <div className="flex h-28 items-center justify-center">
                  <div className="text-center">
                    <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50">
                      <Table2 className="h-5 w-5 text-emerald-300" />
                    </div>
                    <p className="text-xs font-medium text-slate-500">{block.title || 'Data table'}</p>
                  </div>
                </div>
                {!readOnly && hovered && (
                  <button type="button" className="absolute right-3 top-3 rounded-full border border-slate-200 bg-white p-2 text-slate-400 shadow-sm hover:text-slate-600 print:hidden" title="Configure table">
                    <Settings className="h-4 w-4" />
                  </button>
                )}
              </div>
            )}

            {/* Metric block */}
            {block.kind === 'metric' && (
              <div className="my-3 rounded-xl border border-slate-100 bg-gradient-to-br from-blue-50/50 to-white px-5 py-4">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{block.title || 'Metric'}</p>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-3xl font-bold tabular-nums text-blue-600">{block.metricValue || '—'}</span>
                  {block.metricUnit && <span className="text-sm text-slate-400">{block.metricUnit}</span>}
                </div>
                {block.content && <p className="mt-2 text-xs text-slate-400">{block.content}</p>}
              </div>
            )}
          </>
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
      </div>

      {/* Insert button between blocks */}
      {!readOnly && (
        <div className="relative flex h-4 items-center justify-center print:hidden">
          {hovered && (
            <button
              type="button"
              onClick={() => setShowInsert(!showInsert)}
              className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm transition-all hover:border-blue-300 hover:text-blue-500"
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
  // Split blocks into pages (~10 blocks per page for A4 proportion)
  const BLOCKS_PER_PAGE = 8;
  const pages: DocBlock[][] = [];
  for (let i = 0; i < blocks.length; i += BLOCKS_PER_PAGE) {
    pages.push(blocks.slice(i, i + BLOCKS_PER_PAGE));
  }
  if (pages.length === 0) pages.push([]);

  // Count done vs total for progress indicator
  const doneCount = blocks.filter((b) => b.status === 'done').length;
  const totalContent = blocks.filter((b) => b.kind !== 'heading' && b.kind !== 'divider' && b.kind !== 'spacer').length;

  return (
    <div className={`space-y-8 ${className || ''}`}>
      {/* Document info bar (print-hidden) */}
      {totalContent > 0 && (
        <div className="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-2 text-[10px] text-slate-400 print:hidden">
          <span>{blocks.length} blocks across {pages.length} page{pages.length !== 1 ? 's' : ''}</span>
          <span>{doneCount}/{totalContent} content blocks generated</span>
        </div>
      )}

      {pages.map((pageBlocks, pageIdx) => (
        <div
          key={pageIdx}
          className="a4-page relative mx-auto w-[210mm] min-h-[297mm] rounded-sm border border-slate-200 bg-white px-[25mm] py-[20mm] shadow-md print:border-0 print:shadow-none print:m-0 print:rounded-none"
          style={{ maxWidth: '794px' }}
        >
          {/* Page content */}
          <div className="space-y-2">
            {pageBlocks.map((block) => (
              <DocumentBlock
                key={block.id}
                block={block}
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
          <div className="absolute bottom-4 left-0 right-0 text-center text-[10px] text-slate-300 print:text-slate-500">
            Page {pageIdx + 1} of {pages.length}
          </div>
        </div>
      ))}
    </div>
  );
}
