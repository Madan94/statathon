/* ═══════════════════════════════════════════════════════════════════
   Figure model (T1/T5) — turns a canvas block's table data into a
   normalised chart dataset + an auto-selected chart type.

   Pure + framework-free. Reused by FigureChart (echarts) and FigureMap.
   ═══════════════════════════════════════════════════════════════════ */

import type { PageBlock } from './useCanvasState';

export type ChartType = 'bar' | 'hbar' | 'pie' | 'donut' | 'line' | 'stacked';
export type FigureView = 'table' | 'chart' | 'map' | 'both';

export interface FigurePoint {
  label: string;
  value: number;
  rowIds?: string[];
}

export interface FigureData {
  points: FigurePoint[];
  measure: string;
  dimension: string;
  unit?: string;
  source?: string;
  total: number;
}

const MAX_BAR_CATEGORIES = 12;

/** Pull the row array from any of the known analytics shapes. */
function rows(td: Record<string, unknown> | undefined): Array<Record<string, unknown>> {
  if (!td) return [];
  const r = (td.items || td.rankingData || td.aggregationData || td.rows || []) as Array<Record<string, unknown>>;
  return Array.isArray(r) ? r : [];
}

/** Extract a normalised figure dataset from a block. */
export function figureDataOf(block: PageBlock): FigureData | null {
  const td = block.tableData;
  const rs = rows(td);
  if (!rs.length) return null;

  const dim = (() => {
    const k = rs.find(r => r.key)?.key as Record<string, string> | undefined;
    return k ? Object.keys(k)[0] : 'Category';
  })();
  const measure = (td?.measure as string) || block.title || 'Value';

  const points: FigurePoint[] = rs.map((r, i) => {
    const key = r.key as Record<string, string> | undefined;
    const label = key ? Object.values(key)[0] : (r.label as string) || `#${i + 1}`;
    const value = typeof r.value === 'number' ? r.value : Number(r.value) || 0;
    return { label, value, rowIds: (r.rowIds as string[]) || undefined };
  });

  const total = points.reduce((s, p) => s + (p.value || 0), 0);
  return {
    points,
    measure,
    dimension: dim,
    unit: (td?.unit as string) || block.metricUnit || undefined,
    source: (td?.source as string) || undefined,
    total,
  };
}

/** Whether a block carries chartable tabular data. */
export function isChartable(block: PageBlock): boolean {
  return block.kind === 'table' || block.kind === 'chart';
}

/** Whether the dimension looks like Indian States/UTs (map-eligible). */
export function isStateData(data: FigureData | null): boolean {
  if (!data) return false;
  return /state|ut|region/i.test(data.dimension);
}

/**
 * Auto-select the best chart type from the data shape (T1 ②):
 *  • many categories → horizontal bar (readable labels)
 *  • few categories that sum to a meaningful whole → donut (share)
 *  • otherwise → vertical bar.
 */
export function autoChartType(data: FigureData): ChartType {
  const n = data.points.length;
  if (n > MAX_BAR_CATEGORIES) return 'hbar';
  // Part-of-whole: 2–6 slices where each is a real share.
  if (n >= 2 && n <= 6 && data.total > 0) {
    const allPositive = data.points.every(p => p.value >= 0);
    if (allPositive) return 'donut';
  }
  return 'bar';
}
