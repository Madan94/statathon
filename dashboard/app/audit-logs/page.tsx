'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  Layers,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { dashboardApi, type ActivityItem } from '@/lib/api';
import { formatIndiaTime } from '@/lib/datetime';
import {
  AUDIT_PHASES,
  PHASE_META,
  buildDatasetAuditGroups,
  formatDuration,
  type AuditOutcome,
  type AuditPhaseKey,
  type DatasetAuditGroup,
} from '@/lib/auditInsights';

const OUTCOME_BADGE: Record<AuditOutcome, { variant: 'success' | 'danger' | 'warning' | 'muted'; label: string }> = {
  success: { variant: 'success', label: 'OK' },
  failure: { variant: 'danger', label: 'Failed' },
  running: { variant: 'warning', label: 'Running' },
  neutral: { variant: 'muted', label: 'Info' },
};

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Activity;
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{label}</p>
          <p className="mt-1.5 text-2xl font-bold text-text">{value}</p>
          {hint && <p className="mt-0.5 truncate text-xs text-text-muted">{hint}</p>}
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      </div>
    </Card>
  );
}

function PhaseDot({ phase }: { phase: AuditPhaseKey }) {
  return (
    <span
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ backgroundColor: PHASE_META[phase].color }}
      aria-hidden
    />
  );
}

export default function AuditLogsPage() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [nameHints, setNameHints] = useState<Map<number, string>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [phaseFilter, setPhaseFilter] = useState<AuditPhaseKey | 'all'>('all');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [activity, summary] = await Promise.all([
          dashboardApi.getActivity(300),
          dashboardApi.getSummary().catch(() => null),
        ]);
        if (cancelled) return;
        setItems(activity);
        if (summary) {
          const hints = new Map<number, string>();
          summary.latest_datasets.forEach((d) => hints.set(d.id, d.filename));
          setNameHints(hints);
        }
      } catch (e: unknown) {
        if (!cancelled) {
          const ax = e as { response?: { data?: { detail?: string } }; message?: string };
          setError(ax.response?.data?.detail || ax.message || 'Failed to load audit logs');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(() => buildDatasetAuditGroups(items, nameHints), [items, nameHints]);

  // Default-expand the most recently active dataset once data arrives.
  useEffect(() => {
    if (groups.length && expanded.size === 0) {
      setExpanded(new Set([groups[0].key]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups.length]);

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return groups
      .map((g) => {
        if (phaseFilter === 'all') return g;
        // Keep only events of the selected phase within each group.
        return { ...g, events: g.events.filter((e) => e.phase === phaseFilter) };
      })
      .filter((g) => g.events.length > 0)
      .filter((g) => {
        if (!q) return true;
        return (
          g.datasetName.toLowerCase().includes(q) ||
          g.events.some((e) => `${e.title} ${e.eventType}`.toLowerCase().includes(q))
        );
      });
  }, [groups, query, phaseFilter]);

  const totals = useMemo(() => {
    const totalEvents = groups.reduce((sum, g) => sum + g.events.length, 0);
    const datasetGroups = groups.filter((g) => g.datasetId != null);
    const failures = groups.reduce((sum, g) => sum + g.failureCount, 0);
    const widestSpan = groups.reduce((max, g) => Math.max(max, g.totalSpanMs ?? 0), 0);
    const activePhaseKeys = new Set<AuditPhaseKey>();
    groups.forEach((g) => {
      (Object.keys(g.phaseCounts) as AuditPhaseKey[]).forEach((p) => {
        if (g.phaseCounts[p] > 0) activePhaseKeys.add(p);
      });
    });
    return { totalEvents, datasets: datasetGroups.length, failures, widestSpan, activePhases: activePhaseKeys.size };
  }, [groups]);

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Logs"
        description="Phase-by-phase audit trail for every dataset — ingestion, analysis, extraction, report generation and corrections — with timestamps and elapsed time-lapse."
      />

      {error && <Alert variant="error">{error}</Alert>}

      {loading ? (
        <Card className="p-8 text-sm text-text-muted">Loading audit trail…</Card>
      ) : groups.length === 0 ? (
        <Card className="p-8 text-center text-sm text-text-muted">
          No audited activity yet. Upload a dataset and run an analysis to populate the trail.
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <StatTile icon={Activity} label="Audited events" value={totals.totalEvents} hint="across all phases" />
            <StatTile icon={Database} label="Datasets tracked" value={totals.datasets} hint="with a trail" />
            <StatTile icon={Layers} label="Active phases" value={totals.activePhases} hint={`of ${AUDIT_PHASES.length}`} />
            <StatTile icon={Clock} label="Widest span" value={formatDuration(totals.widestSpan)} hint="longest dataset lifecycle" />
            <StatTile icon={AlertTriangle} label="Failures" value={totals.failures} hint="failed / rejected events" />
          </div>

          <Card>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search dataset, event title or type"
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 md:max-w-md"
              />
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setPhaseFilter('all')}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${phaseFilter === 'all' ? 'bg-primary text-white' : 'bg-surface text-text-muted hover:bg-surface-card'}`}
                >
                  All phases
                </button>
                {AUDIT_PHASES.map((meta) => (
                  <button
                    key={meta.key}
                    type="button"
                    onClick={() => setPhaseFilter(meta.key)}
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors ${phaseFilter === meta.key ? 'text-white' : 'bg-surface text-text-muted hover:bg-surface-card'}`}
                    style={phaseFilter === meta.key ? { backgroundColor: meta.color } : undefined}
                  >
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: phaseFilter === meta.key ? '#fff' : meta.color }} />
                    {meta.label}
                  </button>
                ))}
              </div>
            </div>
          </Card>

          <div className="space-y-3">
            {filteredGroups.map((group) => (
              <DatasetAuditCard key={group.key} group={group} open={expanded.has(group.key)} onToggle={() => toggle(group.key)} />
            ))}
            {filteredGroups.length === 0 && (
              <Card className="p-6 text-center text-sm text-text-muted">No events match the current filters.</Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function DatasetAuditCard({
  group,
  open,
  onToggle,
}: {
  group: DatasetAuditGroup;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <Card className="overflow-hidden p-0">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-surface"
      >
        <div className="flex min-w-0 items-center gap-3">
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
          )}
          <div className="min-w-0">
            <p className="flex items-center gap-2 truncate font-semibold text-text">
              <Database className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
              {group.datasetName}
              {group.datasetId != null && (
                <span className="rounded bg-surface px-1.5 py-0.5 font-mono text-[10px] text-text-muted">#{group.datasetId}</span>
              )}
            </p>
            <p className="mt-0.5 truncate text-xs text-text-muted">
              {group.events.length} events · span {formatDuration(group.totalSpanMs)} · last {formatIndiaTime(group.lastTs ? new Date(group.lastTs).toISOString() : null)}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {(Object.keys(group.phaseCounts) as AuditPhaseKey[])
            .filter((p) => group.phaseCounts[p] > 0)
            .map((p) => (
              <span
                key={p}
                title={`${PHASE_META[p].label}: ${group.phaseCounts[p]}`}
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                style={{ backgroundColor: `${PHASE_META[p].color}1a`, color: PHASE_META[p].color }}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: PHASE_META[p].color }} />
                {group.phaseCounts[p]}
              </span>
            ))}
          {group.failureCount > 0 && <Badge variant="danger">{group.failureCount} failed</Badge>}
        </div>
      </button>

      {open && (
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
                <th className="px-5 py-2.5 font-medium">Timestamp (IST)</th>
                <th className="px-5 py-2.5 font-medium">Phase</th>
                <th className="px-5 py-2.5 font-medium">Event</th>
                <th className="px-5 py-2.5 font-medium">Gap</th>
                <th className="px-5 py-2.5 font-medium">Elapsed</th>
                <th className="px-5 py-2.5 font-medium">Outcome</th>
                <th className="px-5 py-2.5 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {group.events.map((ev, idx) => {
                const badge = OUTCOME_BADGE[ev.outcome];
                return (
                  <tr key={`${ev.eventType}-${ev.createdAt}-${idx}`} className="border-b border-border/40 align-top last:border-0">
                    <td className="whitespace-nowrap px-5 py-2.5 text-text-muted">{formatIndiaTime(ev.createdAt)}</td>
                    <td className="px-5 py-2.5">
                      <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: PHASE_META[ev.phase].color }}>
                        <PhaseDot phase={ev.phase} />
                        {PHASE_META[ev.phase].label}
                      </span>
                    </td>
                    <td className="px-5 py-2.5">
                      <p className="font-medium text-text">{ev.title}</p>
                      <code className="text-[11px] text-text-muted">{ev.eventType}</code>
                    </td>
                    <td className="whitespace-nowrap px-5 py-2.5 text-text-muted">{idx === 0 ? '—' : formatDuration(ev.gapMs)}</td>
                    <td className="whitespace-nowrap px-5 py-2.5 text-text-muted">{formatDuration(ev.elapsedMs)}</td>
                    <td className="px-5 py-2.5">
                      <Badge variant={badge.variant}>{badge.label}</Badge>
                    </td>
                    <td className="px-5 py-2.5">
                      <MetadataChips metadata={ev.metadata} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const META_HIDDEN_KEYS = new Set(['dataset_id']);

function MetadataChips({ metadata }: { metadata: Record<string, unknown> }) {
  const [raw, setRaw] = useState(false);
  const entries = Object.entries(metadata).filter(
    ([k, v]) => !META_HIDDEN_KEYS.has(k) && v != null && v !== '',
  );
  if (entries.length === 0) return <span className="text-xs text-text-muted">—</span>;
  if (raw) {
    return (
      <button type="button" onClick={() => setRaw(false)} className="text-left">
        <pre className="max-w-[320px] whitespace-pre-wrap rounded bg-surface p-2 text-[11px] text-text-muted">
          {JSON.stringify(metadata, null, 2)}
        </pre>
      </button>
    );
  }
  return (
    <div className="flex max-w-[320px] flex-wrap items-center gap-1">
      {entries.slice(0, 4).map(([k, v]) => (
        <span key={k} className="inline-flex items-center gap-1 rounded bg-surface px-1.5 py-0.5 text-[11px] text-text-muted">
          <span className="font-medium text-text">{k}</span>
          <span className="max-w-[140px] truncate">{String(v)}</span>
        </span>
      ))}
      {entries.length > 4 && (
        <button type="button" onClick={() => setRaw(true)} className="rounded bg-surface px-1.5 py-0.5 text-[11px] font-medium text-primary hover:underline">
          +{entries.length - 4} more
        </button>
      )}
    </div>
  );
}
