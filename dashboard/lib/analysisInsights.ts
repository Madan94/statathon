/**
 * Analysis-insights helpers.
 *
 * Derives a cross-dataset analysis roll-up from the activity feed + dashboard
 * summary, and extracts per-phase calculation series (validation severities,
 * imputation methods, outlier counts, weighting, pipeline completion) from a
 * single analysis result for charting. Pure functions — no React, no I/O.
 */
import type {
  ActivityItem,
  DashboardSummary,
  ImputationCandidate,
  OutlierResult,
  ValidationCandidate,
  WeightedProfile,
} from '@/lib/api';

export type AnalysisStatusKey = 'complete' | 'running' | 'failed' | 'none';

export const STATUS_META: Record<AnalysisStatusKey, { label: string; color: string }> = {
  complete: { label: 'Complete', color: '#16a34a' },
  running: { label: 'Running', color: '#d97706' },
  failed: { label: 'Failed', color: '#e11d48' },
  none: { label: 'Not analysed', color: '#94a3b8' },
};

export const RISK_COLOR: Record<string, string> = {
  high: '#e11d48',
  medium: '#d97706',
  low: '#16a34a',
  unknown: '#94a3b8',
};

/** Qualitative palette for categorical charts without a fixed colour mapping. */
export const CHART_PALETTE_FALLBACK = [
  '#2563eb', '#16a34a', '#d97706', '#7c3aed', '#0d9488',
  '#e11d48', '#0891b2', '#ca8a04', '#9333ea', '#dc2626',
];

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info', 'unknown'];
export const SEVERITY_COLOR: Record<string, string> = {
  critical: '#9f1239',
  high: '#e11d48',
  medium: '#d97706',
  low: '#2563eb',
  info: '#0891b2',
  unknown: '#94a3b8',
};

export interface DatasetAnalysisRow {
  id: number;
  name: string;
  rowCount: number;
  columnCount: number;
  uploadedAt: string | null;
  analysisId: number | null;
  analysisStatus: AnalysisStatusKey;
  completedAt: string | null;
  reportCount: number;
}

function normaliseStatus(raw: string | undefined): AnalysisStatusKey {
  const s = (raw || '').toLowerCase();
  if (s === 'complete' || s === 'completed') return 'complete';
  if (s === 'failed' || s === 'error') return 'failed';
  if (s === 'running' || s === 'processing' || s === 'queued' || s === 'pending') return 'running';
  return 'none';
}

function nameFromTitle(title: string): string | null {
  const colon = title.split(': ');
  if (colon.length > 1) return colon[colon.length - 1].trim();
  const forMatch = title.match(/ for (.+?)(?:$|\s\()/i);
  return forMatch ? forMatch[1].trim() : null;
}

/**
 * Fuse the dashboard summary and activity feed into one analysis row per
 * dataset, carrying its latest analysis status and report-job count.
 */
export function buildDatasetAnalysisRows(
  items: ActivityItem[],
  summary: DashboardSummary | null,
): DatasetAnalysisRow[] {
  const rows = new Map<number, DatasetAnalysisRow>();
  const ensure = (id: number): DatasetAnalysisRow => {
    let r = rows.get(id);
    if (!r) {
      r = {
        id, name: `Dataset #${id}`, rowCount: 0, columnCount: 0, uploadedAt: null,
        analysisId: null, analysisStatus: 'none', completedAt: null, reportCount: 0,
      };
      rows.set(id, r);
    }
    return r;
  };

  summary?.latest_datasets.forEach((d) => {
    const r = ensure(d.id);
    r.name = d.filename || r.name;
    r.rowCount = d.row_count || r.rowCount;
    r.columnCount = d.column_count || r.columnCount;
    r.uploadedAt = d.created_at ?? r.uploadedAt;
  });

  for (const item of items) {
    const id = item.metadata?.dataset_id;
    if (typeof id !== 'number') continue;
    const r = ensure(id);

    if (item.event_type.startsWith('dataset.')) {
      const name = nameFromTitle(item.title);
      if (name) r.name = name;
      if (typeof item.metadata.row_count === 'number') r.rowCount = item.metadata.row_count;
      if (typeof item.metadata.column_count === 'number') r.columnCount = item.metadata.column_count;
      if (!r.uploadedAt) r.uploadedAt = item.created_at;
    } else if (item.event_type.startsWith('analysis.')) {
      // Activity is newest-first, so only record the first (latest) analysis seen.
      if (r.analysisId == null && typeof item.metadata.analysis_id === 'number') {
        r.analysisId = item.metadata.analysis_id;
        r.analysisStatus = normaliseStatus(item.metadata.status as string | undefined);
        r.completedAt = (item.metadata.completed_at as string | null) ?? item.created_at;
      }
    } else if (item.event_type.startsWith('report_job.')) {
      r.reportCount += 1;
    }
  }

  return Array.from(rows.values()).sort((a, b) => (b.uploadedAt ?? '').localeCompare(a.uploadedAt ?? ''));
}

/** Status distribution for the cross-dataset donut. */
export function statusDistribution(rows: DatasetAnalysisRow[]): Array<{ key: AnalysisStatusKey; label: string; count: number; color: string }> {
  const counts: Record<AnalysisStatusKey, number> = { complete: 0, running: 0, failed: 0, none: 0 };
  rows.forEach((r) => { counts[r.analysisStatus] += 1; });
  return (Object.keys(counts) as AnalysisStatusKey[])
    .map((key) => ({ key, label: STATUS_META[key].label, count: counts[key], color: STATUS_META[key].color }))
    .filter((d) => d.count > 0);
}

// ── Per-analysis phase calculations ─────────────────────────────────────────

export interface PhaseCompletion {
  key: string;
  label: string;
  pct: number;
  reviewed: number;
  total: number;
  complete: boolean;
}

interface PhaseStatusShape {
  validation?: { total?: number; reviewed?: number; complete?: boolean };
  anomaly?: { columns_total?: number; columns_reviewed?: number; complete?: boolean };
  imputation?: { columns_total?: number; columns_reviewed?: number; complete?: boolean };
  weight_application_completed?: boolean;
}

function pct(reviewed: number, total: number): number {
  if (total <= 0) return reviewed > 0 ? 100 : 0;
  return Math.round((reviewed / total) * 100);
}

export function phaseCompletion(status: PhaseStatusShape | null | undefined): PhaseCompletion[] {
  if (!status) return [];
  const v = status.validation ?? {};
  const a = status.anomaly ?? {};
  const i = status.imputation ?? {};
  const vTotal = v.total ?? 0;
  const vReviewed = v.reviewed ?? 0;
  const aTotal = a.columns_total ?? 0;
  const aReviewed = a.columns_reviewed ?? 0;
  const iTotal = i.columns_total ?? 0;
  const iReviewed = i.columns_reviewed ?? 0;
  return [
    { key: 'validation', label: 'Rule validation', pct: pct(vReviewed, vTotal), reviewed: vReviewed, total: vTotal, complete: Boolean(v.complete) },
    { key: 'anomaly', label: 'Anomaly review', pct: pct(aReviewed, aTotal), reviewed: aReviewed, total: aTotal, complete: Boolean(a.complete) },
    { key: 'imputation', label: 'Missing-value imputation', pct: pct(iReviewed, iTotal), reviewed: iReviewed, total: iTotal, complete: Boolean(i.complete) },
    { key: 'weighting', label: 'Weight application', pct: status.weight_application_completed ? 100 : 0, reviewed: status.weight_application_completed ? 1 : 0, total: 1, complete: Boolean(status.weight_application_completed) },
  ];
}

export function groupValidationBySeverity(cands: ValidationCandidate[] | undefined): Array<{ severity: string; count: number; color: string }> {
  const counts = new Map<string, number>();
  (cands ?? []).forEach((c) => {
    const sev = (c.severity || 'unknown').toLowerCase();
    counts.set(sev, (counts.get(sev) ?? 0) + 1);
  });
  return Array.from(counts.entries())
    .sort((a, b) => SEVERITY_ORDER.indexOf(a[0]) - SEVERITY_ORDER.indexOf(b[0]))
    .map(([severity, count]) => ({
      severity,
      count,
      color: SEVERITY_COLOR[severity] ?? SEVERITY_COLOR.unknown,
    }));
}

export function groupImputationByMethod(cands: ImputationCandidate[] | undefined): Array<{ method: string; count: number }> {
  const counts = new Map<string, number>();
  (cands ?? []).forEach((c) => {
    const m = c.recommended_method || 'unspecified';
    counts.set(m, (counts.get(m) ?? 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([method, count]) => ({ method, count }))
    .sort((a, b) => b.count - a.count);
}

export function imputationMissingByColumn(cands: ImputationCandidate[] | undefined, limit = 12): Array<{ column: string; missing: number }> {
  return (cands ?? [])
    .map((c) => ({ column: c.column, missing: c.missing_count ?? 0 }))
    .filter((c) => c.missing > 0)
    .sort((a, b) => b.missing - a.missing)
    .slice(0, limit);
}

export function outlierColumns(outliers: Record<string, OutlierResult> | undefined, limit = 14): Array<{ column: string; count: number; risk: string; color: string }> {
  if (!outliers) return [];
  return Object.entries(outliers)
    .map(([column, res]) => {
      const count = Math.max(res?.zscore?.length ?? 0, res?.iqr?.length ?? 0);
      const risk = (res?.risk as string) || 'unknown';
      return { column, count, risk, color: RISK_COLOR[risk] ?? RISK_COLOR.unknown };
    })
    .filter((c) => c.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, limit);
}

export function weightedMeans(wp: WeightedProfile | undefined, limit = 12): Array<{ column: string; value: number }> {
  if (!wp?.applied || !wp.weighted_numeric_means) return [];
  return Object.entries(wp.weighted_numeric_means)
    .map(([column, value]) => ({ column, value: Number(value) }))
    .filter((c) => Number.isFinite(c.value))
    .slice(0, limit);
}

/** Pull a handful of scalar (number/string/bool) metrics for headline tiles. */
export function scalarMetrics(obj: Record<string, unknown> | undefined, limit = 8): Array<{ label: string; value: string }> {
  if (!obj) return [];
  const out: Array<{ label: string; value: string }> = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v == null) continue;
    if (typeof v === 'number') {
      out.push({ label: k, value: Number.isInteger(v) ? String(v) : v.toFixed(2) });
    } else if (typeof v === 'string' && v.length <= 48) {
      out.push({ label: k, value: v });
    } else if (typeof v === 'boolean') {
      out.push({ label: k, value: v ? 'yes' : 'no' });
    }
    if (out.length >= limit) break;
  }
  return out;
}

export function prettifyKey(key: string): string {
  return key.replace(/[_.]/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}
