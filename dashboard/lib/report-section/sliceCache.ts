import type { DataRow, ReportSectionRequest, SectionExecutionResult } from './types';
import { stableHash } from './datasetStore';
import { executeSectionRequest } from './aggregationEngine';

const resultCache = new Map<string, SectionExecutionResult>();

export function sliceSignatureOf(request: ReportSectionRequest): string {
  return stableHash({
    datasetId: request.datasetId,
    filters: request.scope.filters,
    filterCombinator: request.scope.filterCombinator || 'AND',
    include: request.scope.columns.include,
    groupBy: request.analysis.groupBy,
    measures: request.scope.columns.measures,
    sort: request.analysis.sort,
    limit: request.analysis.limit,
  });
}

export function executeWithSliceCache(request: ReportSectionRequest, rows: DataRow[]): SectionExecutionResult {
  const key = sliceSignatureOf(request);
  if (request.options?.cache !== false && resultCache.has(key)) {
    const cached = resultCache.get(key)!;
    return { ...cached, cacheHit: true };
  }
  const result = executeSectionRequest(request, rows, false);
  if (request.options?.cache !== false) resultCache.set(key, result);
  return result;
}

export function clearSectionResultCache(): void {
  resultCache.clear();
}
