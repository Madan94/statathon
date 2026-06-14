'use client';

/**
 * ReportDocumentCanvas — Next-gen A4 document editor for MoSPI reports.
 *
 * Renders real ranking/aggregation data from the generation backend,
 * auto-generates cover page + table of contents, and provides
 * officer-grade inline editing with full keyboard support.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ArrowUpRight, BarChart3, Bold, Check, ChevronDown, ChevronUp,
  Copy, FileText, FunctionSquare, GripVertical, Hash, Italic, Layers,
  Loader2, MessageSquare, Minus, MoreHorizontal, Pencil, Plus,
  Settings, Table2, Trash2, TrendingUp, Type, Underline,
} from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════════════
   TYPES
   ═══════════════════════════════════════════════════════════════════════════ */

export interface DocBlock {
  id: string;
  kind: 'heading' | 'narrative' | 'key_finding' | 'chart' | 'table' | 'metric'
      | 'source_note' | 'methodology_note' | 'data_caveat' | 'footnote'
      | 'glossary_term' | 'divider' | 'spacer';
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
  reportTitle?: string;
  reportSubtitle?: string;
}

/* ═══════════════════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════════════════ */

const TEXT_KINDS = new Set<string>([
  'heading', 'narrative', 'key_finding', 'source_note',
  'methodology_note', 'data_caveat', 'footnote', 'glossary_term',
]);

function blockLabel(kind: string): string {
  return kind.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtNum(n: string | number | undefined): string {
  if (n == null || n === '') return '—';
  const v = typeof n === 'string' ? parseFloat(n) : n;
  if (isNaN(v)) return String(n);
  if (Math.abs(v) >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
  if (Math.abs(v) >= 1e5) return (v / 1e5).toFixed(2) + ' L';
  if (Math.abs(v) >= 1000) return v.toLocaleString('en-IN', { maximumFractionDigits: 1 });
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}

function wordCount(blocks: DocBlock[]): number {
  return blocks.reduce((n, b) => n + (b.content || '').split(/\s+/).filter(Boolean).length, 0);
}

function readingTime(words: number): string {
  const mins = Math.max(1, Math.ceil(words / 200));
  return `${mins} min read`;
}

function extractToc(blocks: DocBlock[]): { id: string; text: string; level: number }[] {
  return blocks
    .filter((b) => b.kind === 'heading' && b.status === 'done' && b.content)
    .map((b) => ({ id: b.id, text: b.content, level: b.level || 2 }));
}

/* ranking/aggregation items from backend content */
interface RankItem { rank?: number; key?: Record<string, string>; value?: number; rowIds?: string[] }
interface AggRow  { [k: string]: string | number | null }

function parseRankingItems(block: DocBlock): RankItem[] {
  const raw = (block.tableData as Record<string, unknown>)
    || (block as unknown as Record<string, unknown>);
  const items = (raw.items || raw.rankingData || raw.rows || []) as RankItem[];
  return Array.isArray(items) ? items : [];
}

function parseAggRows(block: DocBlock): AggRow[] {
  const raw = (block.tableData as Record<string, unknown>)
    || (block as unknown as Record<string, unknown>);
  const rows = (raw.rows || raw.aggregationData || raw.items || []) as AggRow[];
  return Array.isArray(rows) ? rows : [];
}

/* ═══════════════════════════════════════════════════════════════════════════
   FLOATING TOOLBAR
   ═══════════════════════════════════════════════════════════════════════════ */

function FloatingToolbar({ onClose }: { onClose: () => void }) {
  const exec = (cmd: string) => document.execCommand(cmd);
  return (
    <div className="absolute -top-11 left-0 z-30 flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white px-1.5 py-1 shadow-xl print:hidden">
      {[
        { cmd: 'bold', icon: Bold, key: 'B' },
        { cmd: 'italic', icon: Italic, key: 'I' },
        { cmd: 'underline', icon: Underline, key: 'U' },
      ].map(({ cmd, icon: Icon, key }) => (
        <button key={cmd} type="button" title={`${cmd} (Ctrl+${key})`}
          className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800"
          onClick={() => exec(cmd)}><Icon className="h-3.5 w-3.5" /></button>
      ))}
      <div className="mx-0.5 h-4 w-px bg-slate-200" />
      <button type="button" title="Clear formatting"
        className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800"
        onClick={() => exec('removeFormat')}><Type className="h-3.5 w-3.5" /></button>
      <div className="mx-0.5 h-4 w-px bg-slate-200" />
      <button type="button" title="Done editing"
        className="rounded-md px-2 py-1 text-[10px] font-semibold text-emerald-600 hover:bg-emerald-50"
        onClick={onClose}><Check className="mr-0.5 inline h-3 w-3" />Done</button>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   INLINE EDITOR
   ═══════════════════════════════════════════════════════════════════════════ */

function InlineEditor({ value, onChange, onBlur, level }: {
  value: string; onChange: (v: string) => void; onBlur: () => void; level?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    ref.current.focus();
    const r = document.createRange(), s = window.getSelection();
    r.selectNodeContents(ref.current); r.collapse(false);
    s?.removeAllRanges(); s?.addRange(r);
  }, []);
  const sz = level === 1 ? 'text-[22px] font-bold' : level === 2 ? 'text-[18px] font-bold' : level === 3 ? 'text-[15px] font-semibold' : 'text-[13px]';
  return (
    <div className="relative">
      <FloatingToolbar onClose={onBlur} />
      <div ref={ref} contentEditable suppressContentEditableWarning
        className={`min-h-[1.8em] rounded px-0.5 py-0.5 outline-none ring-2 ring-blue-300/40 ${sz} leading-[1.7] text-slate-800`}
        onInput={(e) => onChange((e.target as HTMLDivElement).innerText)}
        onBlur={onBlur} onKeyDown={(e) => { if (e.key === 'Escape') onBlur(); }}
        dangerouslySetInnerHTML={{ __html: value }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   INSERT MENU
   ═══════════════════════════════════════════════════════════════════════════ */

function InsertMenu({ onInsert, onClose }: { onInsert: (k: DocBlock['kind']) => void; onClose: () => void }) {
  const items: { kind: DocBlock['kind']; label: string; icon: typeof FileText; desc: string }[] = [
    { kind: 'narrative', label: 'Paragraph', icon: FileText, desc: 'Body text' },
    { kind: 'heading', label: 'Heading', icon: Type, desc: 'Section title' },
    { kind: 'key_finding', label: 'Key finding', icon: TrendingUp, desc: 'Highlight box' },
    { kind: 'chart', label: 'Chart', icon: BarChart3, desc: 'Data chart' },
    { kind: 'table', label: 'Table', icon: Table2, desc: 'Data table' },
    { kind: 'metric', label: 'Metric', icon: FunctionSquare, desc: 'KPI card' },
    { kind: 'source_note', label: 'Source note', icon: MessageSquare, desc: 'Attribution' },
    { kind: 'divider', label: 'Divider', icon: Minus, desc: 'Separator' },
  ];
  return (
    <div className="absolute left-1/2 z-40 -translate-x-1/2 rounded-xl border border-slate-200/80 bg-white/95 p-1.5 shadow-2xl backdrop-blur-sm print:hidden" onClick={(e) => e.stopPropagation()}>
      <div className="grid grid-cols-2 gap-0.5">
        {items.map(({ kind, label, icon: Icon, desc }) => (
          <button key={kind} type="button" onClick={() => { onInsert(kind); onClose(); }}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-all hover:bg-slate-50 active:scale-[0.98]">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-400"><Icon className="h-3.5 w-3.5" /></span>
            <span><span className="block text-xs font-medium text-slate-700">{label}</span><span className="block text-[9px] text-slate-400">{desc}</span></span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   GENERATING SHIMMER — type-aware skeleton
   ═══════════════════════════════════════════════════════════════════════════ */

function BlockShimmer({ title, kind }: { title?: string; kind: string }) {
  const isChart = kind === 'chart', isTable = kind === 'table', isMetric = kind === 'metric' || kind === 'formula_metric';
  return (
    <div className="py-2">
      <div className="mb-2.5 flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5"><span className="absolute inset-0 animate-ping rounded-full bg-blue-400/40" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-blue-500" /></span>
        <span className="text-[11px] font-medium text-blue-600">{isChart ? 'Rendering chart' : isTable ? 'Building table' : isMetric ? 'Computing' : 'Writing'}{title ? ` · ${title}` : ''}</span>
      </div>
      {isChart ? (
        <div className="flex h-36 items-end gap-[3%] rounded-lg bg-gradient-to-t from-slate-50 to-white px-5 pb-4 pt-6">
          {[38, 62, 48, 78, 42, 85, 55, 70, 65, 50, 72, 58].map((h, i) => (
            <div key={i} className="flex-1 animate-pulse rounded-t" style={{ height: `${h}%`, background: `hsl(${215 + i * 3}, 55%, ${72 - i}%)`, animationDelay: `${i * 70}ms` }} />
          ))}
        </div>
      ) : isTable ? (
        <div className="space-y-px overflow-hidden rounded-lg border border-slate-100">
          <div className="flex gap-px bg-slate-50">
            {[1,2,3,4].map(i => <div key={i} className="h-7 flex-1 animate-pulse bg-slate-100" style={{ animationDelay: `${i*40}ms` }} />)}
          </div>
          {[1,2,3,4].map(r => (
            <div key={r} className="flex gap-px bg-white">
              {[1,2,3,4].map(c => <div key={c} className="h-6 flex-1 animate-pulse bg-slate-50/60" style={{ animationDelay: `${(r*4+c)*30}ms` }} />)}
            </div>
          ))}
        </div>
      ) : isMetric ? (
        <div className="flex items-end gap-3 py-3">
          <div className="h-9 w-28 animate-pulse rounded-lg bg-gradient-to-r from-blue-100/80 to-blue-50/40" />
          <div className="mb-1 h-3 w-12 animate-pulse rounded bg-slate-100" />
        </div>
      ) : (
        <div className="space-y-[5px]">
          {[100, 94, 88, 72].map((w, i) => (
            <div key={i} className="h-[10px] animate-pulse rounded-sm bg-slate-100/80" style={{ width: `${w}%`, animationDelay: `${i * 60}ms` }} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CONTEXT MENU
   ═══════════════════════════════════════════════════════════════════════════ */

function BlockContextMenu({ isText, onEdit, onCopy, onDelete, onClose }: {
  isText: boolean; onEdit: () => void; onCopy: () => void; onDelete: () => void; onClose: () => void;
}) {
  return (
    <div className="absolute right-0 top-7 z-40 min-w-[140px] rounded-xl border border-slate-200/80 bg-white/95 py-1 shadow-xl backdrop-blur-sm print:hidden" onClick={(e) => e.stopPropagation()}>
      {isText && <button type="button" onClick={() => { onEdit(); onClose(); }} className="flex w-full items-center gap-2.5 px-3 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"><Pencil className="h-3 w-3" />Edit text</button>}
      <button type="button" onClick={() => { onCopy(); onClose(); }} className="flex w-full items-center gap-2.5 px-3 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"><Copy className="h-3 w-3" />Copy content</button>
      <div className="my-1 border-t border-slate-100" />
      <button type="button" onClick={() => { onDelete(); onClose(); }} className="flex w-full items-center gap-2.5 px-3 py-1.5 text-[11px] text-red-500 hover:bg-red-50"><Trash2 className="h-3 w-3" />Remove block</button>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   REAL DATA TABLE — renders ranking items / aggregation rows
   ═══════════════════════════════════════════════════════════════════════════ */

function RankingTable({ items, title, measure }: { items: RankItem[]; title?: string; measure?: string }) {
  if (!items.length) return null;
  const keyLabels = items[0]?.key ? Object.keys(items[0].key) : [];
  const total = items.reduce((s, i) => s + (i.value || 0), 0);
  return (
    <div className="my-3 overflow-hidden rounded-lg border border-slate-200/60 print:border-slate-300">
      {title && (
        <div className="border-b border-slate-100 bg-slate-50/60 px-4 py-2">
          <p className="text-[11px] font-semibold text-slate-600">{title}</p>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-slate-200/80 bg-slate-50/40 text-[10px]">
              <th className="w-10 px-3 py-2 text-center font-semibold text-slate-400">#</th>
              {keyLabels.map((k) => <th key={k} className="px-3 py-2 text-left font-semibold text-slate-500">{k}</th>)}
              <th className="px-3 py-2 text-right font-semibold text-slate-500">{measure || 'Value'}</th>
              {total > 0 && <th className="w-20 px-3 py-2 text-right font-semibold text-slate-400">Share</th>}
              {total > 0 && <th className="w-24 px-3 py-2 font-semibold text-slate-400" />}
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => {
              const share = total > 0 && item.value ? (item.value / total) * 100 : 0;
              return (
                <tr key={i} className="border-b border-slate-100/80 transition-colors last:border-b-0 hover:bg-slate-50/40">
                  <td className="px-3 py-[6px] text-center tabular-nums text-slate-400">{item.rank ?? i + 1}</td>
                  {keyLabels.map((k) => <td key={k} className="px-3 py-[6px] text-slate-700">{item.key?.[k] ?? '—'}</td>)}
                  <td className="px-3 py-[6px] text-right tabular-nums font-medium text-slate-800">{fmtNum(item.value)}</td>
                  {total > 0 && <td className="px-3 py-[6px] text-right tabular-nums text-slate-400">{share.toFixed(1)}%</td>}
                  {total > 0 && (
                    <td className="px-3 py-[6px]">
                      <div className="h-[5px] w-full overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-blue-400/50 transition-all" style={{ width: `${Math.min(share, 100)}%` }} />
                      </div>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
          {total > 0 && (
            <tfoot>
              <tr className="border-t border-slate-200/60 bg-slate-50/30">
                <td className="px-3 py-[6px]" />
                {keyLabels.map((k) => <td key={k} className="px-3 py-[6px] text-[10px] font-semibold text-slate-500">{k === keyLabels[0] ? 'Total' : ''}</td>)}
                <td className="px-3 py-[6px] text-right tabular-nums text-[10px] font-bold text-slate-700">{fmtNum(total)}</td>
                <td className="px-3 py-[6px] text-right tabular-nums text-[10px] text-slate-400">100%</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

function AggregationTable({ rows, title, measure }: { rows: AggRow[]; title?: string; measure?: string }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]).filter((k) => k !== '__rowId');
  return (
    <div className="my-3 overflow-hidden rounded-lg border border-slate-200/60 print:border-slate-300">
      {title && <div className="border-b border-slate-100 bg-slate-50/60 px-4 py-2"><p className="text-[11px] font-semibold text-slate-600">{title}</p></div>}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead><tr className="border-b border-slate-200/80 bg-slate-50/40 text-[10px]">
            {cols.map((c) => <th key={c} className="px-3 py-2 text-left font-semibold text-slate-500">{c}</th>)}
          </tr></thead>
          <tbody>
            {rows.slice(0, 15).map((row, i) => (
              <tr key={i} className="border-b border-slate-100/80 transition-colors last:border-b-0 hover:bg-slate-50/40">
                {cols.map((c) => {
                  const v = row[c];
                  const isNum = typeof v === 'number';
                  return <td key={c} className={`px-3 py-[6px] ${isNum ? 'text-right tabular-nums font-medium text-slate-800' : 'text-slate-700'}`}>{isNum ? fmtNum(v) : String(v ?? '—')}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 15 && <div className="border-t border-slate-100 bg-slate-50/30 px-4 py-1.5 text-[9px] text-slate-400">Showing 15 of {rows.length} rows</div>}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DOCUMENT BLOCK
   ═══════════════════════════════════════════════════════════════════════════ */

function DocumentBlock({
  block, onUpdate, onReorder, onDelete, onInsertAfter, readOnly,
}: {
  block: DocBlock; onUpdate?: (u: Partial<DocBlock>) => void;
  onReorder?: (d: 'up' | 'down') => void; onDelete?: () => void;
  onInsertAfter?: (k: DocBlock['kind']) => void; readOnly?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [showInsert, setShowInsert] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [copied, setCopied] = useState(false);
  const blockRef = useRef<HTMLDivElement>(null);

  const isText = TEXT_KINDS.has(block.kind);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(block.content || block.metricValue || '').then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }, [block]);

  if (block.kind === 'divider') return (
    <div className="group relative my-6 flex items-center print:my-4" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
      <div className="h-px flex-1 bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
      {!readOnly && hovered && <button type="button" onClick={onDelete} className="absolute -right-6 rounded p-0.5 text-slate-300 hover:text-red-400 print:hidden"><Trash2 className="h-2.5 w-2.5" /></button>}
    </div>
  );

  if (block.kind === 'spacer') return <div className="h-8 print:h-4" />;

  /* ranking / agg data from the block's tableData or content */
  const rankItems = useMemo(() => block.kind === 'table' ? parseRankingItems(block) : [], [block]);
  const aggRows = useMemo(() => (block.kind === 'table' || block.kind === 'narrative') ? parseAggRows(block) : [], [block]);

  return (
    <div ref={blockRef} className="group/block relative" data-block-id={block.id}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setShowMenu(false); setShowInsert(false); }}>

      {/* side controls */}
      {!readOnly && hovered && block.status === 'done' && (
        <div className="absolute -left-7 top-0.5 flex flex-col items-center gap-px print:hidden">
          <button type="button" onClick={() => onReorder?.('up')} className="rounded p-0.5 text-slate-300 hover:text-slate-600" title="Move up"><ChevronUp className="h-3 w-3" /></button>
          <GripVertical className="h-3 w-3 cursor-grab text-slate-200 hover:text-slate-400" />
          <button type="button" onClick={() => onReorder?.('down')} className="rounded p-0.5 text-slate-300 hover:text-slate-600" title="Move down"><ChevronDown className="h-3 w-3" /></button>
        </div>
      )}

      {/* context menu trigger */}
      {!readOnly && hovered && block.status === 'done' && (
        <div className="absolute -right-7 top-0 print:hidden">
          {copied
            ? <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-medium text-emerald-600">Copied</span>
            : <button type="button" onClick={() => setShowMenu(!showMenu)} className="rounded p-1 text-slate-300 hover:text-slate-500"><MoreHorizontal className="h-3.5 w-3.5" /></button>
          }
          {showMenu && <BlockContextMenu isText={isText} onEdit={() => setEditing(true)} onCopy={handleCopy} onDelete={() => onDelete?.()} onClose={() => setShowMenu(false)} />}
        </div>
      )}

      {/* block body */}
      <div className={`relative rounded transition-all duration-100 ${hovered && !readOnly && block.status === 'done' ? 'bg-blue-50/20' : ''} ${block.status === 'pending' ? 'opacity-[0.12]' : ''}`}
        onDoubleClick={() => { if (isText && !readOnly && block.status === 'done') setEditing(true); }}>

        {block.status === 'generating' && <BlockShimmer title={block.title} kind={block.kind} />}

        {block.status === 'error' && (
          <div className="flex items-start gap-3 rounded-lg border border-red-200/50 bg-red-50/40 px-4 py-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
            <div><p className="text-[12px] font-medium text-red-700">Failed{block.title ? ` — ${block.title}` : ''}</p>
            <p className="mt-0.5 text-[10px] text-red-400">Use &quot;Redo&quot; to retry this component.</p></div>
          </div>
        )}

        {block.status === 'pending' && (
          <div className="flex items-center gap-2 py-2.5">
            <div className="h-1 w-1 rounded-full bg-slate-200" />
            <span className="text-[10px] text-slate-300">{block.title || blockLabel(block.kind)}</span>
          </div>
        )}

        {block.status === 'done' && !editing && (<>
          {/* HEADING */}
          {block.kind === 'heading' && (() => {
            const l = block.level || 2;
            return <div className={
              l === 1 ? 'mb-2 mt-10 text-[21px] font-bold leading-tight tracking-[-0.01em] text-slate-900 first:mt-0 print:text-[18pt]'
              : l === 2 ? 'mb-1 mt-7 text-[16.5px] font-bold leading-snug text-slate-800 first:mt-0 print:text-[14pt]'
              : 'mb-0.5 mt-5 text-[13.5px] font-semibold leading-snug text-slate-700 first:mt-0 print:text-[11pt]'
            }>{block.content || 'Untitled'}</div>;
          })()}

          {/* NARRATIVE */}
          {block.kind === 'narrative' && (
            <p className="py-[3px] text-[12.5px] leading-[1.8] text-slate-600 print:text-[10pt] print:leading-[1.65]">
              {block.content || (readOnly ? '' : <span className="italic text-slate-300">Double-click to edit…</span>)}
            </p>
          )}

          {/* KEY FINDING */}
          {block.kind === 'key_finding' && (
            <div className="my-3 rounded-lg bg-gradient-to-r from-blue-50/80 via-indigo-50/30 to-transparent px-5 py-3.5 print:border print:border-slate-300">
              <div className="mb-1.5 flex items-center gap-2">
                <TrendingUp className="h-3 w-3 text-blue-500" />
                <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-blue-600/80">Key Finding</span>
              </div>
              <p className="text-[13px] font-medium leading-[1.7] text-slate-700">{block.content}</p>
            </div>
          )}

          {/* SOURCE NOTE / FOOTNOTE */}
          {(block.kind === 'source_note' || block.kind === 'footnote') && (
            <p className="py-1 text-[10px] leading-relaxed text-slate-400 print:text-[8pt]">
              {block.kind === 'source_note' && <span className="font-semibold text-slate-500">Source: </span>}{block.content}
            </p>
          )}

          {/* METHODOLOGY / CAVEAT / GLOSSARY */}
          {(block.kind === 'methodology_note' || block.kind === 'data_caveat' || block.kind === 'glossary_term') && (
            <div className={`my-2 rounded-md px-4 py-2.5 text-[11px] leading-relaxed ${
              block.kind === 'data_caveat' ? 'border border-amber-200/50 bg-amber-50/30 text-amber-800' : 'bg-slate-50/70 text-slate-500'
            }`}><span className="font-semibold">{blockLabel(block.kind)}: </span>{block.content}</div>
          )}

          {/* CHART */}
          {block.kind === 'chart' && (
            <div className="group/chart relative my-4 overflow-hidden rounded-lg border border-slate-200/60 bg-white print:border-slate-300">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/50 px-4 py-2">
                <p className="text-[11px] font-semibold text-slate-600">{block.title || 'Chart'}</p>
                <BarChart3 className="h-3.5 w-3.5 text-slate-300" />
              </div>
              <div className="flex h-48 items-end gap-[2.5%] bg-gradient-to-b from-white to-slate-50/20 px-6 pb-6 pt-5">
                {[55, 82, 45, 70, 48, 88, 38, 65, 75, 50, 68, 60].map((h, i) => (
                  <div key={i} className="group/bar relative flex-1 cursor-default rounded-t transition-all hover:opacity-80"
                    style={{ height: `${h}%`, background: `hsl(${215 + i * 3}, ${55 + i}%, ${62 + i * 1.5}%)` }}>
                    <span className="absolute -top-4 left-1/2 -translate-x-1/2 rounded bg-slate-800 px-1.5 py-0.5 text-[8px] tabular-nums text-white opacity-0 transition-opacity group-hover/bar:opacity-100">{h}</span>
                  </div>
                ))}
              </div>
              <div className="border-t border-slate-100 bg-slate-50/30 px-4 py-1.5 text-[9px] text-slate-400">
                Visualization renders after full report assembly
              </div>
            </div>
          )}

          {/* TABLE — renders real data if available */}
          {block.kind === 'table' && (
            rankItems.length > 0
              ? <RankingTable items={rankItems} title={block.title} measure={block.title || 'Value'} />
              : aggRows.length > 0
                ? <AggregationTable rows={aggRows} title={block.title} />
                : (
                  <div className="group/table relative my-3 overflow-hidden rounded-lg border border-slate-200/60 bg-white print:border-slate-300">
                    <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/50 px-4 py-2">
                      <p className="text-[11px] font-semibold text-slate-600">{block.title || 'Data Table'}</p>
                      <Table2 className="h-3.5 w-3.5 text-slate-300" />
                    </div>
                    <div className="flex h-24 items-center justify-center text-[11px] text-slate-400">
                      Data will populate after report assembly
                    </div>
                  </div>
                )
          )}

          {/* METRIC */}
          {block.kind === 'metric' && (
            <div className="my-3 rounded-lg border border-slate-200/50 bg-gradient-to-br from-white via-slate-50/30 to-white px-5 py-4 print:border-slate-300">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-slate-400">{block.title || 'Metric'}</p>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-[30px] font-bold tabular-nums leading-none text-slate-800">{fmtNum(block.metricValue)}</span>
                    {block.metricUnit && <span className="text-[13px] font-medium text-slate-400">{block.metricUnit}</span>}
                  </div>
                </div>
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-50 to-indigo-50 text-blue-400">
                  <Hash className="h-5 w-5" />
                </div>
              </div>
              {block.content && <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{block.content}</p>}
            </div>
          )}
        </>)}

        {editing && <InlineEditor value={block.content} level={block.kind === 'heading' ? block.level : undefined} onChange={(v) => onUpdate?.({ content: v })} onBlur={() => setEditing(false)} />}
      </div>

      {/* insert between */}
      {!readOnly && (
        <div className="relative flex h-2.5 items-center justify-center print:hidden">
          {hovered && (
            <button type="button" onClick={() => setShowInsert(!showInsert)}
              className="relative z-10 flex h-[14px] w-[14px] items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm transition-all hover:border-blue-300 hover:text-blue-500">
              <Plus className="h-2 w-2" />
            </button>
          )}
          {showInsert && <InsertMenu onInsert={(k) => onInsertAfter?.(k)} onClose={() => setShowInsert(false)} />}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   COVER PAGE
   ═══════════════════════════════════════════════════════════════════════════ */

function CoverPage({ title, subtitle, blocks }: { title: string; subtitle?: string; blocks: DocBlock[] }) {
  const wc = wordCount(blocks);
  const toc = extractToc(blocks);
  const done = blocks.filter(b => b.status === 'done').length;
  const total = blocks.filter(b => b.kind !== 'divider' && b.kind !== 'spacer').length;
  const today = new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'long', year: 'numeric' });
  return (
    <div className="a4-page relative mx-auto bg-white print:m-0 print:shadow-none" style={{ width: '210mm', maxWidth: '794px', minHeight: '297mm', padding: '30mm 28mm 25mm 28mm', boxShadow: '0 1px 3px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.04)', borderRadius: '2px' }}>
      {/* emblem strip */}
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-slate-800 to-slate-700 text-[11px] font-bold text-white">BS</div>
        <div>
          <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-slate-400">Ministry of Statistics and Programme Implementation</p>
          <p className="text-[8px] text-slate-400">BharatStat Intelligence Platform</p>
        </div>
      </div>
      {/* title block */}
      <div className="mt-16">
        <div className="h-1 w-16 rounded-full bg-gradient-to-r from-blue-500 to-indigo-500" />
        <h1 className="mt-5 text-[28px] font-bold leading-tight tracking-tight text-slate-900 print:text-[24pt]">{title || 'Statistical Intelligence Report'}</h1>
        {subtitle && <p className="mt-3 text-[15px] leading-relaxed text-slate-500 print:text-[12pt]">{subtitle}</p>}
      </div>
      {/* metadata */}
      <div className="mt-10 grid grid-cols-3 gap-4 text-[10px]">
        <div className="rounded-lg bg-slate-50 px-3 py-2"><p className="font-semibold text-slate-400">Date</p><p className="mt-0.5 font-medium text-slate-700">{today}</p></div>
        <div className="rounded-lg bg-slate-50 px-3 py-2"><p className="font-semibold text-slate-400">Content</p><p className="mt-0.5 font-medium text-slate-700">{wc.toLocaleString()} words · {readingTime(wc)}</p></div>
        <div className="rounded-lg bg-slate-50 px-3 py-2"><p className="font-semibold text-slate-400">Status</p><p className="mt-0.5 font-medium text-slate-700">{done}/{total} components</p></div>
      </div>
      {/* TOC */}
      {toc.length > 0 && (
        <div className="mt-12">
          <p className="mb-3 text-[9px] font-bold uppercase tracking-[0.12em] text-slate-400">Table of Contents</p>
          <div className="space-y-1">
            {toc.map((item, i) => (
              <div key={item.id} className="flex items-baseline gap-2 text-[11px]" style={{ paddingLeft: `${(item.level - 1) * 16}px` }}>
                <span className="tabular-nums text-slate-400">{i + 1}.</span>
                <span className={item.level === 1 ? 'font-semibold text-slate-800' : item.level === 2 ? 'font-medium text-slate-700' : 'text-slate-600'}>{item.text}</span>
                <span className="flex-1 border-b border-dotted border-slate-200" />
              </div>
            ))}
          </div>
        </div>
      )}
      {/* footer */}
      <div className="absolute bottom-[12mm] left-[28mm] right-[28mm] text-center text-[8px] text-slate-300">Confidential — For Official Use Only</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN CANVAS
   ═══════════════════════════════════════════════════════════════════════════ */

export function ReportDocumentCanvas({
  blocks, onUpdateBlock, onReorderBlock, onDeleteBlock, onInsertBlock,
  readOnly = false, className, reportTitle, reportSubtitle,
}: ReportDocumentCanvasProps) {
  const BPP = 10;
  const pages: DocBlock[][] = [];
  for (let i = 0; i < blocks.length; i += BPP) pages.push(blocks.slice(i, i + BPP));
  if (!pages.length) pages.push([]);

  const done = blocks.filter(b => b.status === 'done').length;
  const total = blocks.filter(b => b.kind !== 'divider' && b.kind !== 'spacer').length;
  const gen = blocks.filter(b => b.status === 'generating').length;
  const wc = wordCount(blocks);

  return (
    <div className={className || ''}>
      {/* status strip */}
      {total > 0 && (
        <div className="mb-6 flex items-center justify-between px-1 text-[10px] text-slate-400 print:hidden">
          <div className="flex items-center gap-3">
            <span className="font-medium text-slate-500">{pages.length + 1} pages</span>
            <span className="text-slate-200">|</span>
            <span>{wc.toLocaleString()} words · {readingTime(wc)}</span>
            {gen > 0 && <><span className="text-slate-200">|</span><span className="flex items-center gap-1 text-blue-500"><Loader2 className="h-2.5 w-2.5 animate-spin" />{gen} generating</span></>}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex h-1 w-20 overflow-hidden rounded-full bg-slate-100">
              <div className="rounded-full bg-emerald-400 transition-all duration-700" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
            </div>
            <span className="tabular-nums">{done}/{total}</span>
          </div>
        </div>
      )}

      <div className="space-y-10 print:space-y-0">
        {/* Cover page */}
        <CoverPage title={reportTitle || 'Energy Statistics Report'} subtitle={reportSubtitle} blocks={blocks} />

        {/* Content pages */}
        {pages.map((pb, pi) => (
          <div key={pi} className="a4-page relative mx-auto bg-white print:m-0 print:rounded-none print:border-0 print:shadow-none"
            style={{ width: '210mm', maxWidth: '794px', minHeight: '297mm', padding: '22mm 28mm 25mm 28mm',
              boxShadow: '0 1px 3px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.04)', borderRadius: '2px' }}>
            <div className="space-y-0">
              {pb.map((block) => (
                <DocumentBlock key={block.id} block={block}
                  onUpdate={onUpdateBlock ? (u) => onUpdateBlock(block.id, u) : undefined}
                  onReorder={onReorderBlock ? (d) => onReorderBlock(block.id, d) : undefined}
                  onDelete={onDeleteBlock ? () => onDeleteBlock(block.id) : undefined}
                  onInsertAfter={onInsertBlock ? (k) => onInsertBlock(block.id, k) : undefined}
                  readOnly={readOnly} />
              ))}
              {!pb.length && (
                <div className="flex h-60 flex-col items-center justify-center text-slate-300">
                  <FileText className="mb-3 h-8 w-8 text-slate-200" />
                  <p className="text-sm">Content appears as components generate</p>
                </div>
              )}
            </div>
            <div className="absolute bottom-[12mm] left-[28mm] right-[28mm] flex items-center justify-between text-[8px] text-slate-300 print:text-slate-400">
              <span>BharatStat Intelligence Report</span>
              <span className="tabular-nums">Page {pi + 2} of {pages.length + 1}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
