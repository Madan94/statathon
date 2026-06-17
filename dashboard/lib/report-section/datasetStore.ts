import type { DataRow, DatasetSnapshot, FilterCombinator, SectionPredicate } from './types';
import { applyPredicates } from './predicateEngine';

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const obj = value as Record<string, unknown>;
  return `{${Object.keys(obj).sort().map(k => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(',')}}`;
}

function hashString(input: string): string {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return `h_${(hash >>> 0).toString(16)}`;
}

function inferType(values: unknown[]): DatasetSnapshot['columnTypes'][string] {
  const sample = values.filter(v => v !== null && v !== undefined && v !== '').slice(0, 50);
  if (!sample.length) return 'unknown';
  if (sample.every(v => typeof v === 'number' || (typeof v === 'string' && v.trim() !== '' && !Number.isNaN(Number(v))))) return 'number';
  if (sample.every(v => typeof v === 'boolean')) return 'boolean';
  if (sample.every(v => typeof v === 'string' && !Number.isNaN(Date.parse(v)))) return 'date';
  return 'string';
}

function coerceCell(raw: string): unknown {
  const value = raw.trim();
  if (value === '') return null;
  if (/^-?\d+(\.\d+)?$/.test(value)) return Number(value);
  if (/^(true|false)$/i.test(value)) return /^true$/i.test(value);
  return value;
}

export function parseRowsInput(input: string): DataRow[] {
  const text = input.trim();
  if (!text) return [];
  if (text.startsWith('[')) {
    const parsed = JSON.parse(text) as unknown;
    if (!Array.isArray(parsed)) throw new Error('Dataset JSON must be an array of rows');
    return parsed as DataRow[];
  }
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map(h => h.trim());
  return lines.slice(1).map(line => {
    const cells = line.split(',');
    const row: DataRow = {};
    headers.forEach((h, i) => { row[h] = coerceCell(cells[i] ?? ''); });
    return row;
  });
}

export function buildDatasetSnapshot(datasetId: string, rows: DataRow[]): DatasetSnapshot {
  const columns = Array.from(new Set(rows.flatMap(row => Object.keys(row))));
  const columnTypes: DatasetSnapshot['columnTypes'] = {};
  const distinctValues: DatasetSnapshot['distinctValues'] = {};
  for (const col of columns) {
    const vals = rows.map(r => r[col]);
    columnTypes[col] = inferType(vals);
    const seen = new Set<string>();
    const distinct: unknown[] = [];
    for (const v of vals) {
      if (v === null || v === undefined || v === '') continue;
      const key = String(v).trim().toLowerCase();
      if (!seen.has(key)) {
        seen.add(key);
        distinct.push(v);
      }
      if (distinct.length >= 250) break;
    }
    distinctValues[col] = distinct;
  }
  return {
    datasetId,
    rows,
    columns,
    columnTypes,
    distinctValues,
    rowCount: rows.length,
    signature: hashString(stableStringify({ datasetId, columns, rowCount: rows.length, sample: rows.slice(0, 25) })),
  };
}

export interface DatasetProvider {
  registerRows(datasetId: string, rows: DataRow[]): DatasetSnapshot;
  has(datasetId: string): boolean;
  getSnapshot(datasetId: string): DatasetSnapshot | null;
  getRows(datasetId: string): DataRow[];
  getDistinctValues(datasetId: string, column: string): unknown[];
  getSlice(datasetId: string, predicates: SectionPredicate[], includeColumns: string[], filterCombinator?: FilterCombinator): { rows: DataRow[]; indexes: number[]; filtersApplied: string[] };
  clear(datasetId: string): void;
  clearAll(): void;
}

class FrontendMemoryDatasetProvider implements DatasetProvider {
  private snapshots = new Map<string, DatasetSnapshot>();

  registerRows(datasetId: string, rows: DataRow[]): DatasetSnapshot {
    const snapshot = buildDatasetSnapshot(datasetId, rows);
    this.snapshots.set(datasetId, snapshot);
    return snapshot;
  }

  has(datasetId: string): boolean {
    return this.snapshots.has(datasetId);
  }

  getSnapshot(datasetId: string): DatasetSnapshot | null {
    return this.snapshots.get(datasetId) ?? null;
  }

  getRows(datasetId: string): DataRow[] {
    return this.getSnapshot(datasetId)?.rows ?? [];
  }

  getDistinctValues(datasetId: string, column: string): unknown[] {
    return this.getSnapshot(datasetId)?.distinctValues[column] ?? [];
  }

  getSlice(datasetId: string, predicates: SectionPredicate[], includeColumns: string[], filterCombinator: FilterCombinator = 'AND') {
    const snapshot = this.getSnapshot(datasetId);
    if (!snapshot) return { rows: [], indexes: [], filtersApplied: [] };
    const filtered = applyPredicates(snapshot.rows, predicates, filterCombinator);
    const include = includeColumns.filter(c => snapshot.columns.includes(c));
    const rows = filtered.indexes.map(i => {
      const source = snapshot.rows[i];
      if (!include.length) return source;
      const row: DataRow = {};
      include.forEach(c => { row[c] = source[c]; });
      return row;
    });
    return { rows, indexes: filtered.indexes, filtersApplied: filtered.filtersApplied };
  }

  clear(datasetId: string): void {
    this.snapshots.delete(datasetId);
  }

  clearAll(): void {
    this.snapshots.clear();
  }
}

export const reportSectionDatasetStore: DatasetProvider = new FrontendMemoryDatasetProvider();
export const stableHash = (value: unknown): string => hashString(stableStringify(value));
export const stableJson = stableStringify;
