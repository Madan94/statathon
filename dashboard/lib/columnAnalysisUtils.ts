import type { AnalysisResult, ColumnProfile, SemanticMappingRow } from '@/lib/api';
import { isAuxiliaryProfile } from '@/lib/columnNormalization';

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

function lookupBySnake<T>(map: Record<string, T> | undefined, col: string): T | undefined {
  if (!map) return undefined;
  if (map[col] != null) return map[col];
  const target = snakeKey(col);
  for (const [key, value] of Object.entries(map)) {
    if (snakeKey(key) === target) return value;
  }
  return undefined;
}

function allColumnNames(results: AnalysisResult): string[] {
  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const profilingSummary = results.profiling_summary as { column_profiles?: Record<string, ColumnProfile> } | undefined;
  const schema = results.schema ?? {};
  return Object.keys(columnProfiles ?? profilingSummary?.column_profiles ?? schema);
}

/** Find semantic_mapping row with alias-aware column match. */
export function resolveSemanticRow(
  column: string,
  results: AnalysisResult,
): SemanticMappingRow | undefined {
  for (const row of results.semantic_mapping ?? []) {
    if (columnNamesMatch(row.column, column)) return row;
  }
  return undefined;
}

/** Pipeline role from Step 3; defaults to variable when unset. */
export function resolveAnalysisRole(
  column: string,
  results: AnalysisResult,
): 'identifier' | 'variable' {
  const role = resolveSemanticRow(column, results)?.analysis_role;
  return role === 'identifier' || role === 'variable' ? role : 'variable';
}

/** Constant-value column (no missing) — excluded from column analysis. */
export function isAuxiliaryColumn(column: string, results: AnalysisResult): boolean {
  const profilingSummary = results.profiling_summary as
    | {
        health?: { rows?: number; missing_per_column?: Record<string, number> };
        column_profiles?: Record<string, ColumnProfile>;
      }
    | undefined;

  const health = (results.health ?? profilingSummary?.health) as
    | { rows?: number; missing_per_column?: Record<string, number> }
    | undefined;
  const columnProfiles = (results.column_profiles ??
    profilingSummary?.column_profiles) as Record<string, ColumnProfile> | undefined;
  const totalRows = health?.rows ?? 0;
  const profile = lookupBySnake(columnProfiles, column);
  const missingFromHealth = lookupBySnake(health?.missing_per_column, column);
  const missingRatio =
    missingFromHealth != null && totalRows > 0
      ? Number(missingFromHealth) / totalRows
      : Number(profile?.missing_ratio ?? 0);
  return isAuxiliaryProfile(profile, missingRatio, totalRows);
}

/** Variable columns only — identifiers and auxiliary columns are excluded. */
export function isVariableAnalysisColumn(column: string, results: AnalysisResult): boolean {
  if (resolveAnalysisRole(column, results) === 'identifier') return false;
  if (isAuxiliaryColumn(column, results)) return false;
  return true;
}

export interface SkippedColumnSummary {
  identifiers: string[];
  auxiliary: string[];
  skippedCount: number;
}

export function skippedColumnSummary(results: AnalysisResult): SkippedColumnSummary {
  const identifiers: string[] = [];
  const auxiliary: string[] = [];

  for (const col of allColumnNames(results)) {
    if (isVariableAnalysisColumn(col, results)) continue;
    if (resolveAnalysisRole(col, results) === 'identifier') {
      identifiers.push(col);
    } else if (isAuxiliaryColumn(col, results)) {
      auxiliary.push(col);
    }
  }

  return {
    identifiers,
    auxiliary,
    skippedCount: identifiers.length + auxiliary.length,
  };
}

/** Domain-grouped column list for Step 7 — variable columns only. */
export function orderedVariableColumns(results: AnalysisResult): string[] {
  const allColumns = allColumnNames(results);
  const variableCols = allColumns.filter((c) => isVariableAnalysisColumn(c, results));

  const domainMap: Record<string, string> = {};
  for (const row of results.semantic_mapping ?? []) {
    if (!row.domain) continue;
    for (const col of allColumns) {
      if (columnNamesMatch(row.column, col)) {
        domainMap[col] = row.domain;
      }
    }
  }

  const domains = [...new Set(Object.values(domainMap))].sort();
  const ordered: string[] = [];
  for (const domain of domains) {
    ordered.push(...variableCols.filter((c) => domainMap[c] === domain));
  }
  ordered.push(...variableCols.filter((c) => !domainMap[c]));
  return ordered.length ? ordered : variableCols;
}
