'use client';
import { useState } from 'react';
import { rowMarkers, collectLegend, MARKER_LEGEND, type RowMarkerResult } from '../../engine/statMarkers';
import { applyNumerals } from '../../engine/typography';
import { FigureChart } from '../FigureChart';
import { FigureMap } from '../FigureMap';
import { figureDataOf, isStateData, type FigureView } from '../../engine/figureModel';
import { makeNum, tableRows, dimensionName, measureName } from '../blockFormat';
import type { KindProps } from './types';

/* TABLE — official MoSPI grade: real headers, true-total share, TOTAL row,
   unit line, numbered caption, split-row windows, view switcher, click-to-sort.
   Owns its own figure-view + sort state. */
export function TableBlock({ block, isSelected, numerals, tableCaption, splitPart }: KindProps) {
  const [figureView, setFigureView] = useState<FigureView>('table');
  const [sort, setSort] = useState<{ key: 'rank' | 'name' | 'value' | 'share'; dir: 'asc' | 'desc' }>({ key: 'rank', dir: 'asc' });
  const num = makeNum(numerals);

  const allRows = tableRows(block.tableData);
  if (allRows.length === 0) {
    return (
      <div className="rounded border border-dashed border-slate-300 bg-slate-50/40 px-3 py-4 text-center">
        <p className="text-[10px] font-medium text-slate-500">{tableCaption ? `${tableCaption} \u2014 ${block.title}` : block.title || 'Table'}</p>
        <p className="mt-0.5 text-[9px] text-slate-400">Ask the assistant to fill this table, or generate it.</p>
      </div>
    );
  }

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
}
