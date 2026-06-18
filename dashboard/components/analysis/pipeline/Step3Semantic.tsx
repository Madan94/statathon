'use client';

import { useEffect, useMemo, useState } from 'react';
import { analysisApi, DomainsPayload, SemanticMappingRow, DomainRegistry } from '@/lib/api';
import type { AnalysisResult } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import {
  ChevronLeft,
  CheckCircle2,
  Info,
  Zap,
  Database,
  GitBranch,
  Cpu,
  Search,
  BookOpen,
  Table2,
  AlertTriangle,
  RotateCcw,
  ChevronDown,
  Fingerprint,
  BarChart3,
} from 'lucide-react';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  overrides: Record<string, string>;
  effectiveSchema?: string[];
  normalizationVersion?: number | null;
  onProceed: (overrides: Record<string, string>) => void;
  onBack: () => void;
}

type RoleFilter = 'all' | 'identifier' | 'variable';
type ReviewFilter = 'all' | 'overridden' | 'low_confidence';
type MainView = 'columns' | 'domains';

const ROUTING_LABELS: Record<
  string,
  { label: string; icon: React.ReactNode; variant: 'success' | 'default' | 'warning' | 'muted' }
> = {
  schema_suffix_lock: { label: 'Suffix lock', icon: <Database className="h-3 w-3" />, variant: 'success' },
  rapidfuzz_ontology: { label: 'RapidFuzz', icon: <Zap className="h-3 w-3" />, variant: 'success' },
  schema_ontology_lock: { label: 'Ontology lock', icon: <Database className="h-3 w-3" />, variant: 'success' },
  embedding_similarity: { label: 'Embedding', icon: <Cpu className="h-3 w-3" />, variant: 'default' },
  embedding: { label: 'Embedding', icon: <Cpu className="h-3 w-3" />, variant: 'default' },
  llm: { label: 'LLM', icon: <Zap className="h-3 w-3" />, variant: 'warning' },
  uncorrelated: { label: 'Uncorrelated', icon: <Info className="h-3 w-3" />, variant: 'muted' },
  dynamic_cluster: { label: 'Dynamic', icon: <GitBranch className="h-3 w-3" />, variant: 'warning' },
};

const ROUTING_HINTS: Record<string, string> = {
  schema_suffix_lock: '_id / _code suffix detected',
  rapidfuzz_ontology: 'lexical ≥85% match',
  schema_ontology_lock: 'exact ontology keyword',
  embedding_similarity: 'bi-encoder cosine routing',
  embedding: 'Qdrant embedding match',
  llm: 'LLM fallback for low-confidence columns',
  uncorrelated: 'no domain above confidence floor',
  dynamic_cluster: 'agglomerative cluster fallback',
};

function confVariant(c?: number): 'success' | 'warning' | 'danger' | 'muted' {
  if (!c) return 'muted';
  if (c >= 0.75) return 'success';
  if (c >= 0.45) return 'warning';
  return 'danger';
}

function confBar(val: number, label: string, color: string) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-text-muted w-16 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.min(val * 100, 100)}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-[10px] font-mono text-text-muted w-7 text-right">
        {(val * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function normalizeDomainKey(name: string): string {
  return name.trim().toLowerCase();
}

function isUiDomainRegistry(value: unknown): value is DomainRegistry {
  if (!value || typeof value !== 'object') return false;
  const dr = value as DomainRegistry;
  return Boolean(dr.static_ontology || dr.dynamic_domains || dr.universal_domains);
}

function normalizeMappingRows(raw: AnalysisResult['semantic_mapping']): SemanticMappingRow[] {
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === 'object') {
    return Object.entries(raw as Record<string, unknown>).map(([column, meta]) => {
      if (meta && typeof meta === 'object') {
        return { column, ...(meta as SemanticMappingRow) };
      }
      return { column, domain: String(meta ?? '') };
    });
  }
  return [];
}

function columnsForDomain(
  domainKey: string,
  colsByDomain: Map<string, string[]>,
  spec?: { members?: string[]; columns?: string[] },
): string[] {
  const key = normalizeDomainKey(domainKey);
  const mapped = colsByDomain.get(key) ?? [];
  const members = [...(spec?.members ?? []), ...(spec?.columns ?? [])];
  const merged = [...mapped];
  for (const col of members) {
    if (col && !merged.includes(col)) merged.push(col);
  }
  return merged;
}

function StatTile({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: 'default' | 'success' | 'warning' | 'muted';
}) {
  const toneCls = {
    default: 'border-border bg-surface-card',
    success: 'border-success/30 bg-success/5',
    warning: 'border-warning/30 bg-warning/5',
    muted: 'border-border bg-surface/60',
  }[tone];

  return (
    <div className={cn('rounded-xl border px-4 py-3', toneCls)}>
      <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-text">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-text-muted">{sub}</p>}
    </div>
  );
}

function DomainRegistryPanel({
  registry,
  mappingRows,
  localOverrides,
}: {
  registry: DomainRegistry;
  mappingRows: SemanticMappingRow[];
  localOverrides: Record<string, string>;
}) {
  const [activeTab, setActiveTab] = useState<'static' | 'dynamic' | 'universal'>('static');
  const [expandedDomain, setExpandedDomain] = useState<string | null>(null);

  const colsByDomain = new Map<string, string[]>();
  for (const r of mappingRows) {
    const d = normalizeDomainKey(localOverrides[r.column] ?? r.domain ?? 'unknown');
    if (!colsByDomain.has(d)) colsByDomain.set(d, []);
    colsByDomain.get(d)!.push(r.column);
  }

  const archetype = registry.active_archetype ?? '—';
  const staticOntology = registry.static_ontology ?? {};
  const archetypeEntry = staticOntology[archetype];
  const rawStaticDomains = archetypeEntry?.domains?.length
    ? archetypeEntry.domains
    : Object.values(staticOntology).flatMap((e) => e.domains ?? []);
  const dynamicDomains = registry.dynamic_domains ?? {};
  const rawUniversalDomains = registry.universal_domains ?? [];

  const seen = new Set<string>();
  const staticDomains = rawStaticDomains.filter((d) => {
    if (seen.has(d)) return false;
    seen.add(d);
    return true;
  });
  const universalDomains = rawUniversalDomains.filter((d) => {
    if (seen.has(d)) return false;
    seen.add(d);
    return true;
  });

  const tabCls = (t: string) =>
    cn(
      'px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
      activeTab === t ? 'bg-accent text-white' : 'text-text-muted hover:text-text hover:bg-border/50',
    );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-text-muted">Active archetype</span>
        <Badge variant="default" className="uppercase tracking-wide">
          {archetype}
        </Badge>
        {archetypeEntry?.label && (
          <span className="text-xs text-text-muted italic">{archetypeEntry.label}</span>
        )}
      </div>

      <div className="flex gap-1 bg-border/20 rounded-lg p-1 flex-wrap">
        <button type="button" className={tabCls('static')} onClick={() => setActiveTab('static')}>
          Static ({staticDomains.length})
        </button>
        <button type="button" className={tabCls('dynamic')} onClick={() => setActiveTab('dynamic')}>
          Dynamic ({Object.keys(dynamicDomains).length})
        </button>
        <button type="button" className={tabCls('universal')} onClick={() => setActiveTab('universal')}>
          Universal ({universalDomains.length})
        </button>
      </div>

      <div className="max-h-[520px] overflow-y-auto space-y-1.5 pr-1">
        {activeTab === 'static' &&
          staticDomains.map((domain) => {
            const cols = columnsForDomain(domain, colsByDomain);
            const kwSample = archetypeEntry?.keywords_sample?.[domain];
            return (
              <div key={domain} className="rounded-lg border border-border overflow-hidden">
                <button
                  type="button"
                  onClick={() => setExpandedDomain(expandedDomain === domain ? null : domain)}
                  className={cn(
                    'w-full text-left px-3 py-2.5 text-sm flex items-center justify-between gap-2 transition-colors',
                    expandedDomain === domain
                      ? 'bg-accent/10 text-primary'
                      : 'hover:bg-border/40 text-text',
                  )}
                >
                  <span className="font-medium truncate">{domain}</span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {cols.length > 0 && <Badge variant="success">{cols.length}</Badge>}
                    <Database className="h-3.5 w-3.5 text-text-muted" />
                  </div>
                </button>
                {expandedDomain === domain && (
                  <div className="px-3 pb-3 bg-surface/50 space-y-2 border-t border-border/40">
                    {cols.length > 0 && (
                      <div>
                        <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">
                          Mapped columns
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {cols.map((c) => (
                            <span
                              key={c}
                              className="text-[10px] font-mono bg-accent/10 text-primary px-2 py-0.5 rounded"
                            >
                              {c}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {kwSample && (
                      <div>
                        <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">
                          Ontology keywords
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {kwSample.map((kw) => (
                            <span
                              key={kw}
                              className="text-[10px] font-mono bg-border/60 text-text-muted px-1.5 py-0.5 rounded"
                            >
                              {kw}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

        {activeTab === 'dynamic' &&
          (Object.keys(dynamicDomains).length === 0 ? (
            <p className="text-xs text-text-muted px-1 py-4 text-center">
              No dynamic domains for this run. Columns may all map to static ontology domains.
            </p>
          ) : (
            Object.entries(dynamicDomains).map(([key, spec]) => {
              const cols = columnsForDomain(key, colsByDomain, spec);
              return (
                <div
                  key={key}
                  className="rounded-lg border border-warning/30 bg-warning/5 overflow-hidden"
                >
                  <button
                    type="button"
                    onClick={() => setExpandedDomain(expandedDomain === key ? null : key)}
                    className="w-full text-left px-3 py-2.5 text-sm flex items-center justify-between gap-2"
                  >
                    <span className="font-mono text-xs text-warning truncate">{key}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {cols.length > 0 && <Badge variant="warning">{cols.length}</Badge>}
                      {spec.cohesion != null && (
                        <span className="text-[10px] text-text-muted">
                          cohesion {(spec.cohesion * 100).toFixed(0)}%
                        </span>
                      )}
                      <GitBranch className="h-3.5 w-3.5 text-warning" />
                    </div>
                  </button>
                  {expandedDomain === key && (
                    <div className="px-3 pb-3 space-y-2 border-t border-warning/20">
                      {spec.description && (
                        <p className="text-[10px] text-text-muted pt-2">{spec.description}</p>
                      )}
                      {spec.parent_theme && (
                        <p className="text-[10px] text-text-muted">
                          Parent theme: <strong className="text-text">{spec.parent_theme}</strong>
                        </p>
                      )}
                      {cols.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {cols.map((c) => (
                            <span
                              key={c}
                              className="text-[10px] font-mono bg-warning/10 text-warning px-2 py-0.5 rounded"
                            >
                              {c}
                            </span>
                          ))}
                        </div>
                      )}
                      {spec.keywords && spec.keywords.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {spec.keywords.map((kw) => (
                            <span
                              key={kw}
                              className="text-[10px] font-mono bg-border/60 text-text-muted px-1.5 py-0.5 rounded"
                            >
                              {kw}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          ))}

        {activeTab === 'universal' &&
          universalDomains.map((domain) => {
            const cols = columnsForDomain(domain, colsByDomain);
            return (
              <div
                key={domain}
                className="flex items-center justify-between px-3 py-2.5 rounded-lg border border-border hover:bg-border/30 transition-colors"
              >
                <span className="text-sm text-text">{domain}</span>
                {cols.length > 0 ? (
                  <Badge variant="default">{cols.length}</Badge>
                ) : (
                  <span className="text-xs text-text-muted">0</span>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}

export default function Step3Semantic({
  results,
  analysisId,
  overrides,
  effectiveSchema,
  normalizationVersion,
  onProceed,
  onBack,
}: Props) {
  const [domainsPayload, setDomainsPayload] = useState<DomainsPayload | null>(null);
  const [domainsLoading, setDomainsLoading] = useState(true);
  const [localOverrides, setLocalOverrides] = useState<Record<string, string>>(overrides);
  const [roleOverrides, setRoleOverrides] = useState<Record<string, 'identifier' | 'variable'>>({});
  const [rolesConfirmed, setRolesConfirmed] = useState(false);
  const [confirmingRoles, setConfirmingRoles] = useState(false);
  const [roleError, setRoleError] = useState<string | null>(null);
  const [showScores, setShowScores] = useState(false);
  const [mainView, setMainView] = useState<MainView>('columns');
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<RoleFilter>('all');
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all');
  const [legendOpen, setLegendOpen] = useState(false);

  useEffect(() => {
    setDomainsLoading(true);
    analysisApi
      .getDomains(analysisId)
      .then(setDomainsPayload)
      .finally(() => setDomainsLoading(false));
    analysisApi
      .getColumnRoles(analysisId)
      .then((payload) => setRolesConfirmed(Boolean(payload.column_roles_confirmed)))
      .catch(() => setRolesConfirmed(false));
  }, [analysisId]);

  const mappingRows: SemanticMappingRow[] = useMemo(
    () => normalizeMappingRows(results.semantic_mapping),
    [results.semantic_mapping],
  );
  const pipelineMeta = (results.meta ?? {}) as Record<string, unknown>;

  const baseRegistry: DomainRegistry = useMemo(() => {
    const fromDomainsApi = domainsPayload?.domain_registry;
    if (isUiDomainRegistry(fromDomainsApi)) {
      return fromDomainsApi;
    }
    if (isUiDomainRegistry(results.domain_registry)) {
      return results.domain_registry as DomainRegistry;
    }
    const archetype =
      domainsPayload?.ontology_macro_type_best_hint ??
      (results.dataset_context as { dataset_type?: string; usecase?: string } | undefined)
        ?.dataset_type ??
      (results.dataset_context as { usecase?: string } | undefined)?.usecase ??
      'unknown';
    const staticDomainKeys = Object.keys(domainsPayload?.static_domains_taxonomy ?? {});
    const universals = [
      'identifier',
      'survey_metadata',
      'geography',
      'demographic',
      'household',
      'uncorrelated_metadata',
    ];
    return {
      active_archetype: archetype,
      universal_domains: universals,
      static_ontology: staticDomainKeys.length
        ? {
            [archetype]: {
              label: archetype,
              domains: staticDomainKeys.filter((d) => !universals.includes(d)),
            },
          }
        : {},
      dynamic_domains: {},
    } as DomainRegistry;
  }, [domainsPayload, results.domain_registry, results.dataset_context]);

  const registry: DomainRegistry = useMemo(() => {
    const staticNames = new Set([
      ...Object.values(baseRegistry.static_ontology ?? {})
        .flatMap((e) => e.domains ?? [])
        .map(normalizeDomainKey),
      ...(baseRegistry.universal_domains ?? []).map(normalizeDomainKey),
    ]);
    const dynamic = { ...(baseRegistry.dynamic_domains ?? {}) };
    for (const row of mappingRows) {
      const domain = normalizeDomainKey(localOverrides[row.column] ?? row.domain ?? '');
      if (!domain || domain === 'uncorrelated') continue;
      const domainType = String((row as { domain_type?: string }).domain_type ?? '').toLowerCase();
      const source = String((row as { source?: string }).source ?? '').toLowerCase();
      const isDynamic = domainType === 'dynamic' || source === 'llm' || !staticNames.has(domain);
      if (!isDynamic) continue;
      const prev = dynamic[domain] ?? {};
      const members = [...(prev.members ?? [])];
      if (!members.includes(row.column)) members.push(row.column);
      dynamic[domain] = {
        ...prev,
        members,
        description: prev.description ?? `Dynamic domain: ${domain}`,
      };
    }
    return { ...baseRegistry, dynamic_domains: dynamic };
  }, [baseRegistry, mappingRows, localOverrides]);

  const allDomainNames = [
    ...Object.values(registry.static_ontology ?? {}).flatMap((e) => e.domains ?? []),
    ...Object.keys(registry.dynamic_domains ?? {}),
    ...(registry.universal_domains ?? []),
    ...mappingRows.map((r) => r.domain ?? ''),
  ]
    .filter(Boolean)
    .filter((v, i, a) => a.indexOf(v) === i);

  const handleRoleOverride = (column: string, role: string) => {
    setRoleOverrides((prev) => {
      if (role === '_pipeline') {
        const next = { ...prev };
        delete next[column];
        return next;
      }
      if (role === 'identifier' || role === 'variable') {
        return { ...prev, [column]: role };
      }
      return prev;
    });
  };

  const effectiveRole = (row: SemanticMappingRow): 'identifier' | 'variable' => {
    if (roleOverrides[row.column]) return roleOverrides[row.column];
    const role = row.analysis_role;
    return role === 'identifier' || role === 'variable' ? role : 'variable';
  };

  const identifierCount = mappingRows.filter((r) => effectiveRole(r) === 'identifier').length;
  const variableCount = mappingRows.filter((r) => effectiveRole(r) === 'variable').length;
  const overrideCount = Object.keys(localOverrides).length;
  const roleOverrideCount = Object.keys(roleOverrides).length;
  const lowConfidenceCount = mappingRows.filter((r) => (r.confidence ?? 0) < 0.45).length;

  const handleConfirmProceed = async () => {
    setConfirmingRoles(true);
    setRoleError(null);
    try {
      const mergedRoles: Record<string, 'identifier' | 'variable'> = {};
      for (const row of mappingRows) {
        mergedRoles[row.column] = effectiveRole(row);
      }
      await analysisApi.confirmColumnRoles(analysisId, mergedRoles);
      setRolesConfirmed(true);
      onProceed(localOverrides);
    } catch (err) {
      setRoleError(err instanceof Error ? err.message : 'Failed to confirm column roles');
    } finally {
      setConfirmingRoles(false);
    }
  };

  const handleOverride = (column: string, domain: string) => {
    setLocalOverrides((p) => {
      if (domain === '_original') {
        const n = { ...p };
        delete n[column];
        return n;
      }
      return { ...p, [column]: domain };
    });
  };

  const filteredRows = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return mappingRows.filter((row) => {
      const role = effectiveRole(row);
      if (roleFilter === 'identifier' && role !== 'identifier') return false;
      if (roleFilter === 'variable' && role !== 'variable') return false;

      const isOverridden = Boolean(localOverrides[row.column]);
      const conf = row.confidence ?? 0;
      if (reviewFilter === 'overridden' && !isOverridden && !roleOverrides[row.column]) return false;
      if (reviewFilter === 'low_confidence' && conf >= 0.45) return false;

      if (!q) return true;
      const effective = localOverrides[row.column] ?? row.domain ?? '';
      return (
        row.column.toLowerCase().includes(q) ||
        String(row.original_name ?? '').toLowerCase().includes(q) ||
        String(effective).toLowerCase().includes(q) ||
        String(row.matched_keyword ?? '').toLowerCase().includes(q)
      );
    });
  }, [mappingRows, searchQuery, roleFilter, reviewFilter, localOverrides, roleOverrides]);

  const viewTabCls = (view: MainView) =>
    cn(
      'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
      mainView === view
        ? 'bg-accent text-white shadow-sm'
        : 'text-text-muted hover:text-text hover:bg-border/40',
    );

  const filterChipCls = (active: boolean) =>
    cn(
      'rounded-full px-2.5 py-1 text-[11px] font-medium border transition-colors',
      active
        ? 'border-accent bg-accent/10 text-primary'
        : 'border-border text-text-muted hover:border-accent/40 hover:text-text',
    );

  return (
    <div className="space-y-5 pb-24">

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile label="Columns mapped" value={mappingRows.length} sub="semantic assignments" />
        <StatTile
          label="Identifiers"
          value={identifierCount}
          sub="validation skipped"
          tone="muted"
        />
        <StatTile
          label="Variables"
          value={variableCount}
          sub="rule validation eligible"
          tone="success"
        />
        <StatTile
          label="Needs review"
          value={lowConfidenceCount + overrideCount + roleOverrideCount}
          sub={`${lowConfidenceCount} low conf · ${overrideCount} domain · ${roleOverrideCount} role`}
          tone={lowConfidenceCount + overrideCount + roleOverrideCount > 0 ? 'warning' : 'default'}
        />
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex gap-1 rounded-xl border border-border bg-surface/60 p-1 w-fit">
          <button type="button" className={viewTabCls('columns')} onClick={() => setMainView('columns')}>
            <Table2 className="h-4 w-4" />
            Column review
          </button>
          <button type="button" className={viewTabCls('domains')} onClick={() => setMainView('domains')}>
            <BookOpen className="h-4 w-4" />
            Domain reference
          </button>
        </div>

        {mainView === 'columns' && (
          <div className="flex flex-1 flex-wrap items-center gap-2 lg:justify-end">
            <div className="relative min-w-[200px] flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search columns or domains…"
                className="w-full rounded-lg border border-border bg-surface py-2 pl-8 pr-3 text-xs text-text focus:outline-none focus:ring-2 focus:ring-accent/30"
              />
            </div>
            <label className="flex items-center gap-2 cursor-pointer select-none rounded-lg border border-border px-2.5 py-2">
              <input
                type="checkbox"
                checked={showScores}
                onChange={(e) => setShowScores(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border text-accent focus:ring-accent/40"
              />
              <span className="text-xs text-text-muted whitespace-nowrap">Score breakdown</span>
            </label>
            {(overrideCount > 0 || roleOverrideCount > 0) && (
              <button
                type="button"
                onClick={() => {
                  setLocalOverrides({});
                  setRoleOverrides({});
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-2 text-xs text-text-muted hover:text-danger hover:border-danger/40 transition-colors"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset overrides
              </button>
            )}
          </div>
        )}
      </div>

      {mainView === 'domains' ? (
        <Card
          title="Domain taxonomy"
          description="Static ontology, dynamic clusters, and universal domains available for this dataset archetype."
        >
          {domainsLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : (
            <DomainRegistryPanel
              registry={registry}
              mappingRows={mappingRows}
              localOverrides={localOverrides}
            />
          )}
        </Card>
      ) : (
        <Card className="overflow-hidden !p-0">
          <div className="border-b border-border px-5 py-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-text">Column mapping</h2>
                <p className="mt-0.5 text-sm text-text-muted">
                  {filteredRows.length} of {mappingRows.length} columns shown
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {rolesConfirmed ? (
                  <Badge variant="success" className="gap-1">
                    <CheckCircle2 className="h-3 w-3" />
                    Roles confirmed
                  </Badge>
                ) : (
                  <Badge variant="warning">Roles pending confirmation</Badge>
                )}
                {overrideCount > 0 && (
                  <Badge variant="warning">
                    {overrideCount} domain override{overrideCount > 1 ? 's' : ''}
                  </Badge>
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <span className="text-[10px] uppercase tracking-wide text-text-muted self-center mr-1">
                Role
              </span>
              {(['all', 'identifier', 'variable'] as RoleFilter[]).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={filterChipCls(roleFilter === f)}
                  onClick={() => setRoleFilter(f)}
                >
                  {f === 'all' ? 'All roles' : f === 'identifier' ? 'Identifiers' : 'Variables'}
                </button>
              ))}
              <span className="w-px h-5 bg-border self-center mx-1 hidden sm:block" />
              <span className="text-[10px] uppercase tracking-wide text-text-muted self-center mr-1">
                Focus
              </span>
              {(['all', 'low_confidence', 'overridden'] as ReviewFilter[]).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={filterChipCls(reviewFilter === f)}
                  onClick={() => setReviewFilter(f)}
                >
                  {f === 'all'
                    ? 'All'
                    : f === 'low_confidence'
                      ? 'Low confidence'
                      : 'Overridden'}
                </button>
              ))}
            </div>

            {roleError && (
              <div className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
                {roleError}
              </div>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[880px]">
              <thead className="sticky top-0 z-10 bg-surface-card border-b border-border">
                <tr>
                  {['Column', 'Domain assignment', 'Analysis role', 'Match quality', 'Actions'].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted bg-surface-card"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {filteredRows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-text-muted">
                      No columns match the current filters.
                    </td>
                  </tr>
                ) : (
                  filteredRows.map((row, rowIdx) => {
                    const effective = localOverrides[row.column] ?? row.domain ?? '—';
                    const isOverridden = !!localOverrides[row.column];
                    const conf = row.confidence ?? 0;
                    const clusterSupport = row.cluster_support ?? 0;
                    const graphConsistency = row.graph_consistency ?? 0;
                    const domainType = String(
                      (row as { domain_type?: string }).domain_type ??
                        (row.source === 'llm'
                          ? 'dynamic'
                          : row.source === 'embedding'
                            ? 'static'
                            : 'static'),
                    ).toLowerCase();
                    const role = effectiveRole(row);
                    const roleOverridden = Boolean(roleOverrides[row.column]);
                    const lowConf = conf > 0 && conf < 0.45;

                    return (
                      <tr
                        key={`mapping-${rowIdx}-${row.column}`}
                        className={cn(
                          'border-b border-border/30 transition-colors align-top',
                          isOverridden && 'bg-warning/5',
                          roleOverridden && 'ring-1 ring-inset ring-warning/20',
                          lowConf && !isOverridden && 'bg-danger/5',
                        )}
                      >
                        <td className="px-4 py-3.5 min-w-[140px]">
                          <div className="font-mono text-xs font-semibold text-text">{row.column}</div>
                          {row.original_name && row.original_name !== row.column && (
                            <div className="text-[10px] text-text-muted mt-0.5">
                              upload: {row.original_name}
                            </div>
                          )}
                          {row.matched_keyword && (
                            <div className="text-[10px] text-text-muted mt-0.5">
                              keyword: <span className="italic">{row.matched_keyword}</span>
                            </div>
                          )}
                        </td>

                        <td className="px-4 py-3.5 min-w-[180px]">
                          <div className="flex items-start gap-2">
                            <div className="min-w-0 flex-1">
                              <span
                                className={cn(
                                  'text-xs font-semibold block truncate',
                                  isOverridden ? 'text-warning' : 'text-primary',
                                )}
                              >
                                {effective}
                              </span>
                              {isOverridden && (
                                <span className="text-[10px] text-text-muted">
                                  was: {row.domain}
                                </span>
                              )}
                              <Badge
                                variant={domainType === 'dynamic' ? 'warning' : 'muted'}
                                className="mt-1.5 text-[10px]"
                              >
                                {domainType}
                              </Badge>
                            </div>
                          </div>
                        </td>

                        <td className="px-4 py-3.5 min-w-[160px]">
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <Badge
                                variant={role === 'identifier' ? 'muted' : 'default'}
                                className="text-[10px] shrink-0"
                              >
                                {role === 'identifier' ? (
                                  <span className="inline-flex items-center gap-1">
                                    <Fingerprint className="h-3 w-3" />
                                    Identifier
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1">
                                    <BarChart3 className="h-3 w-3" />
                                    Variable
                                  </span>
                                )}
                              </Badge>
                              {roleOverridden && (
                                <span className="text-[10px] text-warning">edited</span>
                              )}
                            </div>
                            {row.role_reason && (
                              <p
                                className="text-[10px] text-text-muted line-clamp-2"
                                title={row.role_reason}
                              >
                                {row.role_reason}
                              </p>
                            )}
                            <select
                              value={roleOverrides[row.column] ?? '_pipeline'}
                              onChange={(e) => handleRoleOverride(row.column, e.target.value)}
                              className="w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-[11px] text-text focus:outline-none focus:ring-2 focus:ring-accent/30"
                              aria-label={`Role for ${row.column}`}
                            >
                              <option value="_pipeline">
                                {row.analysis_role === 'identifier' || row.analysis_role === 'variable'
                                  ? `Pipeline: ${row.analysis_role}`
                                  : 'Pipeline default'}
                              </option>
                              <option value="identifier">Identifier</option>
                              <option value="variable">Variable</option>
                            </select>
                          </div>
                        </td>

                        <td className="px-4 py-3.5 min-w-[180px]">
                          <div className="space-y-2">
                            {showScores ? (
                              <div className="space-y-1">
                                {confBar(
                                  conf,
                                  'Ensemble',
                                  conf >= 0.75 ? '#22c55e' : conf >= 0.5 ? '#f59e0b' : '#ef4444',
                                )}
                                {confBar(clusterSupport, 'Cluster', '#14b8a6')}
                                {confBar(graphConsistency, 'Graph', '#6366f1')}
                              </div>
                            ) : (
                              <div className="flex items-center gap-2">
                                <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden max-w-[100px]">
                                  <div
                                    className={cn(
                                      'h-full rounded-full',
                                      conf >= 0.75
                                        ? 'bg-success'
                                        : conf >= 0.5
                                          ? 'bg-warning'
                                          : 'bg-danger',
                                    )}
                                    style={{ width: `${Math.min(conf * 100, 100)}%` }}
                                  />
                                </div>
                                <Badge variant={confVariant(conf)}>
                                  {conf > 0 ? `${(conf * 100).toFixed(0)}%` : '—'}
                                </Badge>
                              </div>
                            )}
                            {row.dynamic_cohesion != null && (
                              <p className="text-[10px] text-text-muted">
                                cohesion {(row.dynamic_cohesion * 100).toFixed(0)}%
                              </p>
                            )}
                            {lowConf && (
                              <p className="text-[10px] text-danger inline-flex items-center gap-1">
                                <AlertTriangle className="h-3 w-3" />
                                Low confidence — review domain
                              </p>
                            )}
                          </div>
                        </td>

                        <td className="px-4 py-3.5 min-w-[160px]">
                          <label className="block text-[10px] text-text-muted mb-1">
                            Override domain
                          </label>
                          <select
                            value={localOverrides[row.column] ?? '_original'}
                            onChange={(e) => handleOverride(row.column, e.target.value)}
                            className="w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-xs text-text focus:outline-none focus:ring-2 focus:ring-accent/30"
                          >
                            <option value="_original">{row.domain ?? '(pipeline assigned)'}</option>
                            {allDomainNames
                              .filter((d) => d !== row.domain)
                              .map((d) => (
                                <option key={d} value={d}>
                                  {d}
                                </option>
                              ))}
                          </select>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-border bg-surface-card/95 backdrop-blur supports-[backdrop-filter]:bg-surface-card/90">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <Button variant="ghost" onClick={onBack} className="flex items-center gap-1">
            <ChevronLeft className="h-4 w-4" /> Back to normalisation
          </Button>
          <div className="flex flex-wrap items-center gap-3">
            <span className="hidden sm:inline text-xs text-text-muted">
              {identifierCount} identifiers · {variableCount} variables
              {overrideCount > 0 && ` · ${overrideCount} domain overrides`}
            </span>
            <Button onClick={() => void handleConfirmProceed()} size="lg" disabled={confirmingRoles}>
              {confirmingRoles ? 'Confirming…' : 'Confirm roles & proceed →'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
