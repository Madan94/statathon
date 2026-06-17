import type { DataRow, SectionIssue, SectionPredicate } from './types';

function norm(value: unknown): string {
  return String(value ?? '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Number(value))) return Number(value);
  return null;
}

function equals(a: unknown, b: unknown): boolean {
  const an = asNumber(a);
  const bn = asNumber(b);
  if (an !== null && bn !== null) return an === bn;
  return norm(a) === norm(b);
}

function cmp(a: unknown, b: unknown, op: 'gt' | 'ge' | 'lt' | 'le'): boolean {
  const an = asNumber(a);
  const bn = asNumber(b);
  if (an === null || bn === null) return false;
  if (op === 'gt') return an > bn;
  if (op === 'ge') return an >= bn;
  if (op === 'lt') return an < bn;
  return an <= bn;
}

export function predicateToText(predicate: SectionPredicate): string {
  const value = Array.isArray(predicate.value) ? `(${predicate.value.map(String).join(', ')})` : String(predicate.value ?? '');
  const op = predicate.op === 'eq' ? '==' : predicate.op === 'ne' ? '!=' : predicate.op.toUpperCase();
  return `${predicate.col} ${op} ${value}`.trim();
}

export function testPredicate(row: DataRow, predicate: SectionPredicate): boolean {
  const actual = row[predicate.col];
  switch (predicate.op) {
    case 'eq': return equals(actual, predicate.value);
    case 'ne': return !equals(actual, predicate.value);
    case 'in': return Array.isArray(predicate.value) && predicate.value.some(v => equals(actual, v));
    case 'not_in': return Array.isArray(predicate.value) && !predicate.value.some(v => equals(actual, v));
    case 'gt': case 'ge': case 'lt': case 'le': return cmp(actual, predicate.value, predicate.op);
    case 'between': {
      if (!Array.isArray(predicate.value) || predicate.value.length < 2) return false;
      const an = asNumber(actual);
      const lo = asNumber(predicate.value[0]);
      const hi = asNumber(predicate.value[1]);
      return an !== null && lo !== null && hi !== null && an >= lo && an <= hi;
    }
    case 'contains': return norm(actual).includes(norm(predicate.value));
    case 'is_null': return actual === null || actual === undefined || actual === '';
    case 'not_null': return !(actual === null || actual === undefined || actual === '');
    default: return false;
  }
}

export function applyPredicates(rows: DataRow[], predicates: SectionPredicate[]): { indexes: number[]; filtersApplied: string[]; warnings: SectionIssue[] } {
  const warnings: SectionIssue[] = [];
  const indexes: number[] = [];
  for (let index = 0; index < rows.length; index++) {
    const row = rows[index];
    let keep = true;
    for (const predicate of predicates) {
      if (!(predicate.col in row)) {
        warnings.push({ severity: predicate.required ? 'warn' : 'info', code: 'FILTER_COLUMN_MISSING', message: `Filter column '${predicate.col}' is missing; filter was widened.`, column: predicate.col });
        continue;
      }
      if (!testPredicate(row, predicate)) {
        keep = false;
        break;
      }
    }
    if (keep) indexes.push(index);
  }
  return { indexes, filtersApplied: predicates.map(predicateToText), warnings };
}
