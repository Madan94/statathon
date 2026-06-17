'use client';

/**
 * Generic Apache ECharts wrapper.
 *
 * Lazily imports echarts (heavy) on mount, renders the supplied option, and
 * keeps the canvas responsive via a ResizeObserver. Used for the advanced
 * visualisations (gantt timelines, heatmaps, gauges) on the Audit Logs and
 * Analysis pages where ECharts is a better fit than Recharts' declarative API.
 */
import { useEffect, useRef } from 'react';
import type { EChartsOption, EChartsType } from 'echarts';

interface EChartProps {
  option: EChartsOption;
  height?: number | string;
  className?: string;
  /** Accessible label describing what the chart shows. */
  ariaLabel?: string;
}

export function EChart({ option, height = 320, className, ariaLabel }: EChartProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const instRef = useRef<EChartsType | null>(null);

  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | undefined;
    const el = ref.current;
    if (!el) return;

    void (async () => {
      const echarts = await import('echarts');
      if (disposed || !ref.current) return;
      const inst = echarts.init(el);
      instRef.current = inst;
      inst.setOption(option);
      ro = new ResizeObserver(() => inst.resize());
      ro.observe(el);
    })();

    return () => {
      disposed = true;
      ro?.disconnect();
      instRef.current?.dispose();
      instRef.current = null;
    };
    // Re-run whenever the option object identity changes.
  }, [option]);

  return (
    <div
      ref={ref}
      className={className}
      style={{ width: '100%', height }}
      role="img"
      aria-label={ariaLabel || 'chart'}
    />
  );
}

export default EChart;
