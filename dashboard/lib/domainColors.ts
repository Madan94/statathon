/** Semantic domain → node color mapping for schema / KG graphs. */

const DOMAIN_COLORS: Record<string, string> = {
  identifier: '#6366f1',
  survey_metadata: '#6366f1',
  metadata: '#6366f1',
  geography: '#14b8a6',
  geographic: '#14b8a6',
  geographic_distribution: '#14b8a6',
  demographic: '#f59e0b',
  household: '#10b981',
  census: '#3b82f6',
  population: '#3b82f6',
  labor: '#f97316',
  labour: '#f97316',
  labour_market: '#f97316',
  employment: '#fb923c',
  health: '#ef4444',
  education: '#84cc16',
  agriculture: '#22c55e',
  agricultural: '#22c55e',
  economic: '#06b6d4',
  economic_indicator: '#06b6d4',
  economic_industry: '#06b6d4',
  industry: '#0891b2',
  inflation: '#e11d48',
  price: '#f43f5e',
  base_year: '#8b5cf6',
  base_year_reference: '#8b5cf6',
  temporal: '#a855f7',
  time: '#a855f7',
  data_collection: '#c084fc',
  data_collection_period: '#c084fc',
  period: '#d946ef',
  uncorrelated: '#94a3b8',
  uncorrelated_metadata: '#94a3b8',
  unknown: '#64748b',
};

/** Token aliases → palette key (longest match wins). */
const DOMAIN_ALIASES: Record<string, string> = {
  labour_market: 'labour_market',
  labour: 'labour_market',
  labor: 'labour_market',
  employment: 'labour_market',
  inflation: 'inflation',
  price_index: 'inflation',
  economic_indicator: 'economic_indicator',
  indicator: 'economic_indicator',
  base_year_reference: 'base_year_reference',
  base_year: 'base_year_reference',
  geographic_distribution: 'geographic_distribution',
  geography: 'geographic_distribution',
  geographic: 'geographic_distribution',
  data_collection_period: 'data_collection_period',
  collection_period: 'data_collection_period',
  survey_metadata: 'survey_metadata',
  metadata: 'survey_metadata',
};

function normalizeDomainKey(domain: string): string {
  return domain.trim().toLowerCase().replace(/[\s-]+/g, '_');
}

function hashDomainColor(domain: string): string {
  let h = 0;
  for (let i = 0; i < domain.length; i++) {
    h = (h * 31 + domain.charCodeAt(i)) & 0xffffffff;
  }
  const hue = Math.abs(h) % 360;
  return `hsl(${hue}, 68%, 58%)`;
}

function resolvePaletteKey(domain: string): string | null {
  const normalized = normalizeDomainKey(domain);
  if (DOMAIN_COLORS[normalized]) return normalized;
  if (DOMAIN_ALIASES[normalized]) return DOMAIN_ALIASES[normalized];

  for (const [alias, key] of Object.entries(DOMAIN_ALIASES)) {
    if (normalized === alias || normalized.includes(alias) || alias.includes(normalized)) {
      return key;
    }
  }

  for (const key of Object.keys(DOMAIN_COLORS)) {
    if (key === 'unknown') continue;
    if (normalized === key || normalized.startsWith(`${key}_`) || normalized.endsWith(`_${key}`)) {
      return key;
    }
    const tokens = normalized.split('_');
    if (tokens.some((t) => t === key || key.includes(t))) return key;
  }

  return null;
}

export function resolveDomainColor(domain?: string | null): string {
  if (!domain?.trim()) return DOMAIN_COLORS.unknown;
  const paletteKey = resolvePaletteKey(domain);
  if (paletteKey && DOMAIN_COLORS[paletteKey]) return DOMAIN_COLORS[paletteKey];
  return hashDomainColor(normalizeDomainKey(domain));
}

export const domainColor = resolveDomainColor;

export function domainLegendLabel(domain?: string | null): string {
  return domain?.trim() || 'unknown';
}

export { DOMAIN_COLORS };
