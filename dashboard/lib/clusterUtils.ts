import type { ClusterGroup } from '@/lib/api';

/** Normalize V1/V2 cluster payloads to a consistent UI shape. */
export function normalizeClusterGroup(cl: ClusterGroup & Record<string, unknown>): ClusterGroup {
  const domain = String(cl.domain || cl.dominant_domain || '');
  const domainPurity =
    cl.domain_purity ?? (cl as { purity?: number }).purity ?? cl.support ?? 0;
  const supportScore =
    cl.support_score ?? (cl as { cluster_confidence?: number }).cluster_confidence ?? 0;
  const embeddingCoherence = cl.embedding_coherence;

  return {
    ...cl,
    cluster_id: String(cl.cluster_id || cl.cluster_name || ''),
    domain,
    support_score: Number(supportScore) || 0,
    domain_purity: Number(domainPurity) || 0,
    embedding_coherence:
      embeddingCoherence != null ? Number(embeddingCoherence) : undefined,
    columns: cl.columns ?? [],
  };
}

export function clusterScoreBarValue(
  score: number | null | undefined,
  fallback = 0,
): number {
  if (score == null || !Number.isFinite(Number(score))) return fallback;
  return Number(score);
}

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
