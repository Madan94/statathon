/**
 * Audit-insights helpers.
 *
 * Turns the flat `dashboardApi.getActivity()` feed into per-dataset, phase-aware
 * audit trails with timestamps and elapsed/gap ("time-lapse") deltas, plus the
 * shared phase taxonomy and chart palette used by the Audit Logs and Analysis
 * pages. All functions are pure so they can be unit-tested in isolation.
 */
import type { ActivityItem } from '@/lib/api';
import { parseApiUtcTimestamp } from '@/lib/datetime';

export type AuditPhaseKey =
  | 'ingestion'
  | 'analysis'
  | 'extraction'
  | 'authoring'
  | 'generation'
  | 'correction'
  | 'other';

export interface AuditPhaseMeta {
  key: AuditPhaseKey;
  label: string;
  description: string;
  /** Hex colour used by both ECharts and inline Recharts/Tailwind styles. */
  color: string;
  order: number;
}

/** Ordered phase taxonomy mirroring the BharatStat pipeline stages. */
export const AUDIT_PHASES: AuditPhaseMeta[] = [
  { key: 'ingestion', label: 'Ingestion', description: 'Dataset uploaded & registered', color: '#2563eb', order: 0 },
  { key: 'analysis', label: 'Analysis', description: 'Validation · imputation · outliers · profiling', color: '#16a34a', order: 1 },
  { key: 'extraction', label: 'Template extraction', description: 'PDF → blueprint extraction', color: '#d97706', order: 2 },
  { key: 'authoring', label: 'Template authoring', description: 'Template saved & versioned', color: '#7c3aed', order: 3 },
  { key: 'generation', label: 'Report generation', description: 'Binding → render → PDF export', color: '#0d9488', order: 4 },
  { key: 'correction', label: 'Corrections', description: 'Manual edits & audit corrections', color: '#e11d48', order: 5 },
  { key: 'other', label: 'Other', description: 'Uncategorised events', color: '#64748b', order: 6 },
];

export const PHASE_META: Record<AuditPhaseKey, AuditPhaseMeta> = AUDIT_PHASES.reduce(
  (acc, meta) => {
    acc[meta.key] = meta;
    return acc;
  },
  {} as Record<AuditPhaseKey, AuditPhaseMeta>,
);

/** Map an activity `event_type` to a pipeline phase. */
export function classifyPhase(eventType: string): AuditPhaseKey {
  const type = (eventType || '').toLowerCase();
  if (type.startsWith('dataset.')) return 'ingestion';
  if (type.startsWith('analysis.')) return 'analysis';
  if (type.startsWith('template.extract')) return 'extraction';
  if (type.startsWith('template.')) return 'authoring';
  if (type.startsWith('report_job.')) return 'generation';
  if (type.startsWith('report.correction')) return 'correction';
  return 'other';
}

/** Outcome of an event, derived from the `event_type` suffix. */
export type AuditOutcome = 'success' | 'failure' | 'running' | 'neutral';

export function classifyOutcome(eventType: string): AuditOutcome {
  const type = (eventType || '').toLowerCase();
  if (/(failed|error|rejected)/.test(type)) return 'failure';
  if (/(running|processing|queued|pending|started)/.test(type)) return 'running';
  if (/(complete|completed|exported|verified|created|uploaded|done)/.test(type)) return 'success';
  return 'neutral';
}

export interface AuditEvent {
  eventType: string;
  title: string;
  phase: AuditPhaseKey;
  outcome: AuditOutcome;
  createdAt: string | null;
  ts: number | null;
  /** Gap since the previous event in the same dataset (ms). */
  gapMs: number | null;
  /** Cumulative elapsed since the first event in the same dataset (ms). */
  elapsedMs: number | null;
  metadata: Record<string, unknown>;
}

export interface DatasetAuditGroup {
  key: string;
  datasetId: number | null;
  datasetName: string;
  events: AuditEvent[];
  firstTs: number | null;
  lastTs: number | null;
  totalSpanMs: number | null;
  phaseCounts: Record<AuditPhaseKey, number>;
  failureCount: number;
  latestStatus: string;
}

function epochOf(iso: string | null): number | null {
  if (!iso) return null;
  const d = parseApiUtcTimestamp(iso);
  const t = d.getTime();
  return Number.isNaN(t) ? null : t;
}

function parseNameFromTitle(title: string): string | null {
  if (!title) return null;
  const colon = title.split(': ');
  if (colon.length > 1) return colon[colon.length - 1].trim();
  const forMatch = title.match(/ for (.+?)(?:$|\s\()/i);
  if (forMatch) return forMatch[1].trim();
  const parenMatch = title.match(/\(([^)]+)\)/);
  if (parenMatch) return parenMatch[1].trim();
  return null;
}

function emptyPhaseCounts(): Record<AuditPhaseKey, number> {
  return {
    ingestion: 0, analysis: 0, extraction: 0,
    authoring: 0, generation: 0, correction: 0, other: 0,
  };
}

/**
 * Group the activity feed into per-dataset audit trails. Events that carry a
 * `dataset_id` are grouped by dataset; template-only events are grouped by their
 * source document; anything else lands in a single "Other events" bucket.
 *
 * @param items   Raw activity feed.
 * @param nameHints Optional dataset_id → filename map (e.g. from the dashboard
 *                  summary) to resolve names for events whose title omits them.
 */
export function buildDatasetAuditGroups(
  items: ActivityItem[],
  nameHints?: Map<number, string>,
): DatasetAuditGroup[] {
  // Pass 1 — resolve dataset_id → best-known name.
  const names = new Map<number, string>(nameHints ?? []);
  for (const item of items) {
    const id = item.metadata?.dataset_id;
    if (typeof id === 'number' && item.event_type.startsWith('dataset.')) {
      const name = parseNameFromTitle(item.title);
      if (name) names.set(id, name);
    }
  }

  // Pass 2 — bucket events by group key.
  const groups = new Map<string, DatasetAuditGroup>();
  const ensure = (key: string, datasetId: number | null, datasetName: string) => {
    let g = groups.get(key);
    if (!g) {
      g = {
        key, datasetId, datasetName, events: [],
        firstTs: null, lastTs: null, totalSpanMs: null,
        phaseCounts: emptyPhaseCounts(), failureCount: 0, latestStatus: '—',
      };
      groups.set(key, g);
    }
    return g;
  };

  for (const item of items) {
    const phase = classifyPhase(item.event_type);
    const outcome = classifyOutcome(item.event_type);
    const datasetId = typeof item.metadata?.dataset_id === 'number' ? item.metadata.dataset_id : null;

    let key: string;
    let name: string;
    let groupDatasetId: number | null;
    if (datasetId != null) {
      key = `ds:${datasetId}`;
      name = names.get(datasetId) || `Dataset #${datasetId}`;
      groupDatasetId = datasetId;
    } else if (phase === 'extraction' || phase === 'authoring') {
      const src = (item.metadata?.source_filename as string) || parseNameFromTitle(item.title) || 'Template';
      key = `tpl:${src}`;
      name = src;
      groupDatasetId = null;
    } else {
      key = 'other';
      name = 'Other events';
      groupDatasetId = null;
    }

    const group = ensure(key, groupDatasetId, name);
    group.events.push({
      eventType: item.event_type,
      title: item.title,
      phase,
      outcome,
      createdAt: item.created_at,
      ts: epochOf(item.created_at),
      gapMs: null,
      elapsedMs: null,
      metadata: item.metadata || {},
    });
  }

  // Pass 3 — sort each group's events ascending and compute time-lapse deltas.
  const result: DatasetAuditGroup[] = [];
  for (const group of groups.values()) {
    group.events.sort((a, b) => {
      if (a.ts == null) return 1;
      if (b.ts == null) return -1;
      return a.ts - b.ts;
    });

    const timed = group.events.filter((e) => e.ts != null);
    const firstTs = timed.length ? timed[0].ts : null;
    const lastTs = timed.length ? timed[timed.length - 1].ts : null;
    let prevTs: number | null = null;
    for (const ev of group.events) {
      group.phaseCounts[ev.phase] += 1;
      if (ev.outcome === 'failure') group.failureCount += 1;
      if (ev.ts != null) {
        ev.gapMs = prevTs != null ? ev.ts - prevTs : 0;
        ev.elapsedMs = firstTs != null ? ev.ts - firstTs : 0;
        prevTs = ev.ts;
      }
    }
    group.firstTs = firstTs;
    group.lastTs = lastTs;
    group.totalSpanMs = firstTs != null && lastTs != null ? lastTs - firstTs : null;
    // Latest status = newest event's outcome-bearing type suffix.
    const newest = group.events[group.events.length - 1];
    group.latestStatus = newest ? newest.eventType : '—';
    result.push(group);
  }

  // Most-recently-active datasets first; "Other" sinks to the bottom.
  result.sort((a, b) => {
    if (a.key === 'other') return 1;
    if (b.key === 'other') return -1;
    return (b.lastTs ?? 0) - (a.lastTs ?? 0);
  });
  return result;
}

/** Humanise a millisecond duration, e.g. 75000 → "1m 15s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '—';
  if (ms < 0) return '—';
  if (ms < 1000) return '<1s';
  const totalSec = Math.floor(ms / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}
