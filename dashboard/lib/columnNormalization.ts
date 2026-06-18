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
  isAuxiliary: boolean;
  constantValue?: unknown;
  /** Underlying storage type when `isAuxiliary` (e.g. numeric, string). */
  storageType?: string;
}

function extractConstantValue(profile: ColumnProfile | undefined): unknown {
  if (!profile) return undefined;
  if (profile.constant_value !== undefined) return profile.constant_value;
  const top = profile.top_values?.[0];
  if (!top) return undefined;
  if (Array.isArray(top)) return top[0];
  if (typeof top === 'object' && top && 'value' in top) return top.value;
  return undefined;
}

/** Column holds one distinct value across all rows (no missing). */
export function isAuxiliaryProfile(
  profile: ColumnProfile | undefined,
  missingRatio: number,
  totalRows: number,
): boolean {
  if (!profile || totalRows <= 0) return false;
  if (profile.is_auxiliary === true) return true;
  const missing = missingRatio > 0 ? missingRatio : Number(profile.missing_ratio ?? 0);
  return missing <= 0 && profile.cardinality === 1;
}

const MATCH_METHOD_LABELS: Record<string, string> = {
  schema_suffix_lock: 'Schema suffix lock',
  rapidfuzz_ontology: 'RapidFuzz + ontology',
  schema_ontology_lock: 'Schema ontology lock',
  embedding_similarity: 'Embedding similarity',
  dynamic_cluster: 'Dynamic cluster',
  column_dictionary: 'Column dictionary',
};

export function formatMatchMethod(method?: string): string {
  if (!method) return 'Pipeline inference';
  return MATCH_METHOD_LABELS[method] ?? method.replace(/_/g, ' ');
}

function snakeKey(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^\w]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '');
}

function lookupBySnake<T>(map: Record<string, T> | undefined, col: string): T | undefined {
  if (!map) return undefined;
  if (map[col] != null) return map[col];
  const target = snakeKey(col);
  for (const [key, value] of Object.entries(map)) {
    if (snakeKey(key) === target) return value;
  }
  return undefined;
}

/** Map DB/API column name (often canonical) back to plan `original_name`. */
export function resolvePlanOriginalName(
  dbColumnName: string,
  plan: NormalizationPlanRow[],
  columnNormalization: ColumnNormalizationRow[] = [],
): string | null {
  const norm = columnNormalization.find(
    (r) =>
      r.original_name === dbColumnName
      || r.normalized_name === dbColumnName
      || (r.canonical_name as string | undefined) === dbColumnName,
  );
  if (norm?.original_name) return norm.original_name;

  const row = plan.find(
    (p) =>
      p.originalName === dbColumnName
      || p.profileKey === dbColumnName
      || p.normalizedName === dbColumnName,
  );
  return row?.originalName ?? null;
}

function profileLookupKeys(originalName: string, profileKey: string, results: AnalysisResult): string[] {
  const seen = new Set<string>();
  const add = (k?: string | null) => {
    if (k) seen.add(k);
  };

  const normRow = (results.column_normalization ?? []).find(
    (r) =>
      r.original_name === originalName
      || snakeKey(String(r.original_name ?? '')) === snakeKey(originalName),
  );

  add(normRow?.canonical_name as string | undefined);
  add(normRow?.normalized_name);
  add(profileKey);
  add(originalName);

  return [...seen];
}

/** Same resolution order as Step 1 `missingCount(col)`. */
function resolveMissingCount(
  keys: string[],
  columnProfiles: Record<string, ColumnProfile> | undefined,
  missingPerCol: Record<string, number> | undefined,
  totalRows: number,
): { missingCount: number; profile?: ColumnProfile } {
  for (const key of keys) {
    const fromHealth = lookupBySnake(missingPerCol, key);
    if (fromHealth != null && fromHealth > 0) {
      return { missingCount: Number(fromHealth), profile: lookupBySnake(columnProfiles, key) };
    }
  }

  for (const key of keys) {
    const profile = lookupBySnake(columnProfiles, key);
    if (profile?.missing_ratio != null && totalRows > 0) {
      return {
        missingCount: Math.round(Number(profile.missing_ratio) * totalRows),
        profile,
      };
    }
    if (profile?.missing_count != null) {
      return { missingCount: Number(profile.missing_count), profile };
    }
  }

  for (const key of keys) {
    const fromHealth = lookupBySnake(missingPerCol, key);
    if (fromHealth != null) {
      return {
        missingCount: Number(fromHealth),
        profile: lookupBySnake(columnProfiles, key),
      };
    }
  }

  return { missingCount: 0, profile: undefined };
}

/** Resolve type and missing stats when profiles/schema use canonical column names. */
export function resolveColumnProfileStats(
  originalName: string,
  profileKey: string,
  results: AnalysisResult,
): ColumnProfileStats {
  const profilingSummary = results.profiling_summary as
    | {
        health?: {
          rows?: number;
          missing_per_column?: Record<string, number>;
          dtypes?: Record<string, string>;
        };
        schema?: Record<string, string>;
        column_profiles?: Record<string, ColumnProfile>;
      }
    | undefined;

  const health = (results.health ?? profilingSummary?.health) as {
    rows?: number;
    missing_per_column?: Record<string, number>;
    dtypes?: Record<string, string>;
  } | undefined;
  const schema = {
    ...(profilingSummary?.schema ?? {}),
    ...(results.schema ?? {}),
  };
  const columnProfiles = (results.column_profiles ??
    profilingSummary?.column_profiles) as Record<string, ColumnProfile> | undefined;
  const totalRows = health?.rows ?? 0;
  const keys = profileLookupKeys(originalName, profileKey, results);
  const missingPerCol = health?.missing_per_column ?? {};
  const dtypes = health?.dtypes ?? {};

  let typeFromSchema: string | undefined;
  let typeFromDtypes: string | undefined;
  let profile: ColumnProfile | undefined;

  for (const key of keys) {
    if (!typeFromSchema) typeFromSchema = lookupBySnake(schema, key);
    if (!typeFromDtypes) typeFromDtypes = lookupBySnake(dtypes, key);
    if (!profile) profile = lookupBySnake(columnProfiles, key);
  }

  if (!profile) {
    for (const row of results.column_normalization ?? []) {
      if (!row || typeof row !== 'object') continue;
      const orig = String(row.original_name ?? '');
      const canon = String(row.canonical_name ?? row.normalized_name ?? '');
      profile =
        lookupBySnake(columnProfiles, orig)
        ?? lookupBySnake(columnProfiles, canon)
        ?? undefined;
      if (profile) break;
      if (snakeKey(orig) === snakeKey(originalName)) {
        profile = lookupBySnake(columnProfiles, orig);
        if (profile) break;
      }
      if (snakeKey(canon) === snakeKey(profileKey)) {
        profile = lookupBySnake(columnProfiles, canon);
        if (profile) break;
      }
    }
  }

  const mapRow = results.semantic_mapping?.find(
    (r) =>
      keys.some((k) => snakeKey(k) === snakeKey(String(r.column ?? '')))
      || snakeKey(String((r as { original_name?: string }).original_name ?? '')) === snakeKey(originalName),
  );
  const typeFromMapping = (mapRow as { dtype?: string } | undefined)?.dtype;

  const { missingCount, profile: resolvedProfile } = resolveMissingCount(
    keys,
    columnProfiles,
    missingPerCol,
    totalRows,
  );
  profile = profile ?? resolvedProfile;

  const missingRatio =
    totalRows > 0
      ? missingCount / totalRows
      : profile?.missing_ratio != null
        ? Number(profile.missing_ratio)
        : 0;

  const storageType =
    typeFromSchema
    ?? profile?.datatype
    ?? typeFromDtypes
    ?? typeFromMapping
    ?? '—';

  const isAuxiliary = isAuxiliaryProfile(profile, missingRatio, totalRows);
  const constantValue = isAuxiliary ? extractConstantValue(profile) : undefined;

  return {
    type: isAuxiliary ? 'auxiliary' : storageType,
    missingCount,
    missingRatio,
    isAuxiliary,
    constantValue,
    storageType: isAuxiliary ? storageType : undefined,
  };
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
