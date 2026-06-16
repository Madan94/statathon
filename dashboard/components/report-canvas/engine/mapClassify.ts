/* ═══════════════════════════════════════════════════════════════════
   Map classification (T2) — data-classification methods for the
   choropleth, plus an Indian State/UT name normaliser so table labels
   match the GeoJSON feature names.
   ═══════════════════════════════════════════════════════════════════ */

export type ClassMethod = 'quantile' | 'equal' | 'jenks';

export interface ClassBreaks {
  /** Upper bound of each class (ascending). */
  bounds: number[];
  min: number;
  max: number;
}

/** Equal-interval breaks. */
function equalInterval(values: number[], classes: number): number[] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const step = (max - min) / classes;
  return Array.from({ length: classes }, (_, i) => min + step * (i + 1));
}

/** Quantile breaks (equal count per class). */
function quantile(values: number[], classes: number): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  const bounds: number[] = [];
  for (let i = 1; i <= classes; i++) {
    const idx = Math.min(sorted.length - 1, Math.floor((i / classes) * sorted.length) - 0);
    bounds.push(sorted[Math.max(0, idx - 1)]);
  }
  bounds[classes - 1] = sorted[sorted.length - 1];
  return bounds;
}

/** Jenks natural breaks (simplified 1-D k-means style). */
function jenks(values: number[], classes: number): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length <= classes) return sorted;
  // Initialise centroids at quantiles, iterate a few times.
  let centroids = Array.from({ length: classes }, (_, i) => sorted[Math.floor((i / classes) * sorted.length)]);
  for (let iter = 0; iter < 8; iter++) {
    const groups: number[][] = Array.from({ length: classes }, () => []);
    for (const v of sorted) {
      let best = 0, bestD = Infinity;
      centroids.forEach((c, i) => { const d = Math.abs(v - c); if (d < bestD) { bestD = d; best = i; } });
      groups[best].push(v);
    }
    centroids = groups.map((g, i) => g.length ? g.reduce((s, x) => s + x, 0) / g.length : centroids[i]);
  }
  // Upper bound of each group = max of its members.
  const groups: number[][] = Array.from({ length: classes }, () => []);
  for (const v of sorted) {
    let best = 0, bestD = Infinity;
    centroids.forEach((c, i) => { const d = Math.abs(v - c); if (d < bestD) { bestD = d; best = i; } });
    groups[best].push(v);
  }
  return groups.filter(g => g.length).map(g => Math.max(...g));
}

export function classify(values: number[], method: ClassMethod, classes = 5): ClassBreaks {
  const vals = values.filter(v => Number.isFinite(v));
  if (!vals.length) return { bounds: [], min: 0, max: 0 };
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  let bounds: number[];
  if (method === 'equal') bounds = equalInterval(vals, classes);
  else if (method === 'jenks') bounds = jenks(vals, classes);
  else bounds = quantile(vals, classes);
  return { bounds, min, max };
}

/** Sequential MoSPI green ramp (light → dark) for the choropleth. */
export const MAP_RAMP = ['#e8f3e8', '#bfe0bf', '#8fc98f', '#5aab5a', '#2f8a2f', '#1F7A1F'];

/* ── Indian State/UT name normaliser ──────────────────────────────── */
const STATE_ALIASES: Record<string, string> = {
  'odisha': 'Odisha', 'orissa': 'Odisha',
  'uttarakhand': 'Uttarakhand', 'uttaranchal': 'Uttarakhand',
  'delhi': 'NCT of Delhi', 'nct of delhi': 'NCT of Delhi', 'new delhi': 'NCT of Delhi',
  'pondicherry': 'Puducherry', 'puducherry': 'Puducherry',
  'jammu & kashmir': 'Jammu and Kashmir', 'jammu and kashmir': 'Jammu and Kashmir', 'j&k': 'Jammu and Kashmir',
  'andaman & nicobar': 'Andaman and Nicobar', 'andaman and nicobar islands': 'Andaman and Nicobar',
  'dadra & nagar haveli': 'Dadra and Nagar Haveli and Daman and Diu',
  'tamilnadu': 'Tamil Nadu', 'tamil nadu': 'Tamil Nadu',
};

export function normaliseState(name: string): string {
  const key = name.trim().toLowerCase();
  if (STATE_ALIASES[key]) return STATE_ALIASES[key];
  // Title-case fallback.
  return name.trim().replace(/\b\w/g, c => c.toUpperCase());
}
