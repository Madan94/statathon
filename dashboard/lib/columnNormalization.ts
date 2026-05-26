import type { AnalysisResult, ColumnNormalizationRow } from '@/lib/api';

export interface NormalizationPlanRow {
  originalName: string;
  normalizedName: string;
  displayName: string;
  domain?: string;
  matchMethod: string;
  matchConfidence?: number;
  matchingReason?: string;
  semanticHints?: string[];
}

const MATCH_METHOD_LABELS: Record<string, string> = {
  schema_suffix_lock: 'Schema suffix lock',
  rapidfuzz_ontology: 'RapidFuzz + ontology',
  schema_ontology_lock: 'Schema ontology lock',
  embedding_similarity: 'Embedding similarity',
  dynamic_cluster: 'Dynamic cluster',
};

export function formatMatchMethod(method?: string): string {
  if (!method) return 'Pipeline inference';
  return MATCH_METHOD_LABELS[method] ?? method.replace(/_/g, ' ');
}

function mapApiRow(row: ColumnNormalizationRow): NormalizationPlanRow {
  return {
    originalName: row.original_name,
    // Step 2 shows plain expanded name, no domain prefix
    normalizedName: row.normalized_name,
    displayName: (row.display_name as string) || row.normalized_name,
    domain: row.domain,
    matchMethod: formatMatchMethod(row.match_method),
    matchConfidence: row.match_confidence,
    matchingReason: row.matching_reason,
    semanticHints: row.semantic_hints,
  };
}

/** Build normalisation plan from backend `column_normalization` payload (dynamic, dataset-agnostic). */
export function buildNormalizationPlan(results: AnalysisResult): NormalizationPlanRow[] {
  const apiPlan = results.column_normalization;
  if (apiPlan?.length) {
    return apiPlan.map(mapApiRow);
  }

  // Legacy fallback for analyses run before dynamic normalisation was added
  const mappingByCol = new Map(
    (results.semantic_mapping ?? []).map((r) => [r.column, r] as const)
  );
  const columns =
    Object.keys(results.column_profiles ?? {}).length > 0
      ? Object.keys(results.column_profiles ?? {})
      : (results.semantic_mapping ?? []).map((r) => r.column);

  return columns.map((originalName) => {
    const row = mappingByCol.get(originalName);
    const normalizedName =
      (row?.normalized_name as string | undefined) ??
      originalName.replace(/_/g, ' ');
    const domain = row?.domain as string | undefined;
    const domainLabel =
      domain && domain !== 'unknown' && domain !== 'uncorrelated'
        ? domain.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
        : null;
    const base = normalizedName.replace(/\b\w/g, (c) => c.toUpperCase());
    const displayName = domainLabel ? `${domainLabel} · ${base}` : base;

    return {
      originalName,
      normalizedName,
      displayName,
      domain,
      matchMethod: 'Legacy analysis (re-run for dynamic names)',
      matchConfidence: row?.confidence,
      matchingReason: (row?.explainability as { matching_reason?: string } | undefined)
        ?.matching_reason,
    };
  });
}
