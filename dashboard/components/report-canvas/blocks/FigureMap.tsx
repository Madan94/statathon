'use client';
import { useEffect, useRef, useState } from 'react';
import type { FigureData } from '../engine/figureModel';
import { classify, MAP_RAMP, normaliseState, type ClassMethod } from '../engine/mapClassify';

/* ═══════════════════════════════════════════════════════════════════
   FigureMap (T2) — India State/UT choropleth via ECharts `map` series.
   • Lazy-loads echarts + India GeoJSON (registered once).
   • Classification: quantile / equal-interval / natural-breaks + class
     count, with a sequential MoSPI ramp + legend.
   • State-name normaliser matches table labels to GeoJSON features.
   ═══════════════════════════════════════════════════════════════════ */

// Public India States GeoJSON (lazy-fetched, registered once).
const INDIA_GEOJSON_URL = 'https://cdn.jsdelivr.net/gh/Subhash9325/GeoJson-Data-of-Indian-States@master/Indian_States';

let indiaRegistered = false;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function ensureIndiaMap(echarts: any): Promise<boolean> {
  if (indiaRegistered) return true;
  try {
    const res = await fetch(INDIA_GEOJSON_URL);
    if (!res.ok) return false;
    const geo = await res.json();
    echarts.registerMap('india', geo);
    indiaRegistered = true;
    return true;
  } catch {
    return false;
  }
}

interface Props {
  data: FigureData;
  caption?: string;
  title: string;
  controls?: boolean;
  height?: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EChartsInstance = any;

export function FigureMap({ data, caption, title, controls = true, height = 320 }: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<EChartsInstance>(null);
  const [method, setMethod] = useState<ClassMethod>('quantile');
  const [classes, setClasses] = useState(5);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let disposed = false;
    const el = elRef.current;
    if (!el) return;

    void (async () => {
      const echarts = await import('echarts');
      if (disposed || !elRef.current) return;
      const ok = await ensureIndiaMap(echarts);
      if (disposed) return;
      if (!ok) { setFailed(true); return; }

      const inst = instRef.current || echarts.init(elRef.current);
      instRef.current = inst;

      const mapped = data.points.map(p => ({ name: normaliseState(p.label), value: p.value }));
      const values = mapped.map(m => m.value);
      const breaks = classify(values, method, classes);
      const pieces = breaks.bounds.map((b, i) => ({
        lte: b,
        gt: i === 0 ? undefined : breaks.bounds[i - 1],
        color: MAP_RAMP[Math.min(MAP_RAMP.length - 1, Math.floor((i / Math.max(1, classes - 1)) * (MAP_RAMP.length - 1)))],
      }));

      inst.setOption({
        tooltip: {
          trigger: 'item',
          formatter: (p: { name: string; value: number }) => {
            const v = Number.isFinite(p.value) ? p.value.toLocaleString('en-IN') : 'n/a';
            const share = data.total > 0 && Number.isFinite(p.value) ? ` (${((p.value / data.total) * 100).toFixed(1)}%)` : '';
            return `${p.name}: ${v}${share}`;
          },
        },
        visualMap: {
          type: 'piecewise', pieces: pieces.reverse(), left: 8, bottom: 8,
          textStyle: { fontSize: 8 }, itemWidth: 12, itemHeight: 10,
          text: [data.unit || 'High', 'Low'],
        },
        series: [{
          type: 'map', map: 'india', roam: false,
          data: mapped,
          label: { show: false },
          emphasis: { label: { show: true, fontSize: 8 }, itemStyle: { areaColor: '#f5c518' } },
          itemStyle: { borderColor: '#fff', borderWidth: 0.5, areaColor: '#f0f0f0' },
        }],
      }, true);
      inst.resize();
    })();

    return () => { disposed = true; };
  }, [data, method, classes]);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => instRef.current?.resize());
    ro.observe(el);
    return () => { ro.disconnect(); instRef.current?.dispose?.(); instRef.current = null; };
  }, []);

  return (
    <figure className="overflow-hidden rounded border border-slate-300 bg-white">
      <figcaption className="doc-caption flex items-center justify-between border-b border-slate-200 bg-slate-100 px-3 py-1.5">
        <span className="text-[10px] font-semibold text-slate-700">{caption ? `${caption} — ${title}` : title}</span>
        {controls && !failed && (
          <div className="flex items-center gap-1" onPointerDown={e => e.stopPropagation()}>
            <select value={method} onChange={e => setMethod(e.target.value as ClassMethod)} title="Classification"
              className="rounded border border-slate-200 bg-white px-1 py-0.5 text-[8px] text-slate-600">
              <option value="quantile">Quantile</option>
              <option value="equal">Equal-interval</option>
              <option value="jenks">Natural breaks</option>
            </select>
            <select value={classes} onChange={e => setClasses(Number(e.target.value))} title="Classes"
              className="rounded border border-slate-200 bg-white px-1 py-0.5 text-[8px] text-slate-600">
              {[3, 4, 5, 6].map(c => <option key={c} value={c}>{c} classes</option>)}
            </select>
          </div>
        )}
      </figcaption>
      {failed ? (
        <div className="px-3 py-8 text-center text-[10px] text-slate-400">
          Map data unavailable offline. Connect to load the India boundary, or use the chart view.
        </div>
      ) : (
        <div ref={elRef} style={{ height }} className="w-full" />
      )}
      {(data.unit || data.source) && !failed && (
        <figcaption className="doc-caption border-t border-slate-100 px-3 py-1 text-[8.5px] text-slate-400">
          {data.unit && <>Unit: {data.unit}</>}{data.unit && data.source && ' · '}{data.source && <>Source: {data.source}</>}
        </figcaption>
      )}
    </figure>
  );
}
