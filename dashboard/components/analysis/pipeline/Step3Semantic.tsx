'use client';

import { useEffect, useState } from 'react';
import { analysisApi, DomainsPayload, SemanticMappingRow, DomainRegistry } from '@/lib/api';
import type { AnalysisResult } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { ChevronLeft, CheckCircle2, Info, Zap, Database, GitBranch, Cpu } from 'lucide-react';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  overrides: Record<string, string>;
  effectiveSchema?: string[];
  normalizationVersion?: number | null;
  onProceed: (overrides: Record<string, string>) => void;
  onBack: () => void;
}

// ── Routing path helpers ──────────────────────────────────────────────────────
const ROUTING_LABELS: Record<string, { label: string; icon: React.ReactNode; variant: 'success' | 'default' | 'warning' | 'muted' }> = {
  schema_suffix_lock: { label: 'Suffix lock', icon: <Database className="h-3 w-3" />, variant: 'success' },
  rapidfuzz_ontology: { label: 'RapidFuzz', icon: <Zap className="h-3 w-3" />, variant: 'success' },
  schema_ontology_lock: { label: 'Ontology lock', icon: <Database className="h-3 w-3" />, variant: 'success' },
  embedding_similarity: { label: 'Embedding', icon: <Cpu className="h-3 w-3" />, variant: 'default' },
  dynamic_cluster: { label: 'Dynamic', icon: <GitBranch className="h-3 w-3" />, variant: 'warning' },
};

function routingInfo(method?: string) {
  if (!method) return ROUTING_LABELS.embedding_similarity;
  return ROUTING_LABELS[method] ?? { label: method.replace(/_/g, ' '), icon: <Cpu className="h-3 w-3" />, variant: 'muted' as const };
}

function confVariant(c?: number): 'success' | 'warning' | 'danger' | 'muted' {
  if (!c) return 'muted';
  if (c >= 0.75) return 'success';
  if (c >= 0.45) return 'warning';
  return 'danger';
}

function confBar(val: number, label: string, color: string) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-text-muted w-20 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(val * 100, 100)}%`, backgroundColor: color }} />
      </div>
      <span className="text-[10px] font-mono text-text-muted w-7 text-right">{(val * 100).toFixed(0)}%</span>
    </div>
  );
}

// ── Domain registry panel ─────────────────────────────────────────────────────
function DomainRegistryPanel({ registry, mappingRows, localOverrides }: {
  registry: DomainRegistry;
  mappingRows: SemanticMappingRow[];
  localOverrides: Record<string, string>;
}) {
  const [activeTab, setActiveTab] = useState<'static' | 'dynamic' | 'universal'>('static');
  const [expandedDomain, setExpandedDomain] = useState<string | null>(null);

  const colsByDomain = new Map<string, string[]>();
  for (const r of mappingRows) {
    const d = localOverrides[r.column] ?? r.domain ?? 'unknown';
    if (!colsByDomain.has(d)) colsByDomain.set(d, []);
    colsByDomain.get(d)!.push(r.column);
  }

  const archetype = registry.active_archetype ?? '—';
  const staticOntology = registry.static_ontology ?? {};
  const archetypeEntry = staticOntology[archetype];
  const rawStaticDomains = archetypeEntry?.domains?.length
    ? archetypeEntry.domains
    : Object.values(staticOntology).flatMap(e => e.domains ?? []);
  const dynamicDomains = registry.dynamic_domains ?? {};
  const rawUniversalDomains = registry.universal_domains ?? [];

  // Deduplicate across tabs so the same domain key never appears twice in any list
  const seen = new Set<string>();
  const staticDomains = rawStaticDomains.filter(d => { if (seen.has(d)) return false; seen.add(d); return true; });
  const universalDomains = rawUniversalDomains.filter(d => { if (seen.has(d)) return false; seen.add(d); return true; });

  const tabCls = (t: string) => cn(
    'px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
    activeTab === t ? 'bg-accent text-white' : 'text-text-muted hover:text-text hover:bg-border/50'
  );

  return (
    <div className="space-y-3">
      {/* Archetype badge */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-text-muted">Active archetype:</span>
        <Badge variant="default" className="uppercase tracking-wide">{archetype}</Badge>
        {archetypeEntry?.label && (
          <span className="text-xs text-text-muted italic">{archetypeEntry.label}</span>
        )}
      </div>

      {/* Tab selector */}
      <div className="flex gap-1 bg-border/20 rounded-lg p-1">
        <button className={tabCls('static')} onClick={() => setActiveTab('static')}>
          Static ontology ({staticDomains.length})
        </button>
        <button className={tabCls('dynamic')} onClick={() => setActiveTab('dynamic')}>
          Dynamic ({Object.keys(dynamicDomains).length})
        </button>
        <button className={tabCls('universal')} onClick={() => setActiveTab('universal')}>
          Universal ({universalDomains.length})
        </button>
      </div>

      <div className="max-h-[420px] overflow-y-auto space-y-1 pr-1">
        {activeTab === 'static' && staticDomains.map((domain) => {
          const cols = colsByDomain.get(domain) ?? [];
          const kwSample = archetypeEntry?.keywords_sample?.[domain];
          return (
            <div key={domain} className="rounded-lg border border-border overflow-hidden">
              <button
                type="button"
                onClick={() => setExpandedDomain(expandedDomain === domain ? null : domain)}
                className={cn('w-full text-left px-3 py-2 text-sm flex items-center justify-between gap-2 transition-colors',
                  expandedDomain === domain ? 'bg-accent/10 text-primary' : 'hover:bg-border/40 text-text')}
              >
                <span className="font-medium truncate">{domain}</span>
                <div className="flex items-center gap-1.5 shrink-0">
                  {cols.length > 0 && <Badge variant="success">{cols.length}</Badge>}
                  <Database className="h-3.5 w-3.5 text-text-muted" />
                </div>
              </button>
              {expandedDomain === domain && (
                <div className="px-3 pb-3 bg-surface/50 space-y-2">
                  {cols.length > 0 && (
                    <div>
                      <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">Mapped columns</p>
                      <div className="flex flex-wrap gap-1">
                        {cols.map(c => <span key={c} className="text-[10px] font-mono bg-accent/10 text-primary px-2 py-0.5 rounded">{c}</span>)}
                      </div>
                    </div>
                  )}
                  {kwSample && (
                    <div>
                      <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">Ontology keywords</p>
                      <div className="flex flex-wrap gap-1">
                        {kwSample.map(kw => <span key={kw} className="text-[10px] font-mono bg-border/60 text-text-muted px-1.5 py-0.5 rounded">{kw}</span>)}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {activeTab === 'dynamic' && (Object.keys(dynamicDomains).length === 0 ? (
          <p className="text-xs text-text-muted px-1 py-3">No dynamic domains generated (all columns matched static ontology).</p>
        ) : Object.entries(dynamicDomains).map(([key, spec]) => {
          const cols = spec.members ?? [];
          return (
            <div key={key} className="rounded-lg border border-warning/30 bg-warning/5 overflow-hidden">
              <button
                type="button"
                onClick={() => setExpandedDomain(expandedDomain === key ? null : key)}
                className="w-full text-left px-3 py-2 text-sm flex items-center justify-between gap-2"
              >
                <span className="font-mono text-xs text-warning truncate">{key}</span>
                <div className="flex items-center gap-1.5 shrink-0">
                  {spec.cohesion != null && (
                    <span className="text-[10px] text-text-muted">cohesion {(spec.cohesion * 100).toFixed(0)}%</span>
                  )}
                  <GitBranch className="h-3.5 w-3.5 text-warning" />
                </div>
              </button>
              {expandedDomain === key && (
                <div className="px-3 pb-3 space-y-2">
                  <p className="text-[10px] text-text-muted">Parent theme: <strong className="text-text">{spec.parent_theme}</strong></p>
                  {cols.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {cols.map(c => <span key={c} className="text-[10px] font-mono bg-warning/10 text-warning px-2 py-0.5 rounded">{c}</span>)}
                    </div>
                  )}
                  {spec.keywords && spec.keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {spec.keywords.map(kw => <span key={kw} className="text-[10px] font-mono bg-border/60 text-text-muted px-1.5 py-0.5 rounded">{kw}</span>)}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        }))}

        {activeTab === 'universal' && universalDomains.map((domain) => {
          const cols = colsByDomain.get(domain) ?? [];
          return (
            <div key={domain} className="flex items-center justify-between px-3 py-2 rounded-lg border border-border hover:bg-border/30 transition-colors">
              <span className="text-sm text-text">{domain}</span>
              {cols.length > 0 ? <Badge variant="default">{cols.length}</Badge> : <span className="text-xs text-text-muted">0</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
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
  const [showScores, setShowScores] = useState(false);

  useEffect(() => {
    if (results.domain_registry) {
      setDomainsLoading(false);
      return;
    }
    analysisApi.getDomains(analysisId).then(setDomainsPayload).finally(() => setDomainsLoading(false));
  }, [analysisId, results.domain_registry]);

  const mappingRows: SemanticMappingRow[] = results.semantic_mapping ?? [];

  // Prefer domain_registry from: 1) enriched results, 2) domains API response
  const registry: DomainRegistry =
    results.domain_registry ??
    domainsPayload?.domain_registry ??
    (() => {
      // Fallback: build minimal registry from whatever is available
      const archetype =
        domainsPayload?.ontology_macro_type_best_hint ??
        (results.dataset_context as { dataset_type?: string } | undefined)?.dataset_type ??
        'unknown';
      const staticDomainKeys = Object.keys(domainsPayload?.static_domains_taxonomy ?? {});
      const universals = ['identifier', 'survey_metadata', 'geography', 'demographic', 'household', 'uncorrelated_metadata'];
      return {
        active_archetype: archetype,
        universal_domains: universals,
        static_ontology: staticDomainKeys.length ? {
          [archetype]: {
            label: archetype,
            domains: staticDomainKeys.filter(d => !universals.includes(d)),
          }
        } : {},
        dynamic_domains: {},
      } as DomainRegistry;
    })();

  // Flat domain name list for the Override dropdown
  const allDomainNames = [
    ...Object.values(registry.static_ontology ?? {}).flatMap(e => e.domains ?? []),
    ...Object.keys(registry.dynamic_domains ?? {}),
    ...(registry.universal_domains ?? []),
    ...mappingRows.map(r => r.domain ?? ''),
  ].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i);

  const overrideCount = Object.keys(localOverrides).length;

  const handleOverride = (column: string, domain: string) => {
    setLocalOverrides((p) => {
      if (domain === '_original') { const n = { ...p }; delete n[column]; return n; }
      return { ...p, [column]: domain };
    });
  };

  return (
    <div className="space-y-6">
      {effectiveSchema && effectiveSchema.length > 0 && (
        <Card className="border-success/30 bg-success/5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <CheckCircle2 className="h-4 w-4 text-success shrink-0" />
            <span className="text-text">
              Using approved normalisation
              {normalizationVersion != null ? ` (v${normalizationVersion})` : ''} —{' '}
              <strong>{effectiveSchema.length}</strong> active columns:
            </span>
            {effectiveSchema.map((col, idx) => (
              <Badge key={`schema-col-${idx}-${col}`} variant="success" className="font-mono text-[10px]">
                {col}
              </Badge>
            ))}
          </div>
        </Card>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Domain registry */}
        <Card title="Domain taxonomy" description="All available statistical domains — static ontology + dynamic clusters generated this run." className="lg:col-span-1 h-fit">
          {domainsLoading && !results.domain_registry ? (
            <div className="space-y-2">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-8" />)}</div>
          ) : (
            <DomainRegistryPanel
              registry={registry}
              mappingRows={mappingRows}
              localOverrides={localOverrides}
            />
          )}
        </Card>

        {/* Right: Column → domain mapping */}
        <Card
          title="Column → domain mapping"
          description="Pipeline-assigned domains with routing path, confidence scores, and override controls."
          className="lg:col-span-2"
        >
          {overrideCount > 0 && (
            <div className="mb-3 flex items-center gap-2">
              <Badge variant="warning">{overrideCount} manual override{overrideCount > 1 ? 's' : ''}</Badge>
              <button type="button" onClick={() => setLocalOverrides({})} className="text-xs text-text-muted hover:text-danger transition-colors">
                Reset all
              </button>
            </div>
          )}
          <div className="mb-3 flex items-center gap-2">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showScores}
                onChange={e => setShowScores(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border text-accent focus:ring-accent/40"
              />
              <span className="text-xs text-text-muted">Show ensemble score breakdown</span>
            </label>
          </div>

          <div className="overflow-x-auto -mx-6">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-border">
                  {['Column', 'Domain', 'Routing path', 'Confidence', 'Override'].map((h) => (
                    <th key={h} className="px-4 pb-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {mappingRows.map((row, rowIdx) => {
                  const effective = localOverrides[row.column] ?? row.domain ?? '—';
                  const isOverridden = !!localOverrides[row.column];
                  const info = routingInfo(row.routing_path ?? (row.explainability as { match_method?: string } | undefined)?.match_method);
                  const conf = row.confidence ?? 0;
                  const clusterSupport = row.cluster_support ?? 0;
                  const graphConsistency = row.graph_consistency ?? 0;
                  return (
                    <tr key={`mapping-${rowIdx}-${row.column}`} className={cn('border-b border-border/30 hover:bg-surface/60 transition-colors align-top', isOverridden && 'bg-warning/5')}>
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs font-medium text-text">{row.column}</div>
                        {row.matched_keyword && (
                          <div className="text-[10px] text-text-muted mt-0.5">kw: <span className="italic">{row.matched_keyword}</span></div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn('text-xs font-semibold', isOverridden ? 'text-warning' : 'text-primary')}>
                          {effective}
                        </span>
                        {isOverridden && (
                          <div className="text-[10px] text-text-muted mt-0.5">was: {row.domain}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={info.variant} className="flex items-center gap-1 w-fit text-[10px]">
                          {info.icon}
                          {info.label}
                        </Badge>
                        {row.dynamic_cohesion != null && (
                          <div className="text-[10px] text-text-muted mt-0.5">cohesion {(row.dynamic_cohesion * 100).toFixed(0)}%</div>
                        )}
                      </td>
                      <td className="px-4 py-3 min-w-[140px]">
                        {showScores ? (
                          <div className="space-y-1">
                            {confBar(conf, 'Ensemble', conf >= 0.75 ? '#22c55e' : conf >= 0.5 ? '#f59e0b' : '#ef4444')}
                            {confBar(clusterSupport, 'Cluster', '#14b8a6')}
                            {confBar(graphConsistency, 'Graph', '#6366f1')}
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <div className="w-14 h-1.5 rounded-full bg-border overflow-hidden">
                              <div
                                className={cn('h-full rounded-full', conf >= 0.75 ? 'bg-success' : conf >= 0.5 ? 'bg-warning' : 'bg-danger')}
                                style={{ width: `${(conf * 100).toFixed(0)}%` }}
                              />
                            </div>
                            <Badge variant={confVariant(conf)}>
                              {conf > 0 ? `${(conf * 100).toFixed(0)}%` : '—'}
                            </Badge>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <select
                          value={localOverrides[row.column] ?? '_original'}
                          onChange={(e) => handleOverride(row.column, e.target.value)}
                          className="rounded border border-border bg-surface px-2 py-1 text-xs text-text focus:outline-none focus:ring-2 focus:ring-accent/30"
                        >
                          <option value="_original">{row.domain ?? '(pipeline assigned)'}</option>
                          {allDomainNames.filter((d) => d !== row.domain).map((d) => (
                            <option key={d} value={d}>{d}</option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Routing path legend */}
          <div className="mt-4 pt-3 border-t border-border">
            <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Routing path legend</p>
            <div className="flex flex-wrap gap-3">
              {Object.entries(ROUTING_LABELS).map(([key, { label, icon, variant }]) => (
                <div key={key} className="flex items-center gap-1.5">
                  <Badge variant={variant} className="flex items-center gap-1 text-[10px]">{icon}{label}</Badge>
                  <span className="text-[10px] text-text-muted">
                    {key === 'schema_suffix_lock' && '→ _id / _code suffix detected'}
                    {key === 'rapidfuzz_ontology' && '→ lexical ≥85% match'}
                    {key === 'schema_ontology_lock' && '→ exact ontology keyword'}
                    {key === 'embedding_similarity' && '→ bi-encoder cosine routing'}
                    {key === 'dynamic_cluster' && '→ agglomerative cluster fallback'}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 flex items-start gap-2 text-xs text-text-muted">
            <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>{mappingRows.length} columns mapped · {overrideCount} manually overridden. All changes are audit-logged as human-reviewed decisions.</span>
          </div>
        </Card>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button variant="ghost" onClick={onBack} className="flex items-center gap-1">
          <ChevronLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
          <span className="text-sm text-text-muted">{mappingRows.length} columns mapped{overrideCount > 0 && `, ${overrideCount} overridden`}</span>
          <Button onClick={() => onProceed(localOverrides)} size="lg">Confirm Mapping & Proceed to Clustering →</Button>
        </div>
      </div>
    </div>
  );
}
