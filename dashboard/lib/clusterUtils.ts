/** Normalize cluster domain_distribution to percentages summing to 100. */
export function normalizeDomainDistribution(
  dist: Record<string, number> | undefined,
  fallbackDomain?: string,
  columnCount?: number
): Record<string, number> {
  let raw: Record<string, number> | null =
    dist && Object.keys(dist).length > 0 ? dist : null;

  if (!raw && fallbackDomain) {
    raw = { [fallbackDomain]: columnCount ?? 1 };
  }
  if (!raw) return {};

  const entries = Object.entries(raw).map(([k, v]) => [k, Number(v)] as const);
  const total = entries.reduce((sum, [, v]) => sum + (Number.isFinite(v) ? v : 0), 0);
  if (total <= 0) return {};

  const out: Record<string, number> = {};
  for (const [k, v] of entries) {
    out[k] = (v / total) * 100;
  }
  return out;
}

export function formatDistributionPct(pct: number): string {
  if (!Number.isFinite(pct)) return '—';
  if (pct > 0 && pct < 1) return '<1%';
  return `${Math.round(pct)}%`;
}
