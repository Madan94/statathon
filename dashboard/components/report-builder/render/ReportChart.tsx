'use client';

/**
 * R3 — ECharts wrapper. Lazily imports echarts (heavy) on mount, renders the
 * option from `chartSpecToOption`, and keeps it responsive via ResizeObserver.
 */
import { useEffect, useRef } from 'react';
import type { EChartsType } from 'echarts';

import type { Chart, Locale } from '@/lib/report/types';
import {
  chartSpecToOption,
  DEFAULT_CHART_THEME,
  type ChartTheme,
} from '@/lib/report/chartOption';
import { loc } from '@/lib/report/format';

interface Props {
  chart: Chart;
  theme?: ChartTheme;
  locale?: Locale;
  height?: number;
}

export function ReportChart({
  chart,
  theme = DEFAULT_CHART_THEME,
  locale = 'en-IN',
  height = 320,
}: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const instRef = useRef<EChartsType | null>(null);

  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | undefined;
    const el = ref.current;
    if (!el) return;

    void (async () => {
      const echarts = await import('echarts');
      if (disposed) return;
      const inst = echarts.init(el);
      instRef.current = inst;
      inst.setOption(chartSpecToOption(chart, theme, locale));
      ro = new ResizeObserver(() => inst.resize());
      ro.observe(el);
    })();

    return () => {
      disposed = true;
      ro?.disconnect();
      instRef.current?.dispose();
      instRef.current = null;
    };
  }, [chart, theme, locale]);

  return (
    <div
      ref={ref}
      style={{ width: '100%', height }}
      role="img"
      aria-label={loc(chart.title, locale) || 'chart'}
    />
  );
}
