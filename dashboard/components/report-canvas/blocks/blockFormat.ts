import { applyNumerals } from '../engine/typography';

/* ═══════════════════════════════════════════════════════════════════
   blockFormat — shared formatters + table-shape helpers used by the
   per-kind block components. Extracted verbatim from BlockRenderer so
   every kind renders numbers and table columns identically.
   ═══════════════════════════════════════════════════════════════════ */

export type TableRow = { rank?: number; key?: Record<string, string>; value?: number; n?: number };

/** Indian-format a number; em-dash only for genuinely missing (null/NaN). */
export function fmtNum(n: number | string | undefined | null): string {
  if (n == null || n === '') return '\u2014';
  const v = typeof n === 'string' ? parseFloat(n) : n;
  if (v == null || isNaN(v)) return '\u2014';
  if (Math.abs(v) >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
  if (Math.abs(v) >= 1e5) return (v / 1e5).toFixed(2) + ' L';
  if (Math.abs(v) >= 1000) return v.toLocaleString('en-IN', { maximumFractionDigits: 1 });
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

/** Format a number then apply the document numeral system (T6). */
export function makeNum(numerals: 'intl' | 'devanagari') {
  return (v: number | string | undefined | null) => applyNumerals(fmtNum(v), numerals);
}

/** Pull the row array from any of the known analytics shapes. */
export function tableRows(td: Record<string, unknown> | undefined): TableRow[] {
  if (!td) return [];
  const rows = (td.items || td.rankingData || td.aggregationData || td.rows || []) as TableRow[];
  return Array.isArray(rows) ? rows : [];
}

/** Real dimension column name (e.g. "State/UT") from the first row's key. */
export function dimensionName(rows: TableRow[], fallback = 'Category'): string {
  const k = rows.find(r => r.key)?.key;
  return k ? Object.keys(k)[0] : fallback;
}

/** Real measure column name from the tableData (binding measure), else title. */
export function measureName(td: Record<string, unknown> | undefined, fallback: string): string {
  const direct = typeof td?.measure === 'string' ? td.measure : '';
  const slot = td?.slot as Record<string, unknown> | undefined;
  const fromSlot = typeof slot?.measure === 'string' ? slot.measure : '';
  return direct || fromSlot || fallback;
}
