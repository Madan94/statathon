import type { QueryAst, ReportSectionRequest } from './types';

export function buildQueryAst(request: ReportSectionRequest): QueryAst {
  const measure = request.scope.columns.measures[0];
  const groupBy = request.analysis.groupBy?.length ? request.analysis.groupBy : request.scope.columns.dimensions;
  const select: QueryAst['select'] = [
    ...groupBy.map(col => ({ expr: col, as: col, role: 'dimension' as const })),
  ];
  if (measure) {
    select.push({ expr: measure.col, as: measure.col, role: 'measure', agg: measure.agg || 'reported_value', unit: measure.unit });
  }
  select.push({ expr: 'count', as: 'n', role: 'metadata', agg: 'count' });
  return {
    datasetId: request.datasetId,
    select,
    where: request.scope.filters || [],
    filterCombinator: request.scope.filterCombinator || 'AND',
    groupBy,
    orderBy: request.analysis.sort ? { expr: request.analysis.sort.by, direction: request.analysis.sort.order } : null,
    limit: request.analysis.limit ?? null,
    provenance: { rowIdsRequired: request.options?.requireEvidence ?? true, sourceColumns: request.scope.columns.include },
  };
}
