import type { DataRow, ReportSectionRequest, SectionExecutionResult, SectionIssue, SectionMeasure, SectionResultRow } from './types';
import { stableHash } from './datasetStore';
import { applyPredicates } from './predicateEngine';

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Number(value))) return Number(value);
  return null;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function aggregate(values: number[], measure: SectionMeasure | null, warnings: SectionIssue[], groupLabel: string): number | null {
  if (!measure) return null;
  const agg = measure.agg || 'reported_value';
  if (agg === 'count') return values.length;
  if (!values.length) return null;
  if (agg === 'sum') return values.reduce((a, b) => a + b, 0);
  if (agg === 'mean' || agg === 'weighted_mean' || agg === 'weighted_ratio') return values.reduce((a, b) => a + b, 0) / values.length;
  if (agg === 'median') return median(values);
  if (agg === 'min') return Math.min(...values);
  if (agg === 'max') return Math.max(...values);
  const unique = Array.from(new Set(values.map(v => Number(v.toFixed(6)))));
  if (unique.length <= 1) return unique[0] ?? null;
  warnings.push({ severity: 'warn', code: 'AMBIGUOUS_REPORTED_VALUE', message: `Reported value for ${groupLabel} has ${unique.length} distinct values; using mean for preview and adding a caveat.`, column: measure.col });
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function keyOf(row: DataRow, groupBy: string[]): Record<string, unknown> {
  const key: Record<string, unknown> = {};
  groupBy.forEach(col => { key[col] = row[col]; });
  return key;
}

function keyText(key: Record<string, unknown>): string {
  const entries = Object.entries(key);
  return entries.length ? entries.map(([k, v]) => `${k}=${String(v)}`).join(',') : 'all';
}

export function executeSectionRequest(request: ReportSectionRequest, rows: DataRow[], cacheHit = false): SectionExecutionResult {
  const warnings: SectionIssue[] = [];
  const filtered = applyPredicates(rows, request.scope.filters || []);
  warnings.push(...filtered.warnings);
  const groupBy = request.analysis.groupBy?.length ? request.analysis.groupBy : request.scope.columns.dimensions;
  const measure = request.scope.columns.measures[0] || null;
  const buckets = new Map<string, { key: Record<string, unknown>; indexes: number[]; values: number[] }>();

  for (const index of filtered.indexes) {
    const source = rows[index];
    const key = keyOf(source, groupBy);
    const token = keyText(key);
    const bucket = buckets.get(token) || { key, indexes: [], values: [] };
    bucket.indexes.push(index);
    if (measure) {
      const n = toNumber(source[measure.col]);
      if (n !== null) bucket.values.push(n);
    }
    buckets.set(token, bucket);
  }

  const resultRows: SectionResultRow[] = Array.from(buckets.values()).map(bucket => ({
    key: bucket.key,
    value: aggregate(bucket.values, measure, warnings, keyText(bucket.key)),
    n: bucket.indexes.length,
    rowIds: [`r:${keyText(bucket.key)}`],
  }));

  const sort = request.analysis.sort;
  if (sort) {
    resultRows.sort((a, b) => {
      const av = a.value ?? 0;
      const bv = b.value ?? 0;
      return sort.order === 'asc' ? av - bv : bv - av;
    });
  }

  const limit = request.analysis.limit;
  const finalRows = limit && limit > 0 ? resultRows.slice(0, limit) : resultRows;
  return {
    requestId: request.requestId,
    datasetId: request.datasetId,
    rows: finalRows,
    measure,
    groupBy,
    filtersApplied: filtered.filtersApplied,
    rowsScanned: rows.length,
    rowsAfterFilter: filtered.indexes.length,
    cacheHit,
    sliceSignature: stableHash({ datasetId: request.datasetId, filters: request.scope.filters, include: request.scope.columns.include }),
    warnings,
  };
}
