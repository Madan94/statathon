import type { AnalysisResult, AnomalyColumnBlock, ImputationCandidate } from '@/lib/api';

const NUMERIC_DTYPE_HINTS = ['numeric', 'float', 'int', 'integer', 'number', 'decimal', 'double', 'long'];

function snakeKey(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^\w]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '');
}

function columnNamesMatch(a: string | undefined | null, b: string | undefined | null): boolean {
  if (!a || !b) return false;
  if (a === b) return true;
  if (a.toLowerCase() === b.toLowerCase()) return true;
  return snakeKey(a) === snakeKey(b);
}

function columnAliases(column: string, results: AnalysisResult): string[] {
  const aliases = new Set<string>([column]);
  for (const row of results.column_normalization ?? []) {
    const names = [
      row.original_name,
      row.normalized_name,
      row.canonical_name as string | undefined,
    ].filter(Boolean) as string[];
    if (names.some((name) => columnNamesMatch(name, column))) {
      names.forEach((name) => aliases.add(name));
    }
  }
  const original = resolveOriginalColumnName(column, results);
  if (original) aliases.add(original);
  return [...aliases];
}

export function isNumericDtype(dtype: string | undefined | null): boolean {
  if (!dtype) return false;
  const key = dtype.toLowerCase();
  if (NUMERIC_DTYPE_HINTS.some((h) => key === h || key.includes(h))) return true;
  if (['string', 'categorical', 'object', 'bool', 'boolean', 'text', 'date', 'datetime'].some((h) => key.includes(h))) {
    return false;
  }
  return false;
}

export function isPandasNumericDtype(dtype: string | undefined | null): boolean {
  if (!dtype) return false;
  const key = dtype.toLowerCase();
  return key.includes('int') || key.includes('float') || key.includes('decimal');
}

/** Resolve UI column name → original dataset column name (pre-normalization). */
export function resolveOriginalColumnName(column: string, results: AnalysisResult): string {
  const rows = results.column_normalization ?? [];
  for (const row of rows) {
    if (row.normalized_name === column || row.original_name === column) {
      return row.original_name;
    }
  }
  return column;
}

export function resolveAnomalyBlock(column: string, results: AnalysisResult): AnomalyColumnBlock | undefined {
  const phase3 = results.phase3 as {
    anomaly_results?: AnomalyColumnBlock[];
  } | undefined;
  const blocks = phase3?.anomaly_results ?? [];
  const aliases = columnAliases(column, results);

  const direct = blocks.find((b) => aliases.some((alias) => columnNamesMatch(b.column, alias)));
  if (direct) return direct;

  return blocks.find((b) => {
    const original = (b as AnomalyColumnBlock & { original_column?: string }).original_column;
    return aliases.some((alias) => columnNamesMatch(original, alias));
  });
}

function matchColumnName(target: string, candidate: string, results: AnalysisResult): boolean {
  if (columnNamesMatch(target, candidate)) return true;
  const original = resolveOriginalColumnName(target, results);
  return columnNamesMatch(original, candidate);
}

export function resolveImputationCandidate(
  column: string,
  results: AnalysisResult,
): ImputationCandidate | undefined {
  const phase3 = results.phase3 as { imputation_candidates?: ImputationCandidate[] } | undefined;
  const candidates = phase3?.imputation_candidates ?? [];
  return candidates.find((c) => matchColumnName(column, c.column, results));
}

export function resolveImputationBlock(
  column: string,
  results: AnalysisResult,
): Record<string, unknown> | undefined {
  const phase3 = results.phase3 as { imputation_results?: Array<Record<string, unknown>> } | undefined;
  const blocks = phase3?.imputation_results ?? [];
  return blocks.find((b) => matchColumnName(column, String(b.column ?? ''), results));
}

export function resolveMissingCount(column: string, results: AnalysisResult): number {
  const candidate = resolveImputationCandidate(column, results);
  if (candidate?.missing_count != null) return Number(candidate.missing_count);
  const health = results.health as { missing_per_column?: Record<string, number> } | undefined;
  const original = resolveOriginalColumnName(column, results);
  return Number(
    health?.missing_per_column?.[column]
    ?? health?.missing_per_column?.[original]
    ?? 0,
  );
}

export function isNumericColumn(column: string, results: AnalysisResult): boolean {
  const block = resolveAnomalyBlock(column, results);
  if (block) return true;

  const schema = results.schema ?? {};
  const profiles = results.column_profiles ?? {};
  const profile = profiles[column] as { datatype?: string; mean_std?: { mean: number } } | undefined;
  const health = results.health as { dtypes?: Record<string, string> } | undefined;

  const original = resolveOriginalColumnName(column, results);
  const dtype =
    schema[column]
    ?? schema[original]
    ?? profile?.datatype
    ?? health?.dtypes?.[column]
    ?? health?.dtypes?.[original];

  if (isNumericDtype(dtype) || isPandasNumericDtype(dtype)) return true;
  if (profile?.mean_std?.mean != null) return true;
  return false;
}

/** Merge outlier detection API response into results without refetching full analysis payload. */
export function mergeOutlierDetection(
  results: AnalysisResult,
  column: string,
  detectRes: {
    method?: string;
    candidates?: Array<Record<string, unknown>>;
    anomaly_block?: Record<string, unknown>;
  },
): AnalysisResult {
  const phase3 = { ...(results.phase3 ?? {}) } as Record<string, unknown>;
  const blocks = [...((phase3.anomaly_results as AnomalyColumnBlock[] | undefined) ?? [])];
  const existing = resolveAnomalyBlock(column, results);
  const mergedBlock = {
    ...(existing ?? { column }),
    ...(detectRes.anomaly_block ?? {}),
    method_selected: detectRes.method ?? detectRes.anomaly_block?.method_selected,
    detection_run: true,
  } as AnomalyColumnBlock;

  const blockIdx = blocks.findIndex(
    (b) => b.column === column
      || b.column === mergedBlock.column
      || (b as AnomalyColumnBlock & { original_column?: string }).original_column === column,
  );
  if (blockIdx >= 0) {
    blocks[blockIdx] = { ...blocks[blockIdx], ...mergedBlock };
  } else {
    blocks.push(mergedBlock);
  }

  const uiCol = String(mergedBlock.column ?? column);
  const prevCandidates = ((phase3.anomaly_candidates as Array<Record<string, unknown>> | undefined) ?? [])
    .filter((c) => String(c.column ?? '') !== uiCol && String(c.column ?? '') !== column);
  const nextCandidates = [
    ...prevCandidates,
    ...((detectRes.candidates as Array<Record<string, unknown>> | undefined) ?? []),
  ];

  return {
    ...results,
    phase3: {
      ...phase3,
      anomaly_results: blocks,
      anomaly_candidates: nextCandidates,
    },
  };
}
