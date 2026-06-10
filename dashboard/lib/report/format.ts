/**
 * R3 — number / value formatting for the React preview, kept in parity with the
 * server `report_builder/generation/render/numbers.py` so the preview and the
 * exported HTML/PDF show identical strings.
 */
import type { Locale, LocalizedLabel, NumberSystem } from './types';

export const EM_DASH = '\u2014';

const UNIT_SUFFIX: Record<string, string> = {
  percent: '%',
  pct: '%',
  mw: ' MW',
  million_tonnes: ' Mt',
  mt: ' Mt',
  inr: '\u20b9',
  rupee: '\u20b9',
};
const PREFIX_UNITS = new Set(['inr', 'rupee']);

/** Split a format token like `percent.1` / `number.0` → [kind, decimals]. */
export function parseFormat(fmt?: string | null): [string, number] {
  if (!fmt) return ['number', 1];
  const idx = fmt.lastIndexOf('.');
  if (idx >= 0) {
    const kind = fmt.slice(0, idx) || 'number';
    const dec = parseInt(fmt.slice(idx + 1), 10);
    return [kind, Number.isNaN(dec) ? 1 : dec];
  }
  return [fmt, 1];
}

function groupIndian(intStr: string): string {
  if (intStr.length <= 3) return intStr;
  const last3 = intStr.slice(-3);
  const rest = intStr.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return `${rest},${last3}`;
}

function groupInternational(intStr: string): string {
  return intStr.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function grouped(n: number, decimals: number, system: NumberSystem): string {
  const neg = n < 0;
  const fixed = Math.abs(n).toFixed(decimals);
  const dot = fixed.indexOf('.');
  const intPart = dot >= 0 ? fixed.slice(0, dot) : fixed;
  const decPart = dot >= 0 ? fixed.slice(dot + 1) : '';
  const g = system === 'indian' ? groupIndian(intPart) : groupInternational(intPart);
  const out = decPart ? `${g}.${decPart}` : g;
  return neg ? `-${out}` : out;
}

export interface FormatOpts {
  unit?: string | null;
  fmt?: string | null;
  system?: NumberSystem;
  empty?: string;
}

/** Format a measured value to its display string (Indian grouping by default). */
export function formatValue(value: unknown, opts: FormatOpts = {}): string {
  const { unit, fmt, system = 'indian', empty = EM_DASH } = opts;
  if (value === null || value === undefined) return empty;
  if (typeof value === 'boolean') return String(value);
  if (typeof value === 'number') {
    const [kind, decimals] = parseFormat(fmt ?? undefined);
    const isInt = Number.isInteger(value) && (!fmt || !fmt.includes('.'));
    const body =
      kind === 'number' && isInt
        ? grouped(value, 0, system)
        : grouped(value, decimals, system);
    const u = (unit ?? '').toLowerCase();
    if (kind === 'percent' || u === 'percent' || u === 'pct') return `${body}%`;
    if (PREFIX_UNITS.has(u)) return `${UNIT_SUFFIX[u]}${body}`;
    if (UNIT_SUFFIX[u]) return `${body}${UNIT_SUFFIX[u]}`;
    return body;
  }
  return String(value);
}

/** Resolve a possibly-bilingual label for the given locale (plain string passes through). */
export function loc(label: LocalizedLabel | undefined | null, locale: Locale = 'en-IN'): string {
  if (label === null || label === undefined) return '';
  if (typeof label === 'object') {
    const lang = String(locale).toLowerCase().startsWith('hi') ? 'hi' : 'en';
    const other = lang === 'hi' ? 'en' : 'hi';
    const picked =
      label[lang] ?? label[other] ?? Object.values(label).find((v) => Boolean(v));
    return picked != null ? String(picked) : '';
  }
  return String(label);
}
