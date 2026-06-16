/* ═══════════════════════════════════════════════════════════════════
   Statistical markers (S1) — MoSPI/NSO disclosure vocabulary.

   Practical "computed reliability" tier:
   • Renders the standard symbols when a row carries flags or a value is
     nil / not-available.
   • COMPUTES the Relative Standard Error (RSE) from a standard error or
     variance (+ optional n) when present, and flags estimates with
     RSE > 20% as "use with caution" (*).
   • Degrades gracefully: a plain numeric row with no flags / no variance
     renders as an ordinary number (no noise).

   Pure, framework-free — used by the table renderer + a future QA pass.
   ═══════════════════════════════════════════════════════════════════ */

export type Marker = 'provisional' | 'revised' | 'nil' | 'negligible' | 'na' | 'caution';

/** Glyph shown inline with / in place of the value. */
export const MARKER_SYMBOL: Record<Marker, string> = {
  provisional: '\u1d3e',   // ᴾ
  revised: '\u1d3f',       // ᴿ
  nil: '\u2013',           // –
  negligible: 'N',
  na: '..',
  caution: '*',
};

/** Legend line shown beneath a table that uses the marker. */
export const MARKER_LEGEND: Record<Marker, string> = {
  provisional: '\u1d3e provisional',
  revised: '\u1d3f revised',
  nil: '\u2013 nil / negligible',
  negligible: 'N negligible',
  na: '.. not available',
  caution: '* estimate has RSE > 20% \u2014 use with caution',
};

export interface RowMarkerResult {
  /** When set, render THIS instead of the number (nil / negligible / n-a). */
  override?: string;
  /** Superscript marker glyphs appended to the number (ᴾ / ᴿ / *). */
  suffix: string;
  /** Markers used (to build the table legend). */
  used: Marker[];
}

type LooseRow = {
  value?: number | null;
  n?: number;
  se?: number;
  std_error?: number;
  variance?: number;
  rse?: number;
  cv?: number;
  flag?: string;
  marker?: string;
  quality?: string;
};

/** Normalise an explicit flag string to a Marker, if recognised. */
function flagToMarker(flag?: string): Marker | null {
  if (!flag) return null;
  const f = flag.toLowerCase();
  if (f === 'p' || f.includes('provisional')) return 'provisional';
  if (f === 'r' || f.includes('revised')) return 'revised';
  if (f.includes('negligible')) return 'negligible';
  if (f === 'na' || f.includes('not available') || f.includes('n/a')) return 'na';
  return null;
}

/** Relative Standard Error (%) from SE/variance + value; null if uncomputable. */
export function computeRSE(row: LooseRow): number | null {
  const value = row.value;
  if (value == null || value === 0 || isNaN(value)) return null;
  if (row.rse != null) return Math.abs(row.rse);
  if (row.cv != null) return Math.abs(row.cv);
  let se = row.se ?? row.std_error;
  if (se == null && row.variance != null) {
    const varr = row.n && row.n > 0 ? row.variance / row.n : row.variance;
    se = Math.sqrt(Math.max(0, varr));
  }
  if (se == null) return null;
  return Math.abs(se / value) * 100;
}

/**
 * Resolve the display markers for a single data row.
 * `value` is the already-extracted numeric measure for the row.
 */
export function rowMarkers(row: LooseRow, value: number | null | undefined): RowMarkerResult {
  const used: Marker[] = [];

  // 1. Missing → not available.
  if (value == null || (typeof value === 'number' && isNaN(value))) {
    used.push('na');
    return { override: MARKER_SYMBOL.na, suffix: '', used };
  }

  // 2. True zero → nil.
  if (value === 0) {
    used.push('nil');
    return { override: MARKER_SYMBOL.nil, suffix: '', used };
  }

  let suffix = '';

  // 3. Explicit provisional / revised / negligible / na flags.
  const explicit = flagToMarker(row.flag ?? row.marker ?? row.quality);
  if (explicit === 'provisional' || explicit === 'revised') {
    suffix += MARKER_SYMBOL[explicit];
    used.push(explicit);
  } else if (explicit === 'negligible') {
    used.push('negligible');
    return { override: MARKER_SYMBOL.negligible, suffix: '', used };
  } else if (explicit === 'na') {
    used.push('na');
    return { override: MARKER_SYMBOL.na, suffix: '', used };
  }

  // 4. Computed reliability — RSE > 20% gets the caution star.
  const rse = computeRSE(row);
  if (rse != null && rse > 20) {
    suffix += MARKER_SYMBOL.caution;
    used.push('caution');
  }

  return { suffix, used };
}

/** Collect the distinct markers used across a set of rows (for the legend). */
export function collectLegend(markerResults: RowMarkerResult[]): Marker[] {
  const seen = new Set<Marker>();
  for (const r of markerResults) for (const m of r.used) seen.add(m);
  // Stable, conventional order.
  const order: Marker[] = ['provisional', 'revised', 'caution', 'nil', 'negligible', 'na'];
  return order.filter((m) => seen.has(m));
}
