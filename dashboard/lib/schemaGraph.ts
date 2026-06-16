import type { GraphEdge } from '@/lib/api';

const SIMILARITY_RE = /similarity\s*(?:[=(:]\s*)?([0-9.]+)/i;
const CROSS_DOMAIN_RE = /Cross-domain linkage\s+([^\s<]+)\s+<->\s+([^\s;.]+)/i;

export function parseEmbeddingSimilarity(semanticReason?: string | null): number | null {
  if (!semanticReason) return null;
  const match = semanticReason.match(SIMILARITY_RE);
  if (!match) return null;
  const value = Number.parseFloat(match[1]);
  return Number.isFinite(value) ? value : null;
}

export function parseDomainsFromReason(semanticReason?: string | null): {
  sourceDomain?: string;
  targetDomain?: string;
} {
  if (!semanticReason) return {};
  const match = semanticReason.match(CROSS_DOMAIN_RE);
  if (!match) return {};
  return { sourceDomain: match[1].trim(), targetDomain: match[2].trim() };
}

export function inferOwlType(
  relationshipType?: string | null,
  opts?: {
    sourceDomain?: string | null;
    targetDomain?: string | null;
    semanticReason?: string | null;
  },
): string {
  const rel = (relationshipType ?? '').trim().toLowerCase();
  let sd = (opts?.sourceDomain ?? '').trim();
  let td = (opts?.targetDomain ?? '').trim();
  if (!sd || !td) {
    const parsed = parseDomainsFromReason(opts?.semanticReason);
    sd = sd || (parsed.sourceDomain ?? '').trim();
    td = td || (parsed.targetDomain ?? '').trim();
  }

  if (rel === 'cross_domain_linkage') return 'owl:ObjectProperty';
  if (rel === 'co_cluster_semantic') {
    if (sd && td && sd === td) return 'owl:equivalentProperty';
    return 'owl:ObjectProperty';
  }
  if (rel === 'intra_domain_association') {
    const sim = parseEmbeddingSimilarity(opts?.semanticReason);
    if (sim != null && sim >= 0.55) return 'rdfs:subPropertyOf';
    return 'rdfs:seeAlso';
  }
  if (!rel || rel === 'semantic' || rel === 'related') return 'owl:ObjectProperty';
  return 'owl:ObjectProperty';
}

export function resolveOwlType(edge: GraphEdge, domainMap?: Map<string, string>): string {
  if (edge.owl_type) return edge.owl_type;
  const parsed = parseDomainsFromReason(edge.semantic_reason);
  return inferOwlType(edge.relationship_type, {
    sourceDomain: edge.source_domain ?? domainMap?.get(edge.source) ?? parsed.sourceDomain,
    targetDomain: edge.target_domain ?? domainMap?.get(edge.target) ?? parsed.targetDomain,
    semanticReason: edge.semantic_reason,
  });
}

export function normalizeSchemaGraphEdges(
  edges: GraphEdge[],
  domainMap?: Map<string, string>,
): GraphEdge[] {
  return edges.map((edge) => {
    const parsed = parseDomainsFromReason(edge.semantic_reason);
    const enriched: GraphEdge = {
      ...edge,
      source_domain: edge.source_domain ?? domainMap?.get(edge.source) ?? parsed.sourceDomain,
      target_domain: edge.target_domain ?? domainMap?.get(edge.target) ?? parsed.targetDomain,
    };
    return {
      ...enriched,
      owl_type: resolveOwlType(enriched, domainMap),
    };
  });
}
