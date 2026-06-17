import type { DatasetSnapshot, ReportSectionRequest, SectionIssue, SectionValidationResult } from './types';

function hasColumn(snapshot: DatasetSnapshot, col: string): boolean {
  return snapshot.columns.includes(col);
}

function valueExists(values: unknown[], value: unknown): boolean {
  const norm = (v: unknown) => String(v ?? '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
  if (Array.isArray(value)) return value.every(v => values.some(x => norm(x) === norm(v)));
  return values.some(v => norm(v) === norm(value));
}

function closest(values: unknown[], value: unknown): unknown | undefined {
  const input = String(Array.isArray(value) ? value[0] : value ?? '').toLowerCase();
  if (!input) return undefined;
  return values.find(v => String(v).toLowerCase().includes(input) || input.includes(String(v).toLowerCase()));
}

export function validateSectionRequest(request: ReportSectionRequest, snapshot: DatasetSnapshot | null): SectionValidationResult {
  const issues: SectionIssue[] = [];
  if (!snapshot) {
    return { status: 'cannot_compute', issues: [{ severity: 'error', code: 'DATASET_NOT_LOADED', message: `Dataset '${request.datasetId}' is not loaded in the frontend cache.` }] };
  }

  if (snapshot.rowCount >= 60000) {
    issues.push({ severity: 'warn', code: 'FRONTEND_MEMORY_WARNING', message: `Dataset has ${snapshot.rowCount.toLocaleString()} rows. Frontend execution may be slower.` });
  }

  for (const col of request.scope.columns.include || []) {
    if (!hasColumn(snapshot, col)) issues.push({ severity: 'warn', code: 'INCLUDED_COLUMN_MISSING', message: `Included column '${col}' is missing.`, column: col });
  }
  for (const dim of request.scope.columns.dimensions || []) {
    if (!hasColumn(snapshot, dim)) issues.push({ severity: 'error', code: 'DIMENSION_MISSING', message: `Dimension '${dim}' is missing.`, column: dim });
  }
  for (const measure of request.scope.columns.measures || []) {
    if (!hasColumn(snapshot, measure.col)) issues.push({ severity: 'error', code: 'MEASURE_MISSING', message: `Measure '${measure.col}' is missing.`, column: measure.col });
  }
  for (const predicate of request.scope.filters || []) {
    if (!hasColumn(snapshot, predicate.col)) {
      issues.push({ severity: predicate.required ? 'warn' : 'info', code: 'FILTER_COLUMN_MISSING', message: `Filter column '${predicate.col}' is missing.`, column: predicate.col });
      continue;
    }
    if (!['is_null', 'not_null', 'gt', 'ge', 'lt', 'le', 'between'].includes(predicate.op)) {
      const values = snapshot.distinctValues[predicate.col] || [];
      if (values.length && !valueExists(values, predicate.value)) {
        issues.push({ severity: 'warn', code: 'FILTER_VALUE_NOT_CONFIRMED', message: `Value '${String(predicate.value)}' was not found exactly in '${predicate.col}'.`, column: predicate.col, suggestion: closest(values, predicate.value) });
      }
    }
  }
  for (const group of request.analysis.groupBy || []) {
    if (!hasColumn(snapshot, group)) issues.push({ severity: 'error', code: 'GROUP_BY_MISSING', message: `Group-by column '${group}' is missing.`, column: group });
  }
  for (const component of request.components || []) {
    if (component.type === 'chart') {
      if (component.x && !hasColumn(snapshot, component.x)) issues.push({ severity: 'warn', code: 'CHART_X_MISSING', message: `Chart x column '${component.x}' is missing.`, column: component.x });
      if (component.y && !hasColumn(snapshot, component.y)) issues.push({ severity: 'warn', code: 'CHART_Y_MISSING', message: `Chart y column '${component.y}' is missing.`, column: component.y });
    }
  }

  const hasError = issues.some(i => i.severity === 'error');
  return { status: hasError ? 'cannot_compute' : issues.length ? 'warning' : 'ready', issues };
}
