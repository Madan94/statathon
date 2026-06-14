'use client';

/**
 * ReportDocumentCanvas — Enterprise A4 document editor.
 *
 * Government publication-grade canvas for MoSPI statistical reports.
 * Clean, print-ready, officer-optimized layout with full inline editing.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Bold,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  FileText,
  FunctionSquare,
  GripVertical,
  Italic,
  Loader2,
  MessageSquare,
  Minus,
  MoreHorizontal,
  Pencil,
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
  level?: number;
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

function formatNumber(n: string | number | undefined): string {
  if (n === undefined || n === null || n === '') return '—';
  const num = typeof n === 'string' ? parseFloat(n) : n;
  if (isNaN(num)) return String(n);
  if (Math.abs(num) >= 1e7) return (num / 1e7).toFixed(2) + ' Cr';
  if (Math.abs(num) >= 1e5) return (num / 1e5).toFixed(2) + ' L';
  if (Math.abs(num) >= 1000) return num.toLocaleString('en-IN');
  if (Number.isInteger(num)) return String(num);
  return num.toFixed(2);
}

// ─── Floating Toolbar ───────────────────────────────────────────────────────

function FloatingToolbar({ onClose }: { onClose: () => void }) {
  const exec = (cmd: string) => { document.execCommand(cmd); };
  return (
    <div className="absolute -top-11 left-0 z-30 flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white px-1.5 py-1 shadow-xl print:hidden">
      <button type="button" className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800" onClick={() => exec('bold')} title="Bold"><Bold className="h-3.5 w-3.5" /></button>
      <button type="button" className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800" onClick={() => exec('italic')} title="Italic"><Italic className="h-3.5 w-3.5" /></button>
      <button type="button" className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800" onClick={() => exec('underline')} title="Underline"><Underline className="h-3.5 w-3.5" /></button>
      <div className="mx-0.5 h-4 w-px bg-slate-200" />
      <button type="button" className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800" onClick={() => exec('removeFormat')} title="Clear formatting"><Type className="h-3.5 w-3.5" /></button>
      <div className="mx-0.5 h-4 w-px bg-slate-200" />
      <button type="button" className="rounded-md px-2 py-1 text-[10px] font-semibold text-emerald-600 hover:bg-emerald-50" onClick={onClose} title="Done editing"><Check className="mr-0.5 inline h-3 w-3" />Done</button>
    </div>
  );
}

// ─── Inline Editor ──────────────────────────────────────────────────────────

function InlineEditor({ value, onChange, onBlur, level }: {
  value: string; onChange: (v: string) => void; onBlur: () => void; level?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    ref.current.focus();
    const range = document.createRange();
    const sel = window.getSelection();
    range.selectNodeContents(ref.current);
    range.collapse(false);
    sel?.removeAllRanges();
    sel?.addRange(range);
  }, []);

  const fontSize = level === 1 ? 'text-[22px] font-bold' : level === 2 ? 'text-[18px] font-bold' : level === 3 ? 'text-[15px] font-semibold' : 'text-[13px]';
  return (
    <div className="relative">
      <FloatingToolbar onClose={onBlur} />
      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        className={`min-h-[1.8em] rounded px-0.5 py-0.5 outline-none ring-2 ring-blue-300/50 ${fontSize} leading-[1.7] text-slate-800`}
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
  const items: { kind: DocBlock['kind']; label: string; icon: typeof FileText; desc: string }[] = [
    { kind: 'narrative', label: 'Paragraph', icon: FileText, desc: 'Body text' },
    { kind: 'heading', label: 'Heading', icon: Type, desc: 'Section title' },
    { kind: 'key_finding', label: 'Key finding', icon: FileText, desc: 'Highlight box' },
    { kind: 'chart', label: 'Chart', icon: BarChart3, desc: 'Data chart' },
    { kind: 'table', label: 'Table', icon: Table2, desc: 'Data table' },
    { kind: 'metric', label: 'Metric', icon: FunctionSquare, desc: 'KPI card' },
    { kind: 'source_note', label: 'Source note', icon: MessageSquare, desc: 'Attribution' },
    { kind: 'divider', label: 'Divider', icon: Minus, desc: 'Line break' },
  ];
  return (
    <div className="absolute left-1/2 z-40 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-1.5 shadow-2xl print:hidden" onClick={(e) => e.stopPropagation()}>
      <div className="grid grid-cols-2 gap-0.5">
        {items.map(({ kind, label, icon: Icon, desc }) => (
          <button key={kind} type="button" onClick={() => { onInsert(kind); onClose(); }}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-colors hover:bg-slate-50">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-400"><Icon className="h-3.5 w-3.5" /></span>
            <span>
              <span className="block text-xs font-medium text-slate-700">{label}</span>
              <span className="block text-[9px] text-slate-400">{desc}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Block Shimmer (generating) ─────────────────────────────────────────────

function BlockShimmer({ title, kind }: { title?: string; kind: string }) {
  const isChart = kind === 'chart';
  const isTable = kind === 'table';
  const isMetric = kind === 'metric' || kind === 'formula_metric';
  return (
    <div className="py-2">
      <div className="mb-2 flex items-center gap-2">
        <div className="relative h-3 w-3">
          <div className="absolute inset-0 animate-ping rounded-full bg-blue-400/30" />
          <div className="absolute inset-0.5 rounded-full bg-blue-500" />
        </div>
        <span className="text-[11px] font-medium text-blue-600">
          {isChart ? 'Rendering chart' : isTable ? 'Building table' : isMetric ? 'Computing metric' : 'Writing'}{title ? ` · ${title}` : ''}
        </span>
      </div>
      <div className="space-y-2">
        {isChart ? (
          <div className="flex h-32 items-end gap-1.5 rounded-lg bg-gradient-to-t from-slate-50 to-white px-4 pb-3 pt-6">
            {[40, 65, 55, 80, 45, 72, 60, 50, 75, 68].map((h, i) => (
              <div key={i} className="flex-1 animate-pulse rounded-t bg-blue-100/60" style={{ height: `${h}%`, animationDelay: `${i * 80}ms` }} />
            ))}
          </div>
        ) : isTable ? (
          <div className="space-y-1 rounded-lg bg-slate-50/50 p-3">
            <div className="flex gap-2">
              {[1, 2, 3, 4].map((i) => <div key={i} className="h-3 flex-1 animate-pulse rounded bg-slate-200/60" style={{ animationDelay: `${i * 50}ms` }} />)}
            </div>
            {[1, 2, 3].map((r) => (
              <div key={r} className="flex gap-2">
                {[1, 2, 3, 4].map((c) => <div key={c} className="h-2.5 flex-1 animate-pulse rounded bg-slate-100/80" style={{ animationDelay: `${(r * 4 + c) * 40}ms` }} />)}
              </div>
            ))}
          </div>
        ) : isMetric ? (
          <div className="flex items-baseline gap-3 py-2">
            <div className="h-8 w-24 animate-pulse rounded-lg bg-blue-100/60" />
            <div className="h-3 w-10 animate-pulse rounded bg-slate-100" />
          </div>
        ) : (
          <div className="space-y-1.5">
            <div className="h-[11px] w-full animate-pulse rounded-sm bg-slate-100/80" />
            <div className="h-[11px] w-[92%] animate-pulse rounded-sm bg-slate-100/60" style={{ animationDelay: '80ms' }} />
            <div className="h-[11px] w-[78%] animate-pulse rounded-sm bg-slate-100/40" style={{ animationDelay: '160ms' }} />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Context Menu ───────────────────────────────────────────────────────────

function BlockContextMenu({ onEdit, onCopy, onDelete, onClose }: {
  onEdit: () => void; onCopy: () => void; onDelete: () => void; onClose: () => void;
}) {
  return (
    <div className="absolute right-0 top-7 z-40 w-40 rounded-xl border border-slate-200 bg-white py-1 shadow-xl print:hidden" onClick={(e) => e.stopPropagation()}>
      <button type="button" onClick={() => { onEdit(); onClose(); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"><Pencil className="h-3 w-3" /> Edit text</button>
      <button type="button" onClick={() => { onCopy(); onClose(); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"><Copy className="h-3 w-3" /> Copy</button>
      <div className="my-1 border-t border-slate-100" />
      <button type="button" onClick={() => { onDelete(); onClose(); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-red-500 hover:bg-red-50"><Trash2 className="h-3 w-3" /> Remove</button>
    </div>
  );
}

// ─── Document Block ─────────────────────────────────────────────────────────

function DocumentBlock({
  block, onUpdate, onReorder, onDelete, onInsertAfter, readOnly,
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
  const [showMenu, setShowMenu] = useState(false);
  const [hovered, setHovered] = useState(false);

  const isTextBlock = TEXT_KINDS.has(block.kind);

  const handleCopy = useCallback(() => {
    const text = block.content || block.metricValue || '';
    navigator.clipboard.writeText(text).catch(() => {});
  }, [block]);

  // ── Divider ──
  if (block.kind === 'divider') {
    return (
      <div className="group relative my-5 flex items-center print:my-3" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
        <div className="h-px flex-1 bg-slate-200" />
        {!readOnly && hovered && (
          <button type="button" onClick={onDelete} className="absolute -right-6 rounded p-0.5 text-slate-300 hover:text-red-400 print:hidden"><Trash2 className="h-2.5 w-2.5" /></button>
        )}
      </div>
    );
  }

  // ── Spacer ──
  if (block.kind === 'spacer') return <div className="h-6 print:h-4" />;

  return (
    <div
      className="group/block relative"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setShowMenu(false); setShowInsert(false); }}
    >
      {/* ── Side controls ── */}
      {!readOnly && hovered && block.status === 'done' && (
        <div className="absolute -left-8 top-0.5 flex flex-col items-center gap-px print:hidden">
          <button type="button" onClick={() => onReorder?.('up')} className="rounded p-0.5 text-slate-300 transition-colors hover:text-slate-600" title="Move up"><ChevronUp className="h-3 w-3" /></button>
          <GripVertical className="h-3 w-3 cursor-grab text-slate-200 transition-colors hover:text-slate-400" />
          <button type="button" onClick={() => onReorder?.('down')} className="rounded p-0.5 text-slate-300 transition-colors hover:text-slate-600" title="Move down"><ChevronDown className="h-3 w-3" /></button>
        </div>
      )}

      {/* ── Top-right menu ── */}
      {!readOnly && hovered && block.status === 'done' && (
        <div className="absolute -right-7 top-0 print:hidden">
          <button type="button" onClick={() => setShowMenu(!showMenu)} className="rounded p-1 text-slate-300 transition-colors hover:text-slate-500"><MoreHorizontal className="h-3.5 w-3.5" /></button>
          {showMenu && <BlockContextMenu onEdit={() => { if (isTextBlock) setEditing(true); }} onCopy={handleCopy} onDelete={() => onDelete?.()} onClose={() => setShowMenu(false)} />}
        </div>
      )}

      {/* ── Block body ── */}
      <div
        className={`relative rounded transition-all duration-150 ${
          hovered && !readOnly && block.status === 'done' ? 'bg-blue-50/30' : ''
        } ${block.status === 'pending' ? 'opacity-[0.15]' : ''}`}
        onDoubleClick={() => { if (isTextBlock && !readOnly && block.status === 'done') setEditing(true); }}
      >
        {/* ── Generating ── */}
        {block.status === 'generating' && <BlockShimmer title={block.title} kind={block.kind} />}

        {/* ── Error ── */}
        {block.status === 'error' && (
          <div className="flex items-start gap-3 rounded-lg border border-red-200/60 bg-red-50/50 px-4 py-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
            <div className="min-w-0">
              <p className="text-[12px] font-medium text-red-700">Generation failed{block.title ? ` — ${block.title}` : ''}</p>
              <p className="mt-0.5 text-[10px] leading-relaxed text-red-400">Click &quot;Redo&quot; in the toolbar above to retry this component.</p>
            </div>
          </div>
        )}

        {/* ── Pending ghost ── */}
        {block.status === 'pending' && (
          <div className="flex items-center gap-2 py-2">
            <div className="h-1.5 w-1.5 rounded-full bg-slate-200" />
            <span className="text-[10px] tracking-wide text-slate-300">{block.title || blockLabel(block.kind)}</span>
          </div>
        )}

        {/* ── Rendered content ── */}
        {block.status === 'done' && !editing && (
          <>
            {/* HEADING */}
            {block.kind === 'heading' && (() => {
              const lvl = block.level || 2;
              const cls = lvl === 1
                ? 'mb-1 mt-8 text-[20px] font-bold leading-tight tracking-tight text-slate-900 first:mt-0 print:text-[18pt]'
                : lvl === 2
                  ? 'mb-0.5 mt-6 text-[16px] font-bold leading-snug text-slate-800 first:mt-0 print:text-[14pt]'
                  : 'mb-0.5 mt-4 text-[13px] font-semibold leading-snug text-slate-700 first:mt-0 print:text-[11pt]';
              return <div className={cls}>{block.content || 'Untitled'}</div>;
            })()}

            {/* NARRATIVE */}
            {block.kind === 'narrative' && (
              <p className="py-0.5 text-[12.5px] leading-[1.75] text-slate-600 print:text-[10pt] print:leading-[1.6]">
                {block.content || (readOnly ? '' : 'Double-click to edit...')}
              </p>
            )}

            {/* KEY FINDING */}
            {block.kind === 'key_finding' && (
              <div className="my-2 rounded-lg bg-gradient-to-r from-blue-50 to-indigo-50/30 px-4 py-3 print:border print:border-slate-300">
                <div className="mb-1 flex items-center gap-1.5">
                  <div className="h-1 w-1 rounded-full bg-blue-500" />
                  <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-blue-600">Key Finding</span>
                </div>
                <p className="text-[12.5px] font-medium leading-[1.7] text-slate-700">{block.content}</p>
              </div>
            )}

            {/* SOURCE NOTE / FOOTNOTE */}
            {(block.kind === 'source_note' || block.kind === 'footnote') && (
              <p className="py-0.5 text-[10px] leading-relaxed text-slate-400 print:text-[8pt]">
                {block.kind === 'source_note' && <span className="font-semibold text-slate-500">Source: </span>}
                {block.content}
              </p>
            )}

            {/* METHODOLOGY / CAVEAT / GLOSSARY */}
            {(block.kind === 'methodology_note' || block.kind === 'data_caveat' || block.kind === 'glossary_term') && (
              <div className={`my-1.5 rounded-md px-3.5 py-2.5 text-[11px] leading-relaxed ${
                block.kind === 'data_caveat'
                  ? 'border border-amber-200/60 bg-amber-50/40 text-amber-800'
                  : 'bg-slate-50/80 text-slate-500'
              }`}>
                <span className="font-semibold">{blockLabel(block.kind)}: </span>{block.content}
              </div>
            )}

            {/* CHART */}
            {block.kind === 'chart' && (
              <div className="group/chart relative my-3 overflow-hidden rounded-lg border border-slate-200/70 bg-white print:border-slate-300">
                <div className="border-b border-slate-100 bg-slate-50/50 px-4 py-2">
                  <p className="text-[11px] font-semibold text-slate-600">{block.title || 'Chart'}</p>
                </div>
                <div className="flex h-44 items-center justify-center bg-gradient-to-b from-white to-slate-50/30 px-6">
                  <div className="flex h-full w-full items-end gap-[3%] pb-8 pt-4">
                    {[62, 85, 48, 73, 55, 90, 40, 68, 78, 52].map((h, i) => (
                      <div key={i} className="flex-1 rounded-t transition-all" style={{ height: `${h}%`, background: `hsl(${210 + i * 4}, 60%, ${65 + i * 2}%)` }} />
                    ))}
                  </div>
                </div>
                <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50/30 px-4 py-1.5">
                  <span className="text-[9px] text-slate-400">Visualization renders after full assembly</span>
                  {!readOnly && <button type="button" className="rounded-md p-1 text-slate-400 opacity-0 transition-opacity group-hover/chart:opacity-100 hover:text-slate-600 print:hidden" title="Chart settings"><Settings className="h-3.5 w-3.5" /></button>}
                </div>
              </div>
            )}

            {/* TABLE */}
            {block.kind === 'table' && (
              <div className="group/table relative my-3 overflow-hidden rounded-lg border border-slate-200/70 bg-white print:border-slate-300">
                <div className="border-b border-slate-100 bg-slate-50/50 px-4 py-2">
                  <p className="text-[11px] font-semibold text-slate-600">{block.title || 'Data Table'}</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50/80">
                        <th className="px-3 py-2 text-left font-semibold text-slate-500">Rank</th>
                        <th className="px-3 py-2 text-left font-semibold text-slate-500">State/UT</th>
                        <th className="px-3 py-2 text-right font-semibold text-slate-500">Value</th>
                        <th className="px-3 py-2 text-right font-semibold text-slate-500">Share %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[1, 2, 3, 4, 5].map((r) => (
                        <tr key={r} className="border-b border-slate-100 last:border-b-0">
                          <td className="px-3 py-1.5 tabular-nums text-slate-400">{r}</td>
                          <td className="px-3 py-1.5 text-slate-600">—</td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-slate-600">—</td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">—</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50/30 px-4 py-1.5">
                  <span className="text-[9px] text-slate-400">Data populates after full assembly</span>
                  {!readOnly && <button type="button" className="rounded-md p-1 text-slate-400 opacity-0 transition-opacity group-hover/table:opacity-100 hover:text-slate-600 print:hidden" title="Table settings"><Settings className="h-3.5 w-3.5" /></button>}
                </div>
              </div>
            )}

            {/* METRIC */}
            {block.kind === 'metric' && (
              <div className="my-3 rounded-lg border border-slate-200/70 bg-gradient-to-br from-white via-blue-50/20 to-white px-5 py-4 print:border-slate-300">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-slate-400">{block.title || 'Metric'}</p>
                    <div className="mt-1.5 flex items-baseline gap-2">
                      <span className="text-[28px] font-bold tabular-nums leading-none text-slate-800">{formatNumber(block.metricValue)}</span>
                      {block.metricUnit && <span className="text-[12px] font-medium text-slate-400">{block.metricUnit}</span>}
                    </div>
                  </div>
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-400">
                    <FunctionSquare className="h-5 w-5" />
                  </div>
                </div>
                {block.content && <p className="mt-2.5 text-[11px] leading-relaxed text-slate-500">{block.content}</p>}
              </div>
            )}
          </>
        )}

        {/* ── Inline editor ── */}
        {editing && (
          <InlineEditor
            value={block.content}
            level={block.kind === 'heading' ? block.level : undefined}
            onChange={(v) => onUpdate?.({ content: v })}
            onBlur={() => setEditing(false)}
          />
        )}
      </div>

      {/* ── Insert between blocks ── */}
      {!readOnly && (
        <div className="relative flex h-3 items-center justify-center print:hidden">
          <div className={`absolute inset-x-0 top-1/2 h-px transition-colors ${showInsert ? 'bg-blue-200' : hovered ? 'bg-slate-100' : 'bg-transparent'}`} />
          {hovered && (
            <button
              type="button"
              onClick={() => setShowInsert(!showInsert)}
              className="relative z-10 flex h-4 w-4 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm transition-all hover:border-blue-300 hover:text-blue-500 hover:shadow"
            >
              <Plus className="h-2.5 w-2.5" />
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
  blocks, onUpdateBlock, onReorderBlock, onDeleteBlock, onInsertBlock,
  readOnly = false, className,
}: ReportDocumentCanvasProps) {
  const BLOCKS_PER_PAGE = 10;
  const pages: DocBlock[][] = [];
  for (let i = 0; i < blocks.length; i += BLOCKS_PER_PAGE) {
    pages.push(blocks.slice(i, i + BLOCKS_PER_PAGE));
  }
  if (pages.length === 0) pages.push([]);

  const doneCount = blocks.filter((b) => b.status === 'done').length;
  const totalContent = blocks.filter((b) => b.kind !== 'divider' && b.kind !== 'spacer').length;
  const generatingCount = blocks.filter((b) => b.status === 'generating').length;

  return (
    <div className={`${className || ''}`}>
      {/* ── Document status strip ── */}
      {totalContent > 0 && (
        <div className="mb-6 flex items-center justify-between px-1 text-[10px] text-slate-400 print:hidden">
          <div className="flex items-center gap-3">
            <span className="font-medium text-slate-500">{pages.length} page{pages.length !== 1 ? 's' : ''}</span>
            <span className="text-slate-300">·</span>
            <span>{blocks.length} blocks</span>
            {generatingCount > 0 && (
              <>
                <span className="text-slate-300">·</span>
                <span className="flex items-center gap-1 text-blue-500"><Loader2 className="h-2.5 w-2.5 animate-spin" />{generatingCount} generating</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex h-1 w-20 overflow-hidden rounded-full bg-slate-100">
              <div className="rounded-full bg-emerald-400 transition-all duration-700" style={{ width: `${totalContent ? (doneCount / totalContent) * 100 : 0}%` }} />
            </div>
            <span className="tabular-nums">{doneCount}/{totalContent}</span>
          </div>
        </div>
      )}

      {/* ── Pages ── */}
      <div className="space-y-10 print:space-y-0">
        {pages.map((pageBlocks, pageIdx) => (
          <div
            key={pageIdx}
            className="a4-page relative mx-auto bg-white print:m-0 print:rounded-none print:border-0 print:shadow-none"
            style={{
              width: '210mm',
              maxWidth: '794px',
              minHeight: '297mm',
              padding: '22mm 28mm 25mm 28mm',
              boxShadow: '0 1px 3px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.04)',
              borderRadius: '2px',
            }}
          >
            {/* Page content */}
            <div className="space-y-0.5">
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

              {pageBlocks.length === 0 && (
                <div className="flex h-60 flex-col items-center justify-center text-slate-300">
                  <FileText className="mb-3 h-8 w-8 text-slate-200" />
                  <p className="text-sm">Content will appear as components generate</p>
                  <p className="mt-1 text-[10px]">Use &quot;Generate&quot; or &quot;Auto-generate all&quot; to begin</p>
                </div>
              )}
            </div>

            {/* Page footer */}
            <div className="absolute bottom-[12mm] left-[28mm] right-[28mm] flex items-center justify-between text-[8px] text-slate-300 print:text-slate-400">
              <span>BharatStat Intelligence Report</span>
              <span className="tabular-nums">Page {pageIdx + 1} of {pages.length}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
