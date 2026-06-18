'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  FileText,
  GitMerge,
  GripVertical,
  Loader2,
  Pencil,
  Sigma,
  Table2,
  Tag,
  X,
} from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Alert } from '@/components/ui/Alert';
import { bindingPhaseApi, generatePhaseApi, type BindingWorkspace, type DatasetColumnProfile } from '@/lib/api';
import { canvasHandoffStorageKey } from '@/lib/report-section/canvasHandoff';
import type { GeneratedSectionBlock, ReportSectionRequest } from '@/lib/report-section';
import type { ReportCanvasHandoffBundle } from '@/lib/report-section/canvasHandoff';

// ─── Types ───────────────────────────────────────────────────────────────────

type DataRow = Record<string, unknown>;
type Step = 'configure' | 'results';
type WeightOp = 'sum' | 'average' | 'divide100';

interface RenderRow {
  dataRow: DataRow;
  catCells: Array<{ value: string; rowspan: number } | null>;
  resultCells: Array<{ value: number; rowspan: number } | null>;
  leafContrib: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toNum(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim()) {
    const n = Number(v.replace(/,/g, ''));
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function fmt(v: number | null | undefined, frac = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toLocaleString('en-IN', { maximumFractionDigits: frac });
}

function cellStr(v: unknown): string {
  if (v == null || v === '') return '—';
  if (typeof v === 'number') return fmt(v, 3);
  return String(v);
}

function isNumeric(col: DatasetColumnProfile): boolean {
  return (
    col.role === 'measure' ||
    /^int|float|double|decimal|number|numeric/i.test(col.dtype || '') ||
    col.minValue != null
  );
}

// Distinct palette — dark accent for headers/badges, light fill for cells
const CAT_COLORS = [
  { bg: 'bg-[#1e3a5f]', text: 'text-white', light: '#dbeafe', lightHex: '#dbeafe', accent: '#1e3a5f', border: '#93c5fd' },
  { bg: 'bg-[#065f46]', text: 'text-white', light: '#d1fae5', lightHex: '#d1fae5', accent: '#065f46', border: '#6ee7b7' },
  { bg: 'bg-[#5b21b6]', text: 'text-white', light: '#ede9fe', lightHex: '#ede9fe', accent: '#5b21b6', border: '#c4b5fd' },
  { bg: 'bg-[#92400e]', text: 'text-white', light: '#fef3c7', lightHex: '#fef3c7', accent: '#92400e', border: '#fcd34d' },
];

function catColor(level: number) {
  return CAT_COLORS[level % CAT_COLORS.length];
}

// Result column gradient
const RES_COLORS = [
  { header: 'bg-[#154360]', cell: '#1a5276', light: '#d6eaf8' },
  { header: 'bg-[#0a1f44]', cell: '#0a1f44', light: '#e8edf5' },
  { header: 'bg-[#1b2631]', cell: '#1b2631', light: '#eaecee' },
];

function buildRenderRows(
  rows: DataRow[],
  cats: string[],
  valueCol: string,
  weightCol: string | null,
  rowCap: number,
  weightOp: WeightOp = 'sum',
): RenderRow[] {
  if (!rows.length || !cats.length || !valueCol) return [];

  const sorted = [...rows]
    .sort((a, b) => {
      for (const cat of cats) {
        const av = String(a[cat] ?? '');
        const bv = String(b[cat] ?? '');
        if (av < bv) return -1;
        if (av > bv) return 1;
      }
      return 0;
    })
    .slice(0, rowCap);

  const n = sorted.length;
  const depth = cats.length;

  const groupStart: boolean[][] = Array.from({ length: n }, () => Array(depth).fill(false));
  for (let lv = 0; lv < depth; lv++) groupStart[0][lv] = true;
  for (let i = 1; i < n; i++) {
    let changed = false;
    for (let lv = 0; lv < depth; lv++) {
      if (changed || String(sorted[i][cats[lv]] ?? '') !== String(sorted[i - 1][cats[lv]] ?? '')) {
        groupStart[i][lv] = true;
        changed = true;
      }
    }
  }

  const rowspans: number[][] = Array.from({ length: n }, () => Array(depth).fill(0));
  for (let i = 0; i < n; i++) {
    for (let lv = 0; lv < depth; lv++) {
      if (!groupStart[i][lv]) continue;
      let span = 1;
      for (let j = i + 1; j < n; j++) {
        if (groupStart[j][lv]) break;
        span++;
      }
      rowspans[i][lv] = span;
    }
  }

  const leafContribs = sorted.map((row) => {
    const v = toNum(row[valueCol]) ?? 0;
    if (!weightCol) return v;
    const w = toNum(row[weightCol]) ?? 0;
    if (weightOp === 'divide100') return v * (w / 100);
    return v * w; // 'sum' and 'average' both start with v×w; average divides per group below
  });

  const groupResult: number[][] = Array.from({ length: n }, () => Array(depth).fill(0));
  for (let i = 0; i < n; i++) {
    for (let lv = 0; lv < depth; lv++) {
      if (!groupStart[i][lv]) continue;
      const span = rowspans[i][lv];
      let total = 0;
      for (let j = i; j < i + span; j++) total += leafContribs[j];
      groupResult[i][lv] = weightOp === 'average' ? total / span : total;
    }
  }

  return sorted.map((row, i) => ({
    dataRow: row,
    leafContrib: leafContribs[i],
    catCells: cats.map((cat, lv) =>
      groupStart[i][lv] ? { value: String(row[cat] ?? '—'), rowspan: rowspans[i][lv] } : null,
    ),
    resultCells: Array.from({ length: depth }, (_, lv) =>
      groupStart[i][lv] ? { value: groupResult[i][lv], rowspan: rowspans[i][lv] } : null,
    ),
  }));
}

// ─── Visualization Flow Diagram ───────────────────────────────────────────────

// ── FlowViz: renders renderRows for ONE C1 group as an SVG flow diagram ───────
//  Columns: [C1 box] [C2 box(es)] … [Leaf rows] [Cn result boxes] … [C1 result box]
//  Lines:   cat → children  →  leaves  →  Cn result  →  …  →  C1 result

type LvGroup = { label: string; startIdx: number; count: number; result: number };

function FlowViz({
  rows,
  cats,
  valueCol,
  weightCol,
}: {
  rows: RenderRow[];       // already filtered to one C1 group
  cats: string[];
  valueCol: string;
  weightCol: string | null;
}) {
  const depth = cats.length;
  const n = Math.min(rows.length, 20);
  const display = rows.slice(0, n);

  // Layout
  const HDR = 34;        // header height
  const ROW_H = 56;      // height per data row
  const PAD_X = 14;
  const PAD_TOP = HDR + 10;
  const CAT_W = 160;
  const LEAF_W = 210;
  const RES_W = 148;
  const GAP = 14;

  const catX = (lv: number) => PAD_X + lv * (CAT_W + GAP);
  const leafX = PAD_X + depth * (CAT_W + GAP);
  const resX = (revLv: number) => leafX + LEAF_W + GAP + revLv * (RES_W + GAP);
  const svgW = resX(depth) + PAD_X;          // one extra to avoid clipping
  const rowY = (i: number) => PAD_TOP + i * ROW_H + ROW_H / 2;
  const svgH = PAD_TOP + n * ROW_H + 20;

  // Groups at each categorical level derived from catCells
  const lvGroups: LvGroup[][] = Array.from({ length: depth }, (_, lv) => {
    const out: LvGroup[] = [];
    for (let i = 0; i < n; i++) {
      const cc = display[i].catCells[lv];
      if (cc !== null) {
        const count = Math.min(cc.rowspan, n - i);
        let result = 0;
        for (let j = i; j < i + count; j++) result += display[j].leafContrib;
        out.push({ label: cc.value, startIdx: i, count, result });
      }
    }
    return out;
  });

  const maxContrib = Math.max(...display.map((r) => r.leafContrib), 1);

  // Group geometry helpers
  const grpTopY = (g: LvGroup) => rowY(g.startIdx) - ROW_H / 2 + 4;
  const grpBotY = (g: LvGroup) => rowY(g.startIdx + g.count - 1) + ROW_H / 2 - 4;
  const grpMidY = (g: LvGroup) => (grpTopY(g) + grpBotY(g)) / 2;
  const grpH    = (g: LvGroup) => Math.max(grpBotY(g) - grpTopY(g), 44);

  return (
    <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: '60vh', background: '#f1f5f9', borderRadius: 12, border: '2px solid #cbd5e1' }}>
      <svg width={svgW} height={svgH} style={{ display: 'block', fontFamily: 'system-ui,sans-serif' }}>
        <rect width={svgW} height={svgH} fill="#f1f5f9" />

        {/* ── Column headers ── */}
        {cats.map((cat, lv) => {
          const c = catColor(lv);
          const x = catX(lv);
          return (
            <g key={`h-cat-${lv}`}>
              <rect x={x} y={4} width={CAT_W} height={HDR - 8} rx={6} fill={c.accent} />
              <text x={x + CAT_W / 2} y={HDR - 8} textAnchor="middle" fill="white" fontSize={9} fontWeight="700">
                C{lv + 1}: {cat.length > 13 ? cat.slice(0, 13) + '…' : cat}
              </text>
            </g>
          );
        })}
        <rect x={leafX} y={4} width={LEAF_W} height={HDR - 8} rx={6} fill="#374151" />
        <text x={leafX + LEAF_W / 2} y={HDR - 8} textAnchor="middle" fill="white" fontSize={9} fontWeight="700">
          {valueCol.length > 12 ? valueCol.slice(0, 12) + '…' : valueCol}
          {weightCol ? ` × ${weightCol.length > 8 ? weightCol.slice(0, 8) + '…' : weightCol}` : ''}
        </text>
        {Array.from({ length: depth }, (_, revLv) => {
          const lv = depth - 1 - revLv;
          const c = catColor(lv);
          const x = resX(revLv);
          return (
            <g key={`h-res-${revLv}`}>
              <rect x={x} y={4} width={RES_W} height={HDR - 8} rx={6} fill={c.accent} opacity={0.9} />
              <text x={x + RES_W / 2} y={HDR - 8} textAnchor="middle" fill="white" fontSize={9} fontWeight="700">
                C{lv + 1} Result
              </text>
            </g>
          );
        })}

        {/* ── Leaf row boxes ── */}
        {display.map((rr, i) => {
          const y = rowY(i);
          const barW = Math.max(3, (rr.leafContrib / maxContrib) * (LEAF_W - 80));
          const val = toNum(rr.dataRow[valueCol]) ?? 0;
          const wgt = weightCol ? toNum(rr.dataRow[weightCol]) : null;
          const fillBg = i % 2 === 0 ? '#ffffff' : '#eff6ff';
          return (
            <g key={`row-${i}`}>
              <rect x={leafX} y={y - ROW_H / 2 + 4} width={LEAF_W} height={ROW_H - 8}
                rx={7} fill={fillBg} stroke="#94a3b8" strokeWidth={1.5} />
              {/* value */}
              <text x={leafX + 10} y={y - 7} fill="#1e293b" fontSize={11} fontWeight="700">{fmt(val, 1)}</text>
              {/* weight */}
              {weightCol && (
                <text x={leafX + 10} y={y + 8} fill="#64748b" fontSize={9}>× {fmt(wgt ?? 0, 2)}</text>
              )}
              {/* = contribution */}
              <text x={leafX + LEAF_W - 8} y={y + 4} textAnchor="end" fill="#1e40af" fontSize={12} fontWeight="800">
                = {fmt(rr.leafContrib, 1)}
              </text>
              {/* bar */}
              <rect x={leafX + 6} y={y + ROW_H / 2 - 10} width={barW} height={4} rx={2} fill="#3b82f6" opacity={0.55} />
            </g>
          );
        })}
        {rows.length > n && (
          <text x={leafX + LEAF_W / 2} y={svgH - 6} textAnchor="middle" fill="#94a3b8" fontSize={8}>
            + {rows.length - n} more rows not shown
          </text>
        )}

        {/* ── Categorical group boxes + fan lines ── */}
        {lvGroups.map((groups, lv) => {
          const c = catColor(lv);
          const x = catX(lv);
          const nextX = lv < depth - 1 ? catX(lv + 1) : leafX;

          return groups.map((grp, gi) => {
            const midY = grpMidY(grp);
            const boxH = grpH(grp);
            const topY = grpTopY(grp);

            // Children: next cat level groups OR individual leaf rows
            const children: { y: number }[] = lv < depth - 1
              ? lvGroups[lv + 1]
                  .filter((g) => g.startIdx >= grp.startIdx && g.startIdx < grp.startIdx + grp.count)
                  .map((g) => ({ y: grpMidY(g) }))
              : display.slice(grp.startIdx, grp.startIdx + grp.count).map((_, ri) => ({ y: rowY(grp.startIdx + ri) }));

            return (
              <g key={`cat-${lv}-${gi}`}>
                {/* Fan lines to children */}
                {children.map((ch, ci) => (
                  <path
                    key={ci}
                    d={`M${x + CAT_W},${midY} C${x + CAT_W + GAP * 0.7},${midY} ${nextX - GAP * 0.7},${ch.y} ${nextX},${ch.y}`}
                    fill="none" stroke={c.accent}
                    strokeWidth={lv === 0 ? 2 : 1.5}
                    strokeOpacity={0.5}
                    strokeDasharray={lv === 0 ? undefined : '6,3'}
                  />
                ))}
                {/* Box */}
                <rect x={x} y={topY} width={CAT_W} height={boxH} rx={8}
                  fill={c.light} stroke={c.accent} strokeWidth={2} />
                {/* Left accent stripe */}
                <rect x={x} y={topY} width={6} height={boxH} rx={4} fill={c.accent} />
                {/* Label */}
                <text x={x + 14} y={midY - 6} fill={c.accent} fontSize={13} fontWeight="800">
                  {grp.label.length > 15 ? grp.label.slice(0, 15) + '…' : grp.label}
                </text>
                <text x={x + 14} y={midY + 9} fill="#475569" fontSize={9}>
                  {cats[lv]} · {grp.count} rows
                </text>
              </g>
            );
          });
        })}

        {/* ── Result boxes (Cn first → C1 last) ── */}
        {Array.from({ length: depth }, (_, revLv) => {
          const lv = depth - 1 - revLv;
          const c = catColor(lv);
          const x = resX(revLv);
          const nextResX = revLv < depth - 1 ? resX(revLv + 1) : null;

          return lvGroups[lv].map((grp, gi) => {
            const midY = grpMidY(grp);
            const boxH = grpH(grp);
            const topY = grpTopY(grp);

            // Lines from leaf rows → deepest result
            const inputLines = revLv === 0
              ? display.slice(grp.startIdx, grp.startIdx + grp.count).map((_, ri) => rowY(grp.startIdx + ri))
              : [];

            // Line to parent result box
            const parentGroup = nextResX !== null
              ? lvGroups[lv - 1]?.find((p) => p.startIdx <= grp.startIdx && p.startIdx + p.count > grp.startIdx)
              : null;

            return (
              <g key={`res-${revLv}-${gi}`}>
                {/* Leaf → deepest result fan */}
                {inputLines.map((ly, li) => (
                  <path key={li}
                    d={`M${leafX + LEAF_W},${ly} C${leafX + LEAF_W + GAP * 0.7},${ly} ${x - GAP * 0.7},${midY} ${x},${midY}`}
                    fill="none" stroke="#6366f1" strokeWidth={1} strokeOpacity={0.2}
                  />
                ))}
                {/* result → parent result */}
                {parentGroup && nextResX !== null && (
                  <path
                    d={`M${x + RES_W},${midY} C${x + RES_W + GAP * 0.7},${midY} ${nextResX - GAP * 0.7},${grpMidY(parentGroup)} ${nextResX},${grpMidY(parentGroup)}`}
                    fill="none" stroke={c.accent} strokeWidth={1.5} strokeOpacity={0.45}
                  />
                )}
                {/* Result box */}
                <rect x={x} y={topY} width={RES_W} height={boxH} rx={8}
                  fill={c.light} stroke={c.accent} strokeWidth={2} />
                <rect x={x} y={topY} width={6} height={boxH} rx={4} fill={c.accent} />
                <text x={x + 14} y={midY - 11} fill={c.accent} fontSize={8} fontWeight="700" letterSpacing="0.5">
                  C{lv + 1} RESULT
                </text>
                <text x={x + 14} y={midY + 7} fill={c.accent} fontSize={14} fontWeight="900">
                  {fmt(grp.result, 2)}
                </text>
                <text x={x + 14} y={midY + 21} fill="#64748b" fontSize={8}>
                  {grp.count} rows · Σ(v{weightCol ? '×w' : ''})
                </text>
              </g>
            );
          });
        })}
      </svg>
    </div>
  );
}

// ── VizModal ──────────────────────────────────────────────────────────────────

function VizModal({
  open,
  onClose,
  renderRows,
  cats,
  valueCol,
  weightCol,
}: {
  open: boolean;
  onClose: () => void;
  renderRows: RenderRow[];
  cats: string[];
  valueCol: string;
  weightCol: string | null;
}) {
  const [activeC1, setActiveC1] = useState(0);

  // Group renderRows by C1 value
  const c1Groups = useMemo(() => {
    const groups: { label: string; rows: RenderRow[]; total: number }[] = [];
    for (const rr of renderRows) {
      if (rr.catCells[0] !== null) {
        groups.push({ label: rr.catCells[0].value, rows: [rr], total: rr.resultCells[cats.length - 1]?.value ?? 0 });
      } else {
        groups[groups.length - 1].rows.push(rr);
      }
    }
    return groups;
  }, [renderRows, cats.length]);

  if (!open || !c1Groups.length) return null;
  const active = c1Groups[Math.min(activeC1, c1Groups.length - 1)];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-6 backdrop-blur-sm" style={{ overflowY: 'auto' }}>
      <div className="w-full max-w-6xl rounded-2xl border border-slate-200 bg-white shadow-2xl" style={{ maxHeight: 'calc(100vh - 3rem)', display: 'flex', flexDirection: 'column' }}>

        {/* Header — fixed */}
        <div className="flex shrink-0 items-start justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-[#0a1f44]">
              <GitMerge className="h-5 w-5 text-primary" />
              Calculation flow — how values aggregate
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Each row flows through the categorical hierarchy. Lines show contribution paths.
              Formula: <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-primary">Σ({valueCol}{weightCol ? ` × ${weightCol}` : ''})</code>
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="ml-4 rounded-xl border border-slate-200 p-2 text-slate-400 hover:bg-slate-50 hover:text-slate-700">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* C1 tab bar — scrollable horizontally, fixed */}
        <div className="shrink-0 overflow-x-auto border-b border-slate-200 bg-slate-50 px-6">
          <div className="flex gap-0.5 py-2">
            {c1Groups.map((g, i) => {
              const c = catColor(0);
              return (
                <button key={g.label} type="button" onClick={() => setActiveC1(i)}
                  className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    activeC1 === i ? 'bg-white shadow-sm ring-1 ring-slate-200' : 'text-slate-500 hover:bg-white/70'
                  }`}
                  style={activeC1 === i ? { color: c.accent } : {}}
                >
                  <span className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-black text-white" style={{ backgroundColor: c.accent }}>
                    {i + 1}
                  </span>
                  {cats[0]}={g.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-4" style={{ minHeight: 0 }}>

          {/* Legend */}
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-4 py-2.5 text-[10px] text-slate-500">
            {cats.map((cat, lv) => {
              const c = catColor(lv);
              return (
                <span key={lv} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: c.accent }} />
                  <span className="font-semibold" style={{ color: c.accent }}>C{lv + 1}</span> = {cat}
                </span>
              );
            })}
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded bg-[#eff6ff]" style={{ border: '1px solid #94a3b8' }} />
              Row: {valueCol}{weightCol ? ` × ${weightCol}` : ''}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded bg-[#3b82f6] opacity-50" />
              Contribution bar (relative size)
            </span>
            <span className="ml-auto font-medium text-slate-600">
              Σ({valueCol}{weightCol ? ` × ${weightCol}` : ''}) per group
            </span>
          </div>

          {/* SVG diagram */}
          <FlowViz rows={active.rows} cats={cats} valueCol={valueCol} weightCol={weightCol} />

          {/* C1 result summary strip */}
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[9px] font-bold uppercase tracking-wide text-slate-400">C1 Group</p>
              <p className="mt-0.5 text-sm font-bold text-[#0a1f44]">{cats[0]} = {active.label}</p>
            </div>
            <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
              <p className="text-[9px] font-bold uppercase tracking-wide text-slate-400">C1 Total Result</p>
              <p className="mt-0.5 text-lg font-black text-primary">{fmt(active.total, 2)}</p>
            </div>
            <p className="text-xs text-slate-500">
              = sum of all Σ({valueCol}{weightCol ? ` × ${weightCol}` : ''}) where {cats[0]} = {active.label}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Label Map Modal ──────────────────────────────────────────────────────────
// Lets the user map raw categorical values (e.g. "1") to display names ("Andhra Pradesh")

type LabelMap = Record<string, Record<string, string>>; // { colName: { rawValue: displayLabel } }

function LabelMapModal({
  open,
  onClose,
  onConfirm,
  cats,
  renderRows,
  generating,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (labelMap: LabelMap) => void;
  cats: string[];
  renderRows: RenderRow[];
  generating: boolean;
}) {
  const [activeTab, setActiveTab] = useState(0);
  const [labelMap, setLabelMap] = useState<LabelMap>({});

  // Compute unique values per categorical column
  const uniqueValues = useMemo<Record<string, string[]>>(() => {
    const out: Record<string, string[]> = {};
    for (const cat of cats) {
      const seen = new Set<string>();
      for (const rr of renderRows) {
        const v = String(rr.dataRow[cat] ?? '');
        if (!seen.has(v)) { seen.add(v); }
      }
      out[cat] = [...seen].sort();
    }
    return out;
  }, [cats, renderRows]);

  const setLabel = (col: string, raw: string, label: string) => {
    setLabelMap((prev) => ({
      ...prev,
      [col]: { ...(prev[col] ?? {}), [raw]: label },
    }));
  };

  const getLabel = (col: string, raw: string) => labelMap[col]?.[raw] ?? raw;

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-10 backdrop-blur-sm" style={{ overflowY: 'auto' }}>
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white shadow-2xl" style={{ maxHeight: 'calc(100vh - 5rem)', display: 'flex', flexDirection: 'column' }}>

        {/* Header */}
        <div className="flex shrink-0 items-start justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-[#0a1f44]">
              <Tag className="h-5 w-5 text-primary" />
              Map category codes to display labels
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Optional — give each coded value a readable name. These labels will appear in the generated report.
              Leave as-is to keep the raw values.
            </p>
          </div>
          <button type="button" onClick={onClose} className="ml-4 rounded-xl border border-slate-200 p-2 text-slate-400 hover:bg-slate-50">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Tab bar */}
        <div className="shrink-0 overflow-x-auto border-b border-slate-200 bg-slate-50 px-6">
          <div className="flex gap-1 py-2">
            {cats.map((cat, i) => {
              const c = catColor(i);
              return (
                <button key={cat} type="button" onClick={() => setActiveTab(i)}
                  className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    activeTab === i ? 'bg-white shadow-sm ring-1 ring-slate-200' : 'text-slate-500 hover:bg-white/70'
                  }`}
                  style={activeTab === i ? { color: c.accent } : {}}
                >
                  <span className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-black text-white" style={{ backgroundColor: c.accent }}>
                    {i + 1}
                  </span>
                  C{i + 1}: {cat}
                  <span className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[9px] text-slate-500">
                    {uniqueValues[cat]?.length ?? 0}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Value mapping table */}
        <div className="flex-1 overflow-y-auto px-6 py-4" style={{ minHeight: 0 }}>
          {cats[activeTab] && (
            <div>
              <p className="mb-3 text-[10px] font-bold uppercase tracking-wide text-slate-400">
                Column: <span style={{ color: catColor(activeTab).accent }}>{cats[activeTab]}</span> —{' '}
                {uniqueValues[cats[activeTab]]?.length} unique values
              </p>
              <div className="space-y-2">
                {(uniqueValues[cats[activeTab]] ?? []).map((raw) => (
                  <div key={raw} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[10px] font-black text-white"
                      style={{ backgroundColor: catColor(activeTab).accent }}>
                      {raw.slice(0, 3)}
                    </div>
                    <div className="w-20 shrink-0">
                      <p className="text-[9px] text-slate-400">Raw value</p>
                      <p className="text-sm font-bold text-slate-700">{raw}</p>
                    </div>
                    <Pencil className="h-3 w-3 shrink-0 text-slate-300" />
                    <div className="flex-1">
                      <p className="text-[9px] text-slate-400">Display label</p>
                      <input
                        type="text"
                        value={getLabel(cats[activeTab], raw)}
                        onChange={(e) => setLabel(cats[activeTab], raw, e.target.value)}
                        placeholder={raw}
                        className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm text-slate-700 outline-none focus:ring-2 focus:ring-primary/20"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex shrink-0 items-center justify-between border-t border-slate-200 px-6 py-4">
          <p className="text-[10px] text-slate-400">
            Unmapped values will use their raw code in the report.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={onClose}
              className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
              Cancel
            </button>
            <button type="button" onClick={() => onConfirm(labelMap)} disabled={generating}
              className="flex items-center gap-2 rounded-xl bg-primary px-5 py-2 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-60">
              {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              {generating ? 'Generating report…' : 'Generate report'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Result Table ─────────────────────────────────────────────────────────────

function ResultTable({
  renderRows,
  cats,
  valueCol,
  weightCol,
  weightOp,
}: {
  renderRows: RenderRow[];
  cats: string[];
  valueCol: string;
  weightCol: string | null;
  weightOp: WeightOp;
}) {
  const depth = cats.length;

  return (
    <div className="overflow-auto rounded-xl border-2 border-slate-300">
      <table className="w-full border-collapse text-xs">
        <thead>
          {/* Level 1: category group headers */}
          <tr>
            {cats.map((cat, lv) => {
              const c = catColor(lv);
              return (
                <th
                  key={cat}
                  className={`${c.bg} ${c.text} whitespace-nowrap border-r border-white/20 px-4 py-3 text-left`}
                >
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/20 text-[9px] font-black">
                      C{lv + 1}
                    </span>
                    <div>
                      <p className="text-[9px] font-normal uppercase tracking-wider opacity-70">
                        Category {lv + 1}
                      </p>
                      <p className="text-[11px] font-bold leading-tight">{cat}</p>
                    </div>
                  </div>
                </th>
              );
            })}
            {/* Aggregator header */}
            <th className="whitespace-nowrap border-r border-white/20 bg-[#374151] px-4 py-3 text-right text-white">
              <div>
                <p className="text-[9px] font-normal uppercase tracking-wider opacity-70">Aggregator A1</p>
                <p className="text-[11px] font-bold leading-tight">{valueCol}</p>
              </div>
            </th>
            {weightCol && (
              <th className="whitespace-nowrap border-r border-white/20 bg-[#4b5563] px-4 py-3 text-right text-white">
                <div>
                  <p className="text-[9px] font-normal uppercase tracking-wider opacity-70">Multiplier</p>
                  <p className="text-[11px] font-bold leading-tight">{weightCol}</p>
                </div>
              </th>
            )}
            {/* Contribution column */}
            <th className="whitespace-nowrap border-r border-white/20 bg-[#3730a3] px-4 py-3 text-right text-white">
              <div>
                <p className="text-[9px] font-normal uppercase tracking-wider opacity-70">
                  Row contrib
                  {weightOp === 'average' && ' (avg)'}
                  {weightOp === 'divide100' && ' (÷100)'}
                </p>
                <p className="text-[11px] font-bold leading-tight">
                  {weightCol
                    ? weightOp === 'divide100'
                      ? `${valueCol} × ${weightCol} ÷ 100`
                      : `${valueCol} × ${weightCol}`
                    : valueCol}
                </p>
              </div>
            </th>
            {/* Result columns — deepest first */}
            {[...cats].reverse().map((cat, revIdx) => {
              const lv = depth - 1 - revIdx;
              const isLeaf = lv === depth - 1;
              const bg = isLeaf ? 'bg-[#1e40af]' : 'bg-[#0a1f44]';
              return (
                <th
                  key={`rh-${lv}`}
                  className={`${bg} whitespace-nowrap border-r border-white/20 px-4 py-3 text-right text-white`}
                >
                  <div>
                    <p className="text-[9px] font-normal uppercase tracking-wider opacity-70">
                      C{lv + 1} group result
                    </p>
                    <p className="text-[11px] font-bold leading-tight">
                      Σ {cat}
                    </p>
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {renderRows.map((rr, rowIdx) => {
            const c1GroupIdx = (() => {
              let count = 0;
              for (let r = 0; r <= rowIdx; r++) {
                if (renderRows[r].catCells[0] !== null) count++;
              }
              return count - 1;
            })();
            const isEven = c1GroupIdx % 2 === 0;
            const rowBase = isEven ? 'bg-white hover:bg-blue-50' : 'bg-slate-100 hover:bg-blue-50';

            return (
              <tr key={rowIdx} className={`border-b-2 border-slate-200 transition-colors ${rowBase}`}>
                {/* Categorical merged cells */}
                {rr.catCells.map((cc, lv) => {
                  if (cc === null) return null;
                  const c = catColor(lv);
                  return (
                    <td
                      key={lv}
                      rowSpan={cc.rowspan}
                      className="border-r-2 border-slate-300 px-3 py-2 align-middle"
                      style={{ borderLeft: `4px solid ${c.accent}` }}
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[9px] font-black text-white"
                          style={{ backgroundColor: c.accent }}
                        >
                          {cc.value.length <= 3 ? cc.value : cc.value.slice(0, 2)}
                        </span>
                        <div>
                          <p className="text-[9px] font-medium uppercase tracking-wide" style={{ color: c.accent }}>
                            C{lv + 1}
                          </p>
                          <p className="text-sm font-bold text-[#1e293b]">{cc.value}</p>
                        </div>
                      </div>
                      <div
                        className="mt-1 rounded px-1.5 py-0.5 text-[9px]"
                        style={{ backgroundColor: c.light, color: c.accent }}
                      >
                        {cc.rowspan} row{cc.rowspan > 1 ? 's' : ''}
                      </div>
                    </td>
                  );
                })}

                {/* Value */}
                <td className="border-r-2 border-slate-300 px-3 py-2 text-right tabular-nums">
                  <span className="text-sm font-semibold text-[#1e293b]">
                    {cellStr(rr.dataRow[valueCol])}
                  </span>
                </td>

                {/* Weight */}
                {weightCol && (
                  <td className="border-r-2 border-slate-300 px-3 py-2 text-right tabular-nums">
                    <span className="text-sm text-[#64748b]">
                      {cellStr(rr.dataRow[weightCol])}
                    </span>
                  </td>
                )}

                {/* Per-row contribution */}
                <td className="border-r-2 border-slate-400 bg-indigo-50 px-3 py-2 text-right tabular-nums">
                  <span className="text-sm font-bold text-indigo-700">{fmt(rr.leafContrib, 2)}</span>
                </td>

                {/* Result merged cells — deepest first */}
                {[...rr.resultCells].reverse().map((rc, revIdx) => {
                  if (rc === null) return null;
                  const lv = depth - 1 - revIdx;
                  const isLeaf = lv === depth - 1;
                  const c = catColor(lv);
                  return (
                    <td
                      key={`rc-${lv}`}
                      rowSpan={rc.rowspan}
                      className="border-r-2 border-slate-300 px-3 py-2 text-right align-middle"
                    >
                      <div className="rounded-xl px-3 py-2" style={{ backgroundColor: c.light }}>
                        <p className="text-[9px] font-semibold uppercase tracking-wide" style={{ color: c.accent }}>
                          C{lv + 1} result
                        </p>
                        <p className="mt-0.5 text-base font-black tabular-nums" style={{ color: c.accent }}>
                          {fmt(rc.value, 2)}
                        </p>
                        <p className="mt-0.5 text-[9px]" style={{ color: c.accent, opacity: 0.7 }}>
                          {rc.rowspan} row{rc.rowspan > 1 ? 's' : ''} summed
                        </p>
                      </div>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Summary Cards ────────────────────────────────────────────────────────────

function SummaryCards({ renderRows, cats }: { renderRows: RenderRow[]; cats: string[] }) {
  const depth = cats.length;

  const grandTotal = useMemo(
    () => renderRows.reduce((s, rr) => s + rr.leafContrib, 0),
    [renderRows],
  );

  const c1Groups = useMemo(
    () =>
      renderRows
        .filter((rr) => rr.catCells[0] !== null)
        .map((rr) => ({
          label: rr.catCells[0]!.value,
          result: rr.resultCells[depth - 1]?.value ?? 0,
          rows: rr.catCells[0]!.rowspan,
        })),
    [renderRows, depth],
  );

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-white px-4 py-3 shadow-sm">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">C1 groups</p>
          <p className="mt-1 text-2xl font-bold text-[#0a1f44]">{c1Groups.length}</p>
          <p className="text-[10px] text-text-muted">{cats[0]}</p>
        </div>
        <div className="rounded-xl border border-border bg-white px-4 py-3 shadow-sm">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">Total rows</p>
          <p className="mt-1 text-2xl font-bold text-[#0a1f44]">{renderRows.length}</p>
          <p className="text-[10px] text-text-muted">shown in table</p>
        </div>
        <div className="rounded-xl border border-border bg-white px-4 py-3 shadow-sm">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">Categorical levels</p>
          <p className="mt-1 text-2xl font-bold text-[#0a1f44]">{cats.length}</p>
          <p className="text-[10px] text-text-muted">{cats.join(' → ')}</p>
        </div>
        <div className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 shadow-sm">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">Grand total Σ</p>
          <p className="mt-1 text-2xl font-bold text-primary">{fmt(grandTotal, 2)}</p>
          <p className="text-[10px] text-text-muted">all groups combined</p>
        </div>
      </div>

      {/* Per-C1 group breakdown */}
      <div className="rounded-xl border border-border bg-white p-4 shadow-sm">
        <p className="mb-3 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
          {cats[0]} → C1 group results
        </p>
        <div className="flex flex-wrap gap-2">
          {c1Groups.map((g, i) => {
            const c = catColor(0);
            const pct = grandTotal > 0 ? (g.result / grandTotal) * 100 : 0;
            return (
              <div
                key={g.label}
                className="rounded-xl border px-4 py-2.5 text-sm"
                style={{ borderColor: c.accent + '40', backgroundColor: c.light }}
              >
                <div className="flex items-center gap-2">
                  <span
                    className="flex h-5 w-5 items-center justify-center rounded-md text-[9px] font-black text-white"
                    style={{ backgroundColor: c.accent }}
                  >
                    {i + 1}
                  </span>
                  <span className="font-semibold text-[#1e293b]">{cats[0]} = {g.label}</span>
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-3">
                  <span className="text-xs font-bold" style={{ color: c.accent }}>
                    {fmt(g.result, 2)}
                  </span>
                  <span className="text-[10px] text-text-muted">{g.rows} rows · {pct.toFixed(1)}%</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full rounded-full bg-white/60">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${Math.max(pct, 2)}%`, backgroundColor: c.accent }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── Column Tag ───────────────────────────────────────────────────────────────

function ColumnTag({ label, onRemove, index }: { label: string; onRemove: () => void; index: number }) {
  const c = catColor(index);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold"
      style={{ borderColor: c.accent + '60', backgroundColor: c.light, color: c.accent }}
    >
      <span
        className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-black text-white"
        style={{ backgroundColor: c.accent }}
      >
        {index + 1}
      </span>
      C{index + 1}: {label}
      <button type="button" onClick={onRemove} className="ml-0.5 rounded-full opacity-70 hover:opacity-100">
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const ROW_CAP = 500;

export default function GuidedQueryContractPage() {
  const params = useParams();
  const templateId = String(params.templateId || '');
  const signature = String(params.signature || '');

  const [workspace, setWorkspace] = useState<BindingWorkspace | null>(null);
  const [rows, setRows] = useState<DataRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const router = useRouter();

  const [step, setStep] = useState<Step>('configure');
  const [selectedCats, setSelectedCats] = useState<string[]>([]);
  const [valueCol, setValueCol] = useState<string>('');
  const [weightCol, setWeightCol] = useState<string>('');
  const [weightOp, setWeightOp] = useState<WeightOp>('sum');
  const [rowCapApplied, setRowCapApplied] = useState(ROW_CAP);
  const [vizOpen, setVizOpen] = useState(false);

  // Report generation state
  const [labelMapOpen, setLabelMapOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  // Load workspace
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    bindingPhaseApi
      .getWorkspace(templateId, signature)
      .then((ws) => { if (!cancelled) setWorkspace(ws); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load workspace.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [templateId, signature]);

  // Load rows
  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    setRowsLoading(true);
    bindingPhaseApi
      .previewRows(templateId, signature, 1000)
      .then((p) => { if (!cancelled) setRows((p.rows as DataRow[]) ?? []); })
      .catch(() => { if (!cancelled) setError('Could not fetch dataset rows.'); })
      .finally(() => { if (!cancelled) setRowsLoading(false); });
    return () => { cancelled = true; };
  }, [workspace, templateId, signature]);

  // Auto-select first measure + detect weight
  useEffect(() => {
    if (!workspace) return;
    const cols = workspace.dataset_ast?.columns ?? [];
    const measures = cols.filter((c) => c.role === 'measure');
    if (measures.length && !valueCol) setValueCol(measures[0].name);
    const weightPatterns = [/multiplier/i, /^weight$/i, /^wt$/i, /^mult/i];
    const auto = cols.find((c) => isNumeric(c) && weightPatterns.some((p) => p.test(c.name)));
    if (auto && !weightCol) setWeightCol(auto.name);
  }, [workspace, valueCol, weightCol]);

  const columns = workspace?.dataset_ast?.columns ?? [];
  const measureColumns = useMemo(() => columns.filter((c) => c.role === 'measure'), [columns]);
  const numericColumns = useMemo(() => columns.filter(isNumeric), [columns]);

  const renderRows = useMemo(
    () => buildRenderRows(rows, selectedCats, valueCol, weightCol || null, rowCapApplied, weightOp),
    [rows, selectedCats, valueCol, weightCol, rowCapApplied, weightOp],
  );

  const toggleCat = (name: string) =>
    setSelectedCats((prev) => prev.includes(name) ? prev.filter((c) => c !== name) : [...prev, name]);

  const moveCat = (i: number, dir: 'up' | 'down') => {
    setSelectedCats((prev) => {
      const next = [...prev];
      const t = dir === 'up' ? i - 1 : i + 1;
      if (t < 0 || t >= next.length) return prev;
      [next[i], next[t]] = [next[t], next[i]];
      return next;
    });
  };

  const canBuild = selectedCats.length >= 1 && Boolean(valueCol);

  // ── Report generation ─────────────────────────────────────────────────────────────────────────────────────────────────────────
  const handleGenerateReport = async (labelMap: LabelMap) => {
    if (!workspace || !renderRows.length) return;
    setGenerating(true);
    setGenError(null);

    try {
      const sectionId = crypto.randomUUID();
      // Unique chapter title avoids anchor collision with existing canvas drafts
      const chapterTitle = `Guided Query Contract`;
      const sectionTitle = `${selectedCats.map((c, i) => `C${i + 1}: ${c}`).join(' × ')} — ${valueCol}${weightCol ? ` × ${weightCol}` : ''}`;
      const sectionPath = [chapterTitle, sectionTitle];
      const mkId = () => crypto.randomUUID();

      const applyLabel = (col: string, raw: string) => labelMap[col]?.[raw] || raw;

      // ── Build C1 group summary rows in the exact canvas TableRow format ──
      // tableRows() in blockFormat.ts looks for: td.items | td.rankingData | td.aggregationData | td.rows
      // Each row: { rank, key: { [DimName]: label }, value }
      const tableItems: Array<{ rank: number; key: Record<string, string>; value: number; n?: number }> = [];
      let rank = 1;
      for (const rr of renderRows) {
        const cc0 = rr.catCells[0];
        if (cc0 === null) continue;
        // C1 result = last resultCell (the outermost accumulation)
        const c1Result = rr.resultCells[selectedCats.length - 1]?.value ?? 0;
        const dimLabel = applyLabel(selectedCats[0], cc0.value);
        tableItems.push({ rank: rank++, key: { [selectedCats[0]]: dimLabel }, value: c1Result, n: cc0.rowspan });
      }
      // Sort descending by value
      tableItems.sort((a, b) => b.value - a.value).forEach((r, i) => { r.rank = i + 1; });

      const grandTotal = tableItems.reduce((s, r) => s + r.value, 0);
      const measureLabel = `${valueCol}${weightCol ? ` × ${weightCol}` : ''} (${weightOp === 'sum' ? 'Σ' : weightOp === 'average' ? 'avg' : '÷100'})`;

      // ── Also build per-C2 table if depth > 1 ──
      const c2Items: Array<{ rank: number; key: Record<string, string>; value: number }> = [];
      if (selectedCats.length > 1) {
        let r2 = 1;
        for (const rr of renderRows) {
          const cc1 = rr.catCells[1];
          if (cc1 === null) continue;
          const c2Result = rr.resultCells[selectedCats.length - 1]?.value ?? 0;
          const l1 = applyLabel(selectedCats[0], String(rr.dataRow[selectedCats[0]] ?? ''));
          const l2 = applyLabel(selectedCats[1], cc1.value);
          c2Items.push({ rank: r2++, key: { [`${selectedCats[0]} → ${selectedCats[1]}`]: `${l1} / ${l2}` }, value: c2Result });
        }
        c2Items.sort((a, b) => b.value - a.value).forEach((r, i) => { r.rank = i + 1; });
      }

      // ── Blocks ────────────────────────────────────────────────────────────
      const blocks: GeneratedSectionBlock[] = [
        {
          id: mkId(), index: 0, kind: 'heading',
          title: sectionTitle, content: sectionTitle,
          sectionPath, status: 'done', pageIndex: 0,
        },
        // C1-level summary table — correct blockFormat shape
        {
          id: mkId(), index: 1, kind: 'table',
          title: `C1: ${selectedCats[0]} — ${measureLabel}`,
          content: '',
          tableData: {
            items: tableItems,          // ← exact key blockFormat.tableRows() reads
            measure: measureLabel,      // ← column header for the value
            unit: '',
            source: `Guided Query Contract · ${weightOp}`,
          },
          sectionPath, status: 'done', pageIndex: 0,
        },
        // Grand total metric
        {
          id: mkId(), index: 2, kind: 'metric',
          title: 'Grand Total',
          content: fmt(grandTotal, 2),
          metricValue: fmt(grandTotal, 2),
          metricUnit: measureLabel,
          sectionPath, status: 'done', pageIndex: 0,
        },
      ];

      // C2 breakdown table (if multi-level)
      if (c2Items.length > 0) {
        blocks.push({
          id: mkId(), index: blocks.length, kind: 'table',
          title: `C2: ${selectedCats[1]} breakdown`,
          content: '',
          tableData: {
            items: c2Items.slice(0, 50),
            measure: measureLabel,
            unit: '',
            source: `Guided Query Contract · ${weightOp}`,
          },
          sectionPath, status: 'done', pageIndex: 0,
        });
      }

      // ── Synthesize LLM narrative ───────────────────────────────────────────
      const topGroups = tableItems.slice(0, 5).map((g) => `${Object.values(g.key)[0]} = ${fmt(g.value, 1)}`).join(', ');
      const description = [
        `Weighted cross-tabulation: ${measureLabel} grouped by ${selectedCats.map((c, i) => `C${i + 1}=${c}`).join(', ')}.`,
        `Grand total: ${fmt(grandTotal, 2)}.`,
        `${tableItems.length} top-level groups (${selectedCats[0]}).`,
        topGroups ? `Top groups by value: ${topGroups}.` : '',
        weightCol ? `Weight column: ${weightCol}. Operation: ${weightOp === 'sum' ? 'Σ(value × weight)' : weightOp === 'average' ? 'weighted average' : 'value × weight ÷ 100'}.` : '',
      ].filter(Boolean).join(' ');

      const synth = await generatePhaseApi.synthesize(templateId, signature, {
        description,
        tags: ['cross-tabulation', 'guided-query', selectedCats[0], weightOp],
        components: [{ type: 'narrative', title: 'Analysis' }, { type: 'key_finding', title: 'Key Findings' }],
        measures: [{ col: valueCol, label: valueCol, agg: weightCol ? 'weighted_mean' : 'sum', weighted: !!weightCol }],
        blocks: blocks as Array<Record<string, unknown>>,
        section_title: sectionTitle,
        chapter_title: chapterTitle,
        dataset_id: workspace.dataset_id,
        analysis_type: 'comparison',
        max_words: 300,
      });

      // Prepend LLM narrative
      if (synth.content) {
        blocks.unshift({
          id: mkId(), index: 0, kind: 'narrative',
          title: 'Analysis',
          content: synth.content,
          sectionPath, status: 'done', pageIndex: 0,
        });
        blocks.forEach((b, i) => { b.index = i; });
      }

      // Key findings
      for (const kf of (synth.key_findings ?? []).slice(0, 4)) {
        blocks.push({
          id: mkId(), index: blocks.length, kind: 'key_finding',
          title: 'Key Finding', content: kf,
          sectionPath, status: 'done', pageIndex: 0,
        });
      }

      // Source note
      blocks.push({
        id: mkId(), index: blocks.length, kind: 'source_note',
        title: 'Source',
        content: `Generated by Guided Query Contract from dataset ${workspace.dataset_id}. Formula: Σ(${valueCol}${weightCol ? ` × ${weightCol}` : ''}), operation: ${weightOp}.`,
        sectionPath, status: 'done', pageIndex: 0,
      });

      // ── ReportSectionRequest ──────────────────────────────────────────────
      const request: ReportSectionRequest = {
        version: 'report.section.v1',
        requestId: sectionId,
        datasetId: workspace.dataset_id,
        target: {
          templateId,
          signature,
          mode: 'append',
          chapter: { title: chapterTitle, create: true },
          section: { title: sectionTitle, create: true },
        },
        scope: {
          filters: [],
          filterCombinator: 'AND',
          columns: {
            dimensions: selectedCats,
            measures: [{ col: valueCol, agg: weightCol ? 'weighted_mean' : 'sum', weighted: !!weightCol, label: valueCol, weightCol: weightCol || null }],
            include: [...selectedCats, valueCol, ...(weightCol ? [weightCol] : [])],
          },
        },
        description: { text: description, source: 'system' },
        analysis: { type: 'comparison', groupBy: selectedCats },
        components: [
          { type: 'table', title: 'Cross-Tabulation', maxWords: 0, enabled: true },
          { type: 'narrative', title: 'Analysis', maxWords: 300, enabled: true },
          { type: 'key_finding', title: 'Key Findings', maxWords: 0, enabled: true },
        ],
      };

      // ── Handoff bundle — clear stale canvas draft first ──────────────────
      // Wipe any previous canvas layout so the duplicate-anchor sec-N-N issue is avoided
      const layoutKey = `canvas-layout:${templateId}:${signature}`;
      sessionStorage.removeItem(layoutKey);

      const bundle: ReportCanvasHandoffBundle = {
        version: 'report.canvas.handoff.v1',
        templateId,
        signature,
        datasetId: workspace.dataset_id,
        generatedAt: new Date().toISOString(),
        sections: [{
          id: sectionId,
          request,
          blocks,
          meta: { rowsScanned: rows.length, rowsAfterFilter: renderRows.length, groups: tableItems.length },
          addedAt: Date.now(),
        }],
      };

      sessionStorage.setItem(canvasHandoffStorageKey(templateId, signature), JSON.stringify(bundle));
      setLabelMapOpen(false);
      router.push(`/report-builder/canvas/${encodeURIComponent(templateId)}/${encodeURIComponent(signature)}?draftMode=new`);
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Report generation failed.');
      setGenerating(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#f8fafc] px-4 py-6 text-text lg:px-8">
      {/* Viz Modal */}
      {renderRows.length > 0 && (
        <VizModal
          open={vizOpen}
          onClose={() => setVizOpen(false)}
          renderRows={renderRows}
          cats={selectedCats}
          valueCol={valueCol}
          weightCol={weightCol || null}
        />
      )}

      {/* Label Map + Generate Modal */}
      <LabelMapModal
        open={labelMapOpen}
        onClose={() => { if (!generating) setLabelMapOpen(false); }}
        onConfirm={handleGenerateReport}
        cats={selectedCats}
        renderRows={renderRows}
        generating={generating}
      />

      <div className="mx-auto max-w-7xl space-y-5">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/report-builder/binding" className="inline-flex items-center gap-1 text-xs font-medium text-text-muted hover:text-primary">
              <ArrowLeft className="h-3.5 w-3.5" /> Back to binding
            </Link>
            <h1 className="mt-2 text-2xl font-bold text-[#0a1f44]">Guided Query Contract</h1>
            <p className="mt-1 max-w-3xl text-sm text-text-muted">
              Choose categorical grouping columns (C1, C2…) and an aggregator (A1) to build a
              weighted cross-tabulation. Result = <code className="rounded bg-white px-1 py-0.5 text-[11px] text-primary">Σ(value × weight)</code> per group.
            </p>
          </div>
          <Badge variant="default" className="text-[10px]">{workspace?.dataset_id ?? '—'}</Badge>
        </div>

        {/* Step bar */}
        <div className="flex gap-2">
          {(['configure', 'results'] as Step[]).map((s, idx) => {
            const labels = ['1. Configure columns', '2. Cross-tab results'];
            const hints = ['categoricals + aggregator', 'nested weighted table'];
            const active = step === s;
            const enabled = s === 'configure' || canBuild;
            return (
              <button
                key={s}
                type="button"
                disabled={!enabled}
                onClick={() => { if (enabled) setStep(s); }}
                className={`flex-1 rounded-xl border px-4 py-3 text-left transition-all ${active ? 'border-primary bg-white shadow-sm ring-1 ring-primary/20' : enabled ? 'border-border bg-white hover:border-primary/40' : 'border-border bg-white text-text-muted opacity-40'}`}
              >
                <p className={`text-xs font-bold ${active ? 'text-primary' : 'text-[#1e293b]'}`}>{labels[idx]}</p>
                <p className="mt-0.5 text-[10px] text-text-muted">{hints[idx]}</p>
              </button>
            );
          })}
        </div>

        {loading && (
          <Card className="flex items-center gap-3 p-5 text-sm text-text-muted">
            <Loader2 className="h-4 w-4 animate-spin text-primary" /> Loading workspace…
          </Card>
        )}
        {error && <Alert variant="error" title="Error">{error}</Alert>}

        {/* ── Step 1: Configure ── */}
        {step === 'configure' && workspace && (
          <div className="grid gap-5 lg:grid-cols-5">
            {/* Categorical picker */}
            <div className="lg:col-span-3 space-y-4">
              <div className="rounded-2xl border border-border bg-white p-5 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-bold text-[#0a1f44]">Categorical columns</h2>
                    <p className="mt-0.5 text-xs text-text-muted">
                      Select columns to group by. They become C1 (outermost) → C2 → … → Cn
                      (innermost). Reorder with the arrows.
                    </p>
                  </div>
                  <Badge variant={selectedCats.length ? 'success' : 'warning'} className="text-[10px]">
                    {selectedCats.length} selected
                  </Badge>
                </div>

                {selectedCats.length > 0 && (
                  <div className="mt-4 space-y-1.5">
                    <p className="text-[10px] font-bold uppercase tracking-wide text-text-muted">Selected order</p>
                    {selectedCats.map((cat, idx) => {
                      const c = catColor(idx);
                      return (
                        <div
                          key={cat}
                          className="flex items-center gap-2 rounded-xl border px-3 py-2"
                          style={{ borderColor: c.accent + '40', backgroundColor: c.light }}
                        >
                          <GripVertical className="h-4 w-4 text-text-muted" />
                          <span
                            className="flex h-6 w-6 items-center justify-center rounded-md text-[10px] font-black text-white"
                            style={{ backgroundColor: c.accent }}
                          >
                            C{idx + 1}
                          </span>
                          <span className="flex-1 text-sm font-semibold" style={{ color: c.accent }}>{cat}</span>
                          <div className="flex gap-1">
                            <button type="button" onClick={() => moveCat(idx, 'up')} disabled={idx === 0}
                              className="rounded p-0.5 text-text-muted hover:text-primary disabled:opacity-30">
                              <ChevronUp className="h-3.5 w-3.5" />
                            </button>
                            <button type="button" onClick={() => moveCat(idx, 'down')} disabled={idx === selectedCats.length - 1}
                              className="rounded p-0.5 text-text-muted hover:text-primary disabled:opacity-30">
                              <ChevronDown className="h-3.5 w-3.5" />
                            </button>
                            <button type="button" onClick={() => toggleCat(cat)}
                              className="rounded p-0.5 text-text-muted hover:text-red-500">
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="mt-4">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-[10px] font-bold uppercase tracking-wide text-text-muted">
                      All columns ({columns.length}) — click to add
                    </p>
                    {selectedCats.length > 0 && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-bold text-primary">
                        {selectedCats.length} selected
                      </span>
                    )}
                  </div>
                  {/* Scrollable single-column list — no truncation */}
                  <div className="max-h-64 overflow-y-auto rounded-xl border border-border bg-slate-50 p-1.5">
                    <div className="space-y-1">
                      {columns.map((col) => {
                        const selected = selectedCats.includes(col.name);
                        const idx = selectedCats.indexOf(col.name);
                        const c = selected ? catColor(idx) : null;
                        return (
                          <button
                            key={col.name}
                            type="button"
                            title={col.name}
                            onClick={() => toggleCat(col.name)}
                            className={`flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-xs transition-all ${
                              selected
                                ? 'shadow-sm'
                                : 'border-transparent bg-white hover:border-primary/30 hover:bg-primary/5'
                            }`}
                            style={selected ? { borderColor: c!.accent, backgroundColor: c!.light } : {}}
                          >
                            {selected ? (
                              <span
                                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[9px] font-black text-white"
                                style={{ backgroundColor: c!.accent }}
                              >
                                C{idx + 1}
                              </span>
                            ) : (
                              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-white text-[10px] font-bold text-slate-400">
                                +
                              </span>
                            )}
                            {/* Full name, no truncation */}
                            <span
                              className="min-w-0 flex-1 break-all text-[11px] font-semibold leading-tight"
                              style={selected ? { color: c!.accent } : { color: '#1e293b' }}
                            >
                              {col.name}
                            </span>
                            <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${
                              col.role === 'measure'
                                ? 'bg-emerald-100 text-emerald-700'
                                : col.role === 'dimension'
                                  ? 'bg-blue-100 text-blue-700'
                                  : 'bg-slate-100 text-slate-500'
                            }`}>
                              {col.role}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Aggregator config */}
            <div className="lg:col-span-2 space-y-4">
              <div className="rounded-2xl border border-border bg-white p-5 shadow-sm">
                <h2 className="text-sm font-bold text-[#0a1f44]">Aggregator A1</h2>
                <p className="mt-0.5 text-xs text-text-muted">
                  Value column + optional weight. Each row contributes{' '}
                  <code className="rounded bg-surface px-1 text-[10px]">value × weight</code>{' '}
                  to its group result.
                </p>

                <div className="mt-4 space-y-3">
                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wide text-text-muted">
                      Value column *
                    </label>
                    <select
                      value={valueCol}
                      onChange={(e) => setValueCol(e.target.value)}
                      className="mt-1.5 w-full rounded-xl border border-border bg-surface px-3 py-2.5 text-sm text-text outline-none focus:ring-2 focus:ring-primary/20"
                    >
                      <option value="">— select measure —</option>
                      {measureColumns.map((col) => (
                        <option key={col.name} value={col.name}>{col.name}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wide text-text-muted">
                      Weight / multiplier (optional)
                    </label>
                    <select
                      value={weightCol}
                      onChange={(e) => setWeightCol(e.target.value)}
                      className="mt-1.5 w-full rounded-xl border border-border bg-surface px-3 py-2.5 text-sm text-text outline-none focus:ring-2 focus:ring-primary/20"
                    >
                      <option value="">— none (sum only) —</option>
                      {numericColumns.map((col) => (
                        <option key={col.name} value={col.name}>{col.name}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wide text-text-muted">
                      Weight operation
                    </label>
                    <select
                      value={weightOp}
                      onChange={(e) => setWeightOp(e.target.value as WeightOp)}
                      className="mt-1.5 w-full rounded-xl border border-border bg-surface px-3 py-2.5 text-sm text-text outline-none focus:ring-2 focus:ring-primary/20"
                    >
                      <option value="sum">Sum — Σ(value × weight)</option>
                      <option value="average">Average — Σ(value × weight) ÷ count</option>
                      <option value="divide100">Divide by 100 — Σ(value × weight ÷ 100)</option>
                    </select>
                    <p className="mt-1 text-[9px] text-text-muted">
                      {weightOp === 'sum' && 'Each group result = sum of (value × weight) for all rows in group.'}
                      {weightOp === 'average' && 'Each group result = sum of (value × weight) ÷ number of rows in group.'}
                      {weightOp === 'divide100' && 'Each group result = sum of (value × weight ÷ 100), treating weight as a percentage.'}
                    </p>
                  </div>

                  <div>
                    <label className="block text-[10px] font-bold uppercase tracking-wide text-text-muted">
                      Row display cap
                    </label>
                    <select
                      value={rowCapApplied}
                      onChange={(e) => setRowCapApplied(Number(e.target.value))}
                      className="mt-1.5 w-full rounded-xl border border-border bg-surface px-3 py-2.5 text-sm text-text outline-none focus:ring-2 focus:ring-primary/20"
                    >
                      {[50, 100, 200, 500].map((n) => (
                        <option key={n} value={n}>{n} rows</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              {/* Live formula card */}
              {valueCol && (
                <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-text-muted">Live formula</p>
                  <div className="mt-2 rounded-xl border border-primary/20 bg-white px-4 py-3 font-mono text-sm">
                    <span className="text-primary font-black">Σ</span>
                    {' '}
                    <span className="text-[#374151] font-semibold">{valueCol}</span>
                    {weightCol && (
                      <>
                        {' '}<span className="text-text-muted">×</span>{' '}
                        <span className="text-green-700 font-semibold">{weightCol}</span>
                        {weightOp === 'divide100' && (
                          <span className="text-orange-500 font-semibold"> ÷ 100</span>
                        )}
                      </>
                    )}
                    {weightCol && weightOp === 'average' && (
                      <span className="text-purple-600 font-semibold"> ÷ n</span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[10px] text-text-muted">
                    {weightOp === 'sum' && 'Σ per group'}
                    {weightOp === 'average' && 'Weighted average per group'}
                    {weightOp === 'divide100' && 'Weight treated as % (÷100) per group'}
                  </p>
                  {selectedCats.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {selectedCats.map((cat, i) => {
                        const c = catColor(i);
                        return (
                          <span
                            key={cat}
                            className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                            style={{ backgroundColor: c.light, color: c.accent }}
                          >
                            grouped by C{i + 1}: {cat}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              <div className="rounded-xl border border-border bg-white p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-text">{rowsLoading ? 'Loading rows…' : `${rows.length.toLocaleString('en-IN')} rows loaded`}</span>
                  <Badge variant={rows.length ? 'success' : 'muted'} className="text-[9px]">
                    {rows.length ? 'ready' : 'loading'}
                  </Badge>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Build action row */}
        {step === 'configure' && workspace && (
          <div className="rounded-2xl border border-border bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="text-sm font-bold text-[#0a1f44]">Build cross-tabulation</h3>
                <p className="mt-0.5 text-xs text-text-muted">
                  {!canBuild
                    ? 'Select ≥1 categorical column and a value column to proceed.'
                    : `${selectedCats.length} level${selectedCats.length > 1 ? 's' : ''}: ${selectedCats.map((c, i) => `C${i + 1}=${c}`).join(' → ')}  ·  A1 = ${valueCol}${weightCol ? ` × ${weightCol}` : ''}`}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {selectedCats.map((cat, i) => (
                  <ColumnTag key={cat} label={cat} index={i} onRemove={() => toggleCat(cat)} />
                ))}
                <Button type="button" onClick={() => setStep('results')} disabled={!canBuild || rowsLoading}>
                  {rowsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Table2 className="h-4 w-4" />}
                  Build table
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* ── Step 2: Results ── */}
        {step === 'results' && workspace && (
          <div className="space-y-5">
            {/* Config banner + Visualize button */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-2">
                {selectedCats.map((cat, i) => {
                  const c = catColor(i);
                  return (
                    <span
                      key={cat}
                      className="rounded-full border px-2.5 py-1 text-[10px] font-bold"
                      style={{ borderColor: c.accent + '40', backgroundColor: c.light, color: c.accent }}
                    >
                      C{i + 1}: {cat}
                    </span>
                  );
                })}
                <span className="rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-[10px] font-bold text-green-700">
                  A1: {valueCol}
                </span>
                {weightCol && (
                  <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[10px] font-bold text-amber-700">
                    × {weightCol}
                  </span>
                )}
                <span className="rounded-full border border-border bg-surface px-2.5 py-1 text-[10px] text-text-muted">
                  {renderRows.length} rows
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setVizOpen(true)}
                  disabled={renderRows.length === 0}
                >
                  <GitMerge className="h-4 w-4" />
                  Visualize flow
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={() => setStep('configure')}>
                  <ArrowLeft className="h-3.5 w-3.5" /> Reconfigure
                </Button>
              </div>
            </div>

            {renderRows.length === 0 ? (
              <Alert variant="warning">No rows match. Try adjusting the row cap or check the dataset loaded correctly.</Alert>
            ) : (
              <>
                <SummaryCards renderRows={renderRows} cats={selectedCats} />

                <div className="overflow-hidden rounded-2xl border border-border bg-white shadow-sm">
                  <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
                    <h2 className="flex items-center gap-2 text-sm font-bold text-[#0a1f44]">
                      <Sigma className="h-4 w-4 text-primary" />
                      Weighted cross-tabulation
                    </h2>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedCats.map((cat, i) => {
                        const c = catColor(i);
                        return (
                          <span key={i} className="flex items-center gap-1 text-[10px]" style={{ color: c.accent }}>
                            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: c.accent }} />
                            C{i + 1}={cat}
                          </span>
                        );
                      })}
                      <span className="text-[10px] text-text-muted ml-1">
                        {weightCol ? `weighted by ${weightCol}` : 'unweighted sum'}
                      </span>
                    </div>
                  </div>
                  <div className="p-4">
                    <ResultTable
                      renderRows={renderRows}
                      cats={selectedCats}
                      valueCol={valueCol}
                      weightCol={weightCol || null}
                      weightOp={weightOp}
                    />
                  </div>
                </div>
              </>
            )}

            {/* Generate Report card */}
            {genError && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                <strong>Generation failed:</strong> {genError}
              </div>
            )}
            <div className="rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/5 to-blue-50 p-5 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h3 className="flex items-center gap-2 text-sm font-bold text-[#0a1f44]">
                    <FileText className="h-4 w-4 text-primary" />
                    Generate Report
                  </h3>
                  <p className="mt-1 text-xs text-slate-500">
                    Map category codes to readable labels, then send this cross-tabulation to the
                    report canvas via the LLM synthesizer (Azure / OpenRouter).
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                      {selectedCats.length} dimension{selectedCats.length > 1 ? 's' : ''}
                    </span>
                    <span className="rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-[10px] font-semibold text-green-700">
                      {valueCol}{weightCol ? ` × ${weightCol}` : ''}
                    </span>
                    <span className="rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                      {renderRows.length} rows · {weightOp}
                    </span>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <button
                    type="button"
                    onClick={() => { setGenError(null); setLabelMapOpen(true); }}
                    disabled={!renderRows.length || generating}
                    className="flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white shadow hover:bg-primary/90 disabled:opacity-50"
                  >
                    {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                    {generating ? 'Generating…' : 'Proceed to Report Generation'}
                    {!generating && <ArrowRight className="h-4 w-4" />}
                  </button>
                  <p className="text-[9px] text-slate-400">
                    Maps labels → synthesizes with LLM → opens Report Canvas
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
