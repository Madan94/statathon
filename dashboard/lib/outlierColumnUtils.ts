import type { AnalysisResult, AnomalyColumnBlock } from '@/lib/api';

const NUMERIC_DTYPE_HINTS = ['numeric', 'float', 'int', 'integer', 'number', 'decimal', 'double', 'long'];

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
  const direct = blocks.find((b) => b.column === column);
  if (direct) return direct;

  const original = resolveOriginalColumnName(column, results);
  if (original !== column) {
    const byOriginal = blocks.find((b) => b.column === original);
    if (byOriginal) return byOriginal;
  }

  return blocks.find(
    (b) => (b as AnomalyColumnBlock & { original_column?: string }).original_column === column
      || (b as AnomalyColumnBlock & { original_column?: string }).original_column === original,
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
