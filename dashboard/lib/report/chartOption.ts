/**
 * R3 — map a `chartAST` chart to an Apache ECharts option. Mirrors the server
 * SVG kit (`render/svg_charts.py`): same 7 types and the same density rule
 * (categorical bar charts with > 12 categories render horizontally), so the
 * interactive preview matches the exported HTML/PDF.
 */
import type { EChartsOption } from 'echarts';

import type { Chart, ChartSeries, Locale } from './types';
import { formatValue, loc } from './format';

export interface ChartTheme {
  palette: string[];
  ink: string;
  muted: string;
  line: string;
}

/** Default theme palette — matches `theme.py` `mospi_navy`. */
export const DEFAULT_CHART_THEME: ChartTheme = {
  palette: ['#1F7A1F', '#0B5394', '#B45F06', '#741B47', '#594F8D', '#0C6E6E'],
  ink: '#1a1a1a',
  muted: '#5a5a5a',
  line: '#d9d9d9',
};

export const MAX_CATEGORIES = 12;

function categories(series: ChartSeries[], locale: Locale): string[] {
  for (const s of series) {
    if (s.points && s.points.length) return s.points.map((p) => loc(p.x, locale));
  }
  return [];
}

function unitOf(chart: Chart): string | undefined {
  return chart.yAxis?.unit;
}

function axisValueFormatter(unit?: string) {
  return (v: number | string) =>
    typeof v === 'number' ? formatValue(v, { unit, system: 'indian' }) : String(v);
}

function baseOption(chart: Chart, theme: ChartTheme, locale: Locale): EChartsOption {
  const multi = (chart.series?.length ?? 0) > 1;
  return {
    color: theme.palette,
    title: chart.title
      ? { text: loc(chart.title, locale), left: 'center', textStyle: { fontSize: 14, color: theme.ink } }
      : undefined,
    tooltip: { trigger: 'item' },
    legend: multi ? { bottom: 0, textStyle: { color: theme.ink } } : undefined,
    grid: { left: 56, right: 24, top: chart.title ? 40 : 16, bottom: multi ? 48 : 36, containLabel: true },
  };
}

function emptyOption(): EChartsOption {
  return {
    title: { text: 'No data', left: 'center', top: 'middle', textStyle: { color: '#b00', fontSize: 13 } },
  };
}

/** Build the ECharts option for a chart spec. */
export function chartSpecToOption(
  chart: Chart,
  theme: ChartTheme = DEFAULT_CHART_THEME,
  locale: Locale = 'en-IN',
): EChartsOption {
  const series = chart.series ?? [];
  const ctype = (chart.chartType ?? 'bar').toLowerCase();
  const unit = unitOf(chart);
  const cats = categories(series, locale);
  const base = baseOption(chart, theme, locale);

  if (!series.length || !cats.length) {
    if (ctype !== 'pie' && ctype !== 'donut') return emptyOption();
  }

  // Pie / donut.
  if (ctype === 'pie' || ctype === 'donut') {
    const pts = series[0]?.points ?? [];
    if (!pts.length) return emptyOption();
    return {
      ...base,
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0, textStyle: { color: theme.ink } },
      series: [
        {
          type: 'pie',
          radius: ctype === 'donut' ? ['45%', '70%'] : '70%',
          data: pts.map((p, i) => ({
            name: loc(p.x, locale),
            value: p.y,
            itemStyle: p.color ? { color: p.color } : { color: theme.palette[i % theme.palette.length] },
          })),
          label: { formatter: '{d}%' },
        },
      ],
    };
  }

  // Density rule: single-series categorical bar with too many categories → horizontal.
  const horizontal = (ctype === 'bar' || ctype === 'simple_bar') && cats.length > MAX_CATEGORIES;

  const catAxis = { type: 'category' as const, data: cats, axisLabel: { color: theme.ink } };
  const valAxis = {
    type: 'value' as const,
    axisLabel: { color: theme.muted, formatter: axisValueFormatter(unit) },
    splitLine: { lineStyle: { color: theme.line } },
  };

  // Line.
  if (ctype === 'line' || ctype === 'time_series' || ctype === 'trend') {
    return {
      ...base,
      xAxis: catAxis,
      yAxis: valAxis,
      series: series.map((s, i) => ({
        type: 'line' as const,
        name: loc(s.label, locale) || `Series ${i + 1}`,
        data: s.points.map((p) => p.y),
        smooth: false,
        itemStyle: { color: theme.palette[i % theme.palette.length] },
      })),
    };
  }

  // Stacked (absolute or 100%).
  const stacked = ctype === 'stacked_bar';
  const normalize = ctype === 'stacked_100' || ctype === 'stacked_percent' || ctype === 'distribution';

  // Column totals for normalization.
  const totals = cats.map((_, ci) =>
    series.reduce((acc, s) => acc + (s.points[ci]?.y ?? 0), 0),
  );

  const barSeries = series.map((s, i) => ({
    type: 'bar' as const,
    name: loc(s.label, locale) || `Series ${i + 1}`,
    stack: stacked || normalize ? 'total' : undefined,
    data: s.points.map((p, ci) =>
      normalize ? Math.round(((p.y ?? 0) / (totals[ci] || 1)) * 1000) / 10 : p.y,
    ),
    itemStyle: { color: theme.palette[i % theme.palette.length] },
  }));

  if (horizontal) {
    return {
      ...base,
      xAxis: { ...valAxis },
      yAxis: { ...catAxis },
      series: series.map((s, i) => ({
        type: 'bar' as const,
        name: loc(s.label, locale) || `Series ${i + 1}`,
        data: s.points.map((p) => p.y),
        itemStyle: { color: theme.palette[i % theme.palette.length] },
      })),
    };
  }

  return {
    ...base,
    xAxis: catAxis,
    yAxis: normalize ? { ...valAxis, max: 100, axisLabel: { color: theme.muted, formatter: '{value}%' } } : valAxis,
    series: barSeries,
  };
}
