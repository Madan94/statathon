import type { AnalysisResult, ColumnNormalizationRow, ColumnProfile } from '@/lib/api';

export interface NormalizationPlanRow {
  originalName: string;
  normalizedName: string;
  /** Key used in schema / column_profiles / health after pipeline rename */
  profileKey: string;
  displayName: string;
  domain?: string;
  matchMethod: string;
  matchConfidence?: number;
  matchingReason?: string;
  semanticHints?: string[];
}

export interface ColumnProfileStats {
  type: string;
  missingCount: number;
  missingRatio: number;
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

function profileLookupKeys(originalName: string, normalizedName: string, results: AnalysisResult): string[] {
  const keys = new Set<string>();
  const add = (k?: string | null) => {
    if (k) keys.add(k);
  };
  add(normalizedName);
  add(originalName);
  for (const row of results.column_normalization ?? []) {
    if (row.original_name !== originalName && row.normalized_name !== normalizedName) continue;
    add(row.original_name);
    add(row.normalized_name);
    add(row.canonical_name as string | undefined);
    add(row.display_name as string | undefined);
  }
  for (const row of results.semantic_mapping ?? []) {
    const orig = (row as { original_name?: string }).original_name;
    if (row.column === originalName || row.column === normalizedName || orig === originalName) {
      add(row.column);
      add(orig);
    }
  }
  for (const pk of Object.keys(results.column_profiles ?? {})) {
    const normRow = (results.column_normalization ?? []).find(
      (r) =>
        r.canonical_name === pk
        || r.original_name === originalName
        || r.normalized_name === normalizedName,
    );
    if (normRow?.original_name === originalName || pk === normalizedName || pk === originalName) {
      add(pk);
    }
  }
  return [...keys];
}

/** Step 1 parity: prefer health when > 0, else derive from profile missing_ratio. */
function resolveMissingCount(
  keys: string[],
  columnProfiles: Record<string, ColumnProfile> | undefined,
  missingPerCol: Record<string, number> | undefined,
  totalRows: number,
): { missingCount: number; profile?: ColumnProfile } {
  let profile: ColumnProfile | undefined;
  for (const key of keys) {
    if (!profile && columnProfiles?.[key]) profile = columnProfiles[key];
  }

  let fromHealth: number | undefined;
  for (const key of keys) {
    if (missingPerCol?.[key] != null) {
      const val = Number(missingPerCol[key]);
      if (val > 0) {
        fromHealth = val;
        break;
      }
      if (fromHealth == null) fromHealth = val;
    }
  }

  if (fromHealth != null && fromHealth > 0) {
    return { missingCount: fromHealth, profile };
  }
  if (profile?.missing_ratio != null && totalRows > 0) {
    return {
      missingCount: Math.round(Number(profile.missing_ratio) * totalRows),
      profile,
    };
  }
  if (profile?.missing_count != null) {
    return { missingCount: Number(profile.missing_count), profile };
  }
  return { missingCount: fromHealth ?? 0, profile };
}

/** Resolve type and missing stats when profiles/schema use canonical column names. */
export function resolveColumnProfileStats(
  originalName: string,
  profileKey: string,
  results: AnalysisResult,
): ColumnProfileStats {
  const health = results.health as {
    rows?: number;
    missing_per_column?: Record<string, number>;
    dtypes?: Record<string, string>;
  } | undefined;
  const schema = results.schema ?? {};
  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const totalRows = health?.rows ?? 0;
  const keys = profileLookupKeys(originalName, profileKey, results);
  const missingPerCol = health?.missing_per_column ?? {};

  let typeFromSchema: string | undefined;
  let typeFromDtypes: string | undefined;

  for (const key of keys) {
    if (!typeFromSchema && schema[key]) typeFromSchema = schema[key];
    if (!typeFromDtypes && health?.dtypes?.[key]) typeFromDtypes = health.dtypes[key];
  }

  const mapRow = results.semantic_mapping?.find(
    (r) =>
      keys.includes(r.column)
      || (r as { original_name?: string }).original_name === originalName,
  );
  const typeFromMapping = (mapRow as { dtype?: string } | undefined)?.dtype;

  const { missingCount, profile } = resolveMissingCount(
    keys,
    columnProfiles,
    missingPerCol,
    totalRows,
  );

  const missingRatio =
    totalRows > 0
      ? missingCount / totalRows
      : profile?.missing_ratio != null
        ? Number(profile.missing_ratio)
        : 0;

  const type =
    typeFromSchema
    ?? profile?.datatype
    ?? typeFromDtypes
    ?? typeFromMapping
    ?? '—';

  return { type, missingCount, missingRatio };
}

function mapApiRow(row: ColumnNormalizationRow): NormalizationPlanRow {
  const profileKey =
    (row.canonical_name as string | undefined)
    || row.normalized_name
    || row.original_name;
  return {
    originalName: row.original_name,
    // Step 2 shows plain expanded name, no domain prefix
    normalizedName: row.normalized_name,
    profileKey,
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
      profileKey: originalName,
      displayName,
      domain,
      matchMethod: 'Legacy analysis (re-run for dynamic names)',
      matchConfidence: row?.confidence,
      matchingReason: (row?.explainability as { matching_reason?: string } | undefined)
        ?.matching_reason,
    };
  });
}
