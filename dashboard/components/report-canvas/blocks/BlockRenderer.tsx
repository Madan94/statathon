'use client';
import { useEffect, useRef, useState } from 'react';
import { Copy, Loader2, Trash2, Sparkles, MessageSquare, Flag } from 'lucide-react';
import type { PageBlock } from '../engine/useCanvasState';
import type { NumberedHeading, TableSplitPart } from '../engine/paginationEngine';
import { rowMarkers, collectLegend, MARKER_LEGEND, type RowMarkerResult } from '../engine/statMarkers';
import { applyNumerals } from '../engine/typography';
import { RichTextEditor } from './RichTextEditor';
import { FigureChart } from './FigureChart';
import { FigureMap } from './FigureMap';
import { figureDataOf, isStateData, type FigureView } from '../engine/figureModel';

/* ═══════════════════════════════════════════════════════════════════
   BlockRenderer — dispatches to the correct block type renderer.
   • Hierarchy headings get MoSPI decimal numbering + a type-scale +
     anchor ids (D-L2).
   • Tables render with real dimension/measure headers, true-total
     share, a TOTAL row, unit line, and split-row windows (D-L3/D-L6).
   Supports inline editing (double-click) + a selection action bar.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  block: PageBlock;
  isSelected: boolean;
  onSelect: () => void;
  onGenerate?: (index: number) => void;
  onUpdate?: (id: string, updates: Partial<PageBlock>) => void;
  onDelete?: (id: string) => void;
  onDuplicate?: (id: string) => void;
  /** On-canvas "✨ ask" — opens the co-pilot scoped to this block (S4). */
  onAsk?: (block: PageBlock) => void;
  /** Add a footnote to this block; returns the marker number (U2). */
  onAddFootnote?: (blockId: string, text: string) => number;
  /** Review (U4): open a comment thread on this block. */
  onComment?: (block: PageBlock) => void;
  /** Review (U4): toggle the attention flag. */
  onFlag?: (blockId: string) => void;
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

const EDITABLE_KINDS = new Set(['heading', 'narrative', 'key_finding', 'source_note', 'metric']);

type TableRow = { rank?: number; key?: Record<string, string>; value?: number; n?: number };

/** Indian-format a number; em-dash only for genuinely missing (null/NaN). */
function fmtNum(n: number | string | undefined | null): string {
  if (n == null || n === '') return '\u2014';
  const v = typeof n === 'string' ? parseFloat(n) : n;
  if (v == null || isNaN(v)) return '\u2014';
  if (Math.abs(v) >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
  if (Math.abs(v) >= 1e5) return (v / 1e5).toFixed(2) + ' L';
  if (Math.abs(v) >= 1000) return v.toLocaleString('en-IN', { maximumFractionDigits: 1 });
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

/** Pull the row array from any of the known analytics shapes. */
function tableRows(td: Record<string, unknown> | undefined): TableRow[] {
  if (!td) return [];
  const rows = (td.items || td.rankingData || td.aggregationData || td.rows || []) as TableRow[];
  return Array.isArray(rows) ? rows : [];
}

/** Real dimension column name (e.g. "State/UT") from the first row's key. */
function dimensionName(rows: TableRow[], fallback = 'Category'): string {
  const k = rows.find(r => r.key)?.key;
  return k ? Object.keys(k)[0] : fallback;
}

/** Real measure column name from the tableData (binding measure), else title. */
function measureName(td: Record<string, unknown> | undefined, fallback: string): string {
  const direct = typeof td?.measure === 'string' ? td.measure : '';
  const slot = td?.slot as Record<string, unknown> | undefined;
  const fromSlot = typeof slot?.measure === 'string' ? slot.measure : '';
  return direct || fromSlot || fallback;
}

export function BlockRenderer({ block, isSelected, onSelect, onGenerate, onUpdate, onDelete, onDuplicate, onAsk, onAddFootnote, onComment, onFlag, commentCount = 0, flagged = false, numerals = 'intl', numbering, tableCaption, splitPart }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [figureView, setFigureView] = useState<FigureView>('table');
  const [sort, setSort] = useState<{ key: 'rank' | 'name' | 'value' | 'share'; dir: 'asc' | 'desc' }>({ key: 'rank', dir: 'asc' });
  const inputRef = useRef<HTMLInputElement>(null);
  /** Format a number then apply the document numeral system (T6). */
  const num = (v: number | string | undefined | null) => applyNumerals(fmtNum(v), numerals);

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

  // ── GENERATING shimmer ──
  if (block.status === 'generating') {
    return (
      <div className="rounded border border-blue-100 bg-blue-50/30 px-4 py-3">
        <div className="flex items-center gap-2">
          <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
          <span className="text-[10px] font-medium text-blue-600">{block.title}</span>
        </div>
        <div className="mt-2 space-y-1.5">
          <div className="h-2.5 w-full animate-pulse rounded bg-blue-100/60" />
          <div className="h-2.5 w-[85%] animate-pulse rounded bg-blue-100/40" />
        </div>
      </div>
    );
  }

  // ── PENDING placeholder ──
  if (block.status === 'pending') {
    return (
      <div
        onClick={e => { e.stopPropagation(); onGenerate?.(block.index); }}
        className="flex cursor-pointer items-center justify-between rounded border border-dashed border-slate-300 bg-slate-50/50 px-4 py-3 transition-colors hover:border-blue-400 hover:bg-blue-50/30"
      >
        <span className="text-[11px] text-slate-500">{block.title}</span>
        <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-[9px] font-semibold text-blue-700">Generate</span>
      </div>
    );
  }

  // ── ERROR ──
  if (block.status === 'error') {
    return (
      <div
        onClick={e => { e.stopPropagation(); onGenerate?.(block.index); }}
        className="flex cursor-pointer items-center justify-between rounded border border-red-200 bg-red-50/50 px-4 py-2"
      >
        <span className="text-[10px] text-red-600">Failed: {block.title}</span>
        <span className="rounded bg-red-100 px-2 py-0.5 text-[9px] font-semibold text-red-700">Retry</span>
      </div>
    );
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
          multiline={block.kind === 'narrative' || block.kind === 'key_finding'}
          onCommit={(html) => { if (onUpdate) onUpdate(block.id, { content: html }); setEditing(false); }}
          onCancel={cancel}
          onAddFootnote={onAddFootnote ? (text) => onAddFootnote(block.id, text) : undefined}
        />
      </div>
    );
  }

  // ── DONE: Real content ──
  return (
    <div
      onClick={e => { e.stopPropagation(); onSelect(); }}
      onDoubleClick={e => { e.stopPropagation(); startEdit(); }}
      className={`relative rounded transition-all ${isSelected ? 'ring-2 ring-blue-400 ring-offset-1 bg-blue-50/10' : 'hover:bg-slate-50/50'}`}
    >
      {/* Selection action bar (Canva-style) */}
      {isSelected && (onDelete || onDuplicate || onAsk || onComment || onFlag) && (
        <div className="absolute -top-3 right-1 z-30 flex items-center gap-0.5 rounded-md border border-slate-200 bg-white px-0.5 py-0.5 shadow-sm">
          {onAsk && (
            <button onPointerDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); onAsk(block); }}
              title="Ask the co-pilot about this" className="rounded p-1 text-indigo-500 hover:bg-indigo-50"><Sparkles className="h-3 w-3" /></button>
          )}
          {onComment && (
            <button onPointerDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); onComment(block); }}
              title="Comment" className="rounded p-1 text-slate-500 hover:bg-blue-50 hover:text-blue-600"><MessageSquare className="h-3 w-3" /></button>
          )}
          {onFlag && (
            <button onPointerDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); onFlag(block.id); }}
              title={flagged ? 'Clear attention flag' : 'Flag for attention'} className={`rounded p-1 ${flagged ? 'text-amber-500 hover:bg-amber-50' : 'text-slate-500 hover:bg-amber-50 hover:text-amber-600'}`}><Flag className="h-3 w-3" /></button>
          )}
          {onDuplicate && (
            <button onPointerDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); onDuplicate(block.id); }}
              title="Duplicate" className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"><Copy className="h-3 w-3" /></button>
          )}
          {onDelete && (
            <button onPointerDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); onDelete(block.id); }}
              title="Delete" className="rounded p-1 text-slate-500 hover:bg-red-50 hover:text-red-600"><Trash2 className="h-3 w-3" /></button>
          )}
        </div>
      )}

      {/* Review markers (U4): comment count + attention flag — always visible */}
      {(commentCount > 0 || flagged) && (
        <div className="absolute -left-1.5 -top-1.5 z-20 flex items-center gap-0.5">
          {commentCount > 0 && (
            <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-blue-500 px-1 text-[8px] font-bold text-white shadow" title={`${commentCount} open comment(s)`}>{commentCount}</span>
          )}
          {flagged && <Flag className="h-3 w-3 fill-amber-400 text-amber-500" />}
        </div>
      )}

      {/* HEADING — MoSPI decimal type-scale (Topic=1 / Chapter=1.1) */}
      {block.kind === 'heading' && (() => {
        const depth = numbering?.depth ?? Math.min(2, Math.max(1, block.sectionPath.length));
        const label = (block.content || block.title).replace(/^(topic|chapter):\s*/i, '');
        const num = numbering?.number;
        if (depth === 1) {
          return (
            <div id={numbering?.anchor} className="scroll-mt-4 pt-2 pb-1">
              <h2 className="doc-heading doc-h1 flex items-baseline gap-2 uppercase tracking-wide text-slate-900">
                {num && <span className="doc-num tabular-nums text-slate-400">{num}</span>}
                <span>{label}</span>
              </h2>
              <div className="mt-1 h-[2px] w-full rounded bg-slate-800/80" />
            </div>
          );
        }
        return (
          <h3 id={numbering?.anchor} className="doc-heading doc-h2 scroll-mt-4 flex items-baseline gap-2 pt-1.5 pb-0.5 text-slate-800">
            {num && <span className="doc-num tabular-nums text-slate-400">{num}</span>}
            <span>{label}</span>
          </h3>
        );
      })()}

      {/* NARRATIVE — section markers become a numbered §1.1.1 sub-heading */}
      {block.kind === 'narrative' && /^section:/i.test(block.content.trim()) && (
        <h4 id={numbering?.anchor} className="doc-heading doc-h3 scroll-mt-4 flex items-baseline gap-2 pl-4 pt-1 pb-0.5 font-semibold text-slate-700">
          {numbering?.number && <span className="tabular-nums text-slate-400">{numbering.number}</span>}
          <span>{block.content.replace(/^section:\s*/i, '')}</span>
        </h4>
      )}
      {block.kind === 'narrative' && !/^section:/i.test(block.content.trim()) && (
        block.content
          ? <p className="doc-body py-1 text-slate-700" dangerouslySetInnerHTML={{ __html: block.content }} />
          : <p className="doc-body py-1 text-slate-700"><span className="text-slate-300 italic">Double-click to edit…</span></p>
      )}

      {/* KEY FINDING */}
      {block.kind === 'key_finding' && (
        <div className="rounded-md bg-blue-50/70 px-4 py-2.5">
          <p className="doc-body font-medium text-slate-700" dangerouslySetInnerHTML={{ __html: block.content }} />
        </div>
      )}

      {/* TABLE — official MoSPI grade: real headers, true-total share,
          TOTAL row, unit line, numbered caption, split-row windows. */}
      {block.kind === 'table' && tableRows(block.tableData).length > 0 && (() => {
        const allRows = tableRows(block.tableData);
        const dim = dimensionName(allRows);
        const measure = measureName(block.tableData, block.title);
        const grandTotal = allRows.reduce((s, x) => s + (x.value || 0), 0);
        const unit = (block.tableData?.unit as string) || block.metricUnit || '';
        const source = (block.tableData?.source as string) || '';
        // Row window for split parts; otherwise the whole table.
        const start = splitPart ? splitPart.rowStart : 0;
        const end = splitPart ? splitPart.rowEnd : allRows.length;
        const windowRows = allRows.slice(start, end);
        const isLastPart = !splitPart || splitPart.partIndex === splitPart.partCount - 1;
        const caption = tableCaption || block.title;
        // S1 — compute statistical markers per row + the table-level legend.
        const markerByRow: RowMarkerResult[] = allRows.map((r) => rowMarkers(r as Record<string, unknown>, r.value));
        const legend = collectLegend(markerByRow);
        // T5 — figure dataset + which views are available for the switcher.
        const figData = figureDataOf(block);
        const canMap = isStateData(figData);
        const showTable = figureView === 'table' || figureView === 'both';
        const showChart = (figureView === 'chart' || figureView === 'both') && !!figData;
        const showMap = figureView === 'map' && canMap && !!figData;
        return (
          <figure className="overflow-hidden rounded border border-slate-300">
            <figcaption className="doc-caption flex items-baseline justify-between border-b border-slate-200 bg-slate-100 px-3 py-1.5">
              <span className="text-[10px] font-semibold text-slate-700">
                {caption}{splitPart?.continued ? ' (contd.)' : ''}{caption !== block.title ? ` \u2014 ${block.title}` : ''}
              </span>
              <span className="flex items-center gap-1.5">
                {/* T5 view switcher — table / chart / both / map (when selected) */}
                {isSelected && figData && (
                  <span className="flex items-center gap-0.5" onPointerDown={e => e.stopPropagation()}>
                    {([
                      { v: 'table' as FigureView, label: '▦' },
                      { v: 'chart' as FigureView, label: '▮' },
                      { v: 'both' as FigureView, label: '▦▮' },
                      ...(canMap ? [{ v: 'map' as FigureView, label: '🗺' }] : []),
                    ]).map(({ v, label }) => (
                      <button key={v} onClick={(e) => { e.stopPropagation(); setFigureView(v); }}
                        className={`rounded px-1 py-0.5 text-[9px] ${figureView === v ? 'bg-blue-100 text-blue-600' : 'text-slate-400 hover:bg-slate-200'}`}>{label}</button>
                    ))}
                  </span>
                )}
                {unit && <span className="text-[8.5px] font-medium text-slate-400">Unit: {unit}</span>}
              </span>
            </figcaption>
            {showChart && figData && (
              <div className="border-b border-slate-100 p-1">
                <FigureChart data={figData} title={block.title} caption={tableCaption} controls={isSelected} height={showTable ? 160 : 200} />
              </div>
            )}
            {showMap && figData && (
              <div className="border-b border-slate-100 p-1">
                <FigureMap data={figData} title={block.title} caption={tableCaption} controls={isSelected} height={300} />
              </div>
            )}
            {showTable && (() => {
              // T3 — magnitude for in-cell data-bars + leader-row detection.
              const maxVal = Math.max(1, ...windowRows.map(r => Math.abs(r.value || 0)));
              const sortedVals = [...allRows.map(r => r.value || 0)].sort((a, b) => b - a);
              const leaderCut = sortedVals[Math.min(2, sortedVals.length - 1)] ?? Infinity;
              // T4 — click-to-sort. Rank order is the default; others re-sort.
              const dir = sort.dir === 'asc' ? 1 : -1;
              const viewRows = sort.key === 'rank'
                ? windowRows
                : [...windowRows].sort((a, b) => {
                    if (sort.key === 'name') {
                      const an = a.key ? Object.values(a.key)[0] : ''; const bn = b.key ? Object.values(b.key)[0] : '';
                      return an.localeCompare(bn) * dir;
                    }
                    return ((a.value || 0) - (b.value || 0)) * dir; // value & share share order
                  });
              const sortArrow = (k: typeof sort.key) => sort.key === k ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '';
              const toggleSort = (k: typeof sort.key) => setSort(s => s.key === k ? { key: k, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key: k, dir: k === 'name' ? 'asc' : 'desc' });
              return (
              <table className="doc-table w-full text-[10px]">
                <thead>
                  <tr className="bg-[#0B5394] text-white">
                    <th onClick={() => toggleSort('rank')} className="cursor-pointer px-2.5 py-1.5 text-left font-semibold hover:bg-white/10">#{sortArrow('rank')}</th>
                    <th onClick={() => toggleSort('name')} className="cursor-pointer px-2.5 py-1.5 text-left font-semibold hover:bg-white/10">{dim}{sortArrow('name')}</th>
                    <th onClick={() => toggleSort('value')} className="cursor-pointer px-2.5 py-1.5 text-right font-semibold hover:bg-white/10">{measure}{sortArrow('value')}</th>
                    <th onClick={() => toggleSort('share')} className="cursor-pointer px-2.5 py-1.5 text-right font-semibold hover:bg-white/10">Share{sortArrow('share')}</th>
                  </tr>
                </thead>
                <tbody>
                  {viewRows.map((item, i) => {
                    const mk = markerByRow[allRows.indexOf(item)] ?? { suffix: '', used: [] };
                    const pct = grandTotal > 0 && item.value != null && item.value !== 0 ? ((item.value / grandTotal) * 100).toFixed(1) : null;
                    const barPct = item.value ? Math.min(100, (Math.abs(item.value) / maxVal) * 100) : 0;
                    const isLeader = (item.value || 0) >= leaderCut && (item.value || 0) > 0;
                    return (
                      <tr key={i} className={`border-b border-slate-100/80 transition-colors hover:bg-blue-50/40 ${i % 2 === 1 ? 'bg-slate-50/50' : ''} ${isLeader ? 'font-semibold' : ''}`}>
                        <td className="doc-num px-2.5 py-1 tabular-nums text-slate-400">{applyNumerals(String(item.rank ?? i + 1), numerals)}</td>
                        <td className="px-2.5 py-1 text-slate-700">{item.key ? Object.values(item.key)[0] : '\u2014'}</td>
                        <td className="doc-num relative px-2.5 py-1 text-right tabular-nums text-slate-800">
                          {/* in-cell data-bar (T3) */}
                          <span className="pointer-events-none absolute inset-y-[3px] right-1 rounded-sm bg-blue-500/12" style={{ width: `${barPct}%`, maxWidth: '70%' }} />
                          <span className="relative">{mk.override ?? num(item.value)}{mk.suffix && <sup className="ml-0.5 text-[7px] font-semibold text-slate-500">{mk.suffix}</sup>}</span>
                        </td>
                        <td className="doc-num px-2.5 py-1 text-right tabular-nums text-slate-400">{pct != null ? `${applyNumerals(pct, numerals)}%` : '\u2013'}</td>
                      </tr>
                    );
                  })}
                  {isLastPart && (
                    <tr className="border-t-2 border-[#0B5394]/40 bg-slate-100 font-bold">
                      <td className="px-2.5 py-1"></td>
                      <td className="px-2.5 py-1 text-slate-800">TOTAL</td>
                      <td className="doc-num px-2.5 py-1 text-right tabular-nums text-slate-900">{num(grandTotal)}</td>
                      <td className="doc-num px-2.5 py-1 text-right tabular-nums text-slate-600">{applyNumerals('100', numerals)}%</td>
                    </tr>
                  )}
                </tbody>
              </table>
              );
            })()}
            {/* S1 — auto legend: only the markers actually present in this table */}
            {isLastPart && legend.length > 0 && (
              <figcaption className="border-t border-slate-100 bg-white px-3 py-1 text-[8px] text-slate-400">
                {legend.map((m) => MARKER_LEGEND[m]).join('  \u00b7  ')}
              </figcaption>
            )}
            {isLastPart && source && (
              <figcaption className="border-t border-slate-100 bg-white px-3 py-1 text-[8.5px] text-slate-400">
                Source: {source}
              </figcaption>
            )}
          </figure>
        );
      })()}
      {block.kind === 'table' && tableRows(block.tableData).length === 0 && (
        <div className="rounded border border-dashed border-slate-300 bg-slate-50/40 px-3 py-4 text-center">
          <p className="text-[10px] font-medium text-slate-500">{tableCaption ? `${tableCaption} \u2014 ${block.title}` : block.title || 'Table'}</p>
          <p className="mt-0.5 text-[9px] text-slate-400">Ask the assistant to fill this table, or generate it.</p>
        </div>
      )}

      {/* METRIC */}
      {block.kind === 'metric' && (
        <div className="flex items-baseline gap-2 rounded border border-slate-200 bg-gradient-to-r from-white to-slate-50 px-4 py-3">
          <span className="text-[22px] font-bold tabular-nums text-slate-800">{num(block.metricValue)}</span>
          {block.metricUnit && <span className="text-[11px] text-slate-400">{block.metricUnit}</span>}
          {block.content && <span className="ml-2 text-[10px] text-slate-500">{block.content}</span>}
        </div>
      )}

      {/* CHART — real ECharts from the block's data (T1) */}
      {block.kind === 'chart' && (() => {
        const figData = figureDataOf(block);
        if (!figData) {
          return (
            <div className="rounded border border-dashed border-slate-300 bg-slate-50/40 px-3 py-6 text-center">
              <p className="text-[10px] font-medium text-slate-500">{tableCaption ? `${tableCaption} — ${block.title}` : block.title || 'Chart'}</p>
              <p className="mt-0.5 text-[9px] text-slate-400">Ask the assistant to fill this chart, or generate it.</p>
            </div>
          );
        }
        return <FigureChart data={figData} title={block.title} caption={tableCaption} controls={isSelected} height={210} />;
      })()}

      {/* SOURCE NOTE */}
      {block.kind === 'source_note' && (
        <p className="py-0.5 text-[9px] text-slate-400">Source: {block.content}</p>
      )}

      {/* DIVIDER */}
      {block.kind === 'divider' && <div className="my-3 h-px bg-slate-200" />}
    </div>
  );
}
