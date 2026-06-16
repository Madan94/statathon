'use client';
import { useEffect, useRef, useState } from 'react';
import { Download, BarChart3, BarChartHorizontal, PieChart, LineChart } from 'lucide-react';
import type { FigureData, ChartType } from '../engine/figureModel';
import { autoChartType } from '../engine/figureModel';

/* ═══════════════════════════════════════════════════════════════════
   FigureChart (T1) — real Apache ECharts rendering of a figure dataset.
   • Lazy-loads echarts (keeps the canvas bundle small).
   • MoSPI navy palette, Indian-number axis, data labels, tooltips.
   • Top-N + "Others" collapse for long category lists.
   • Type override (bar / hbar / donut / line) + PNG export.
   ═══════════════════════════════════════════════════════════════════ */

const PALETTE = ['#0B5394', '#1F7A1F', '#B45F06', '#741B47', '#594F8D', '#0C6E6E', '#8B5A00', '#2E5A88'];
const INK = '#1a1a1a';
const TOP_N = 12;

function fmtIndian(v: number): string {
  if (Math.abs(v) >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
  if (Math.abs(v) >= 1e5) return (v / 1e5).toFixed(2) + ' L';
  if (Math.abs(v) >= 1000) return v.toLocaleString('en-IN', { maximumFractionDigits: 1 });
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

interface Props {
  data: FigureData;
  /** Caption like "Figure 1.1". */
  caption?: string;
  title: string;
  /** Forced type; defaults to auto. */
  type?: ChartType;
  /** Show the small type-switch + export toolbar (editor only). */
  controls?: boolean;
  height?: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EChartsInstance = any;

export function FigureChart({ data, caption, title, type, controls = true, height = 200 }: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<EChartsInstance>(null);
  const [chartType, setChartType] = useState<ChartType>(type || autoChartType(data));

  useEffect(() => { setChartType(type || autoChartType(data)); }, [type, data]);

  useEffect(() => {
    let disposed = false;
    const el = elRef.current;
    if (!el) return;

    void (async () => {
      const echarts = await import('echarts');
      if (disposed || !elRef.current) return;
      const inst = instRef.current || echarts.init(elRef.current);
      instRef.current = inst;

      // Top-N + Others collapse for long lists.
      const sorted = [...data.points].sort((a, b) => b.value - a.value);
      let pts = sorted;
      if (sorted.length > TOP_N) {
        const head = sorted.slice(0, TOP_N - 1);
        const othersVal = sorted.slice(TOP_N - 1).reduce((s, p) => s + p.value, 0);
        pts = [...head, { label: 'Others', value: othersVal }];
      }
      const cats = pts.map(p => p.label);
      const vals = pts.map(p => p.value);
      const unit = data.unit ? ` (${data.unit})` : '';

      const baseGrid = { left: 8, right: 24, top: 16, bottom: 8, containLabel: true };
      let option: Record<string, unknown>;

      if (chartType === 'donut' || chartType === 'pie') {
        option = {
          color: PALETTE,
          tooltip: { trigger: 'item', formatter: (p: { name: string; value: number; percent: number }) => `${p.name}: ${fmtIndian(p.value)} (${p.percent}%)` },
          legend: { type: 'scroll', bottom: 0, textStyle: { color: INK, fontSize: 9 } },
          series: [{
            type: 'pie', radius: chartType === 'donut' ? ['42%', '70%'] : '70%',
            center: ['50%', '46%'],
            data: pts.map(p => ({ name: p.label, value: p.value })),
            label: { fontSize: 9, formatter: (p: { percent: number }) => `${p.percent}%` },
          }],
        };
      } else if (chartType === 'line') {
        option = {
          color: PALETTE, tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtIndian(v) },
          grid: baseGrid,
          xAxis: { type: 'category', data: cats, axisLabel: { fontSize: 8, color: INK, rotate: cats.length > 8 ? 35 : 0 } },
          yAxis: { type: 'value', name: unit, nameTextStyle: { fontSize: 8 }, axisLabel: { fontSize: 8, formatter: (v: number) => fmtIndian(v) } },
          series: [{ type: 'line', data: vals, smooth: true, areaStyle: { opacity: 0.08 }, label: { show: false } }],
        };
      } else {
        const horizontal = chartType === 'hbar';
        const catAxis = { type: 'category', data: cats, axisLabel: { fontSize: 8, color: INK, rotate: !horizontal && cats.length > 8 ? 35 : 0 } };
        const valAxis = { type: 'value', name: unit, nameTextStyle: { fontSize: 8 }, axisLabel: { fontSize: 8, formatter: (v: number) => fmtIndian(v) } };
        option = {
          color: PALETTE, tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtIndian(v) },
          grid: { ...baseGrid, left: horizontal ? 8 : 8 },
          xAxis: horizontal ? valAxis : catAxis,
          yAxis: horizontal ? { ...catAxis, inverse: true } : valAxis,
          series: [{
            type: 'bar', data: vals, barMaxWidth: 22,
            itemStyle: { borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] },
            label: { show: pts.length <= 12, position: horizontal ? 'right' : 'top', fontSize: 8, formatter: (p: { value: number }) => fmtIndian(p.value) },
          }],
        };
      }

      inst.setOption(option, true);
      inst.resize();
    })();

    return () => { disposed = true; };
  }, [data, chartType]);

  // Resize with the container.
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => instRef.current?.resize());
    ro.observe(el);
    return () => { ro.disconnect(); instRef.current?.dispose?.(); instRef.current = null; };
  }, []);

  const exportPng = () => {
    const url = instRef.current?.getDataURL?.({ pixelRatio: 2, backgroundColor: '#fff' });
    if (!url) return;
    const a = document.createElement('a');
    a.href = url; a.download = `${caption || title}.png`.replace(/\s+/g, '_'); a.click();
  };

  const TYPE_BTNS: Array<{ t: ChartType; icon: typeof BarChart3; title: string }> = [
    { t: 'bar', icon: BarChart3, title: 'Vertical bar' },
    { t: 'hbar', icon: BarChartHorizontal, title: 'Horizontal bar' },
    { t: 'donut', icon: PieChart, title: 'Donut' },
    { t: 'line', icon: LineChart, title: 'Line' },
  ];

  return (
    <figure className="overflow-hidden rounded border border-slate-300 bg-white">
      <figcaption className="doc-caption flex items-center justify-between border-b border-slate-200 bg-slate-100 px-3 py-1.5">
        <span className="text-[10px] font-semibold text-slate-700">{caption ? `${caption} — ${title}` : title}</span>
        {controls && (
          <div className="flex items-center gap-0.5" onPointerDown={e => e.stopPropagation()}>
            {TYPE_BTNS.map(({ t, icon: Icon, title: tt }) => (
              <button key={t} onClick={() => setChartType(t)} title={tt}
                className={`rounded p-1 ${chartType === t ? 'bg-blue-100 text-blue-600' : 'text-slate-400 hover:bg-slate-200'}`}><Icon className="h-3 w-3" /></button>
            ))}
            <span className="mx-0.5 h-3 w-px bg-slate-300" />
            <button onClick={exportPng} title="Export PNG" className="rounded p-1 text-slate-400 hover:bg-slate-200"><Download className="h-3 w-3" /></button>
          </div>
        )}
      </figcaption>
      <div ref={elRef} style={{ height }} className="w-full" />
      {(data.unit || data.source) && (
        <figcaption className="doc-caption border-t border-slate-100 px-3 py-1 text-[8.5px] text-slate-400">
          {data.unit && <>Unit: {data.unit}</>}{data.unit && data.source && ' · '}{data.source && <>Source: {data.source}</>}
        </figcaption>
      )}
    </figure>
  );
}
