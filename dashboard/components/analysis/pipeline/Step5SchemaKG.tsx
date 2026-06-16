'use client';

import { useEffect, useMemo, useState } from 'react';
import { analysisApi, GraphPayload, GraphEdge } from '@/lib/api';
import type { AnalysisResult } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import GraphCanvas, { GraphNode, GraphEdge as GEdge } from '@/components/ui/GraphCanvas';
import { cn } from '@/lib/cn';
import { normalizeSchemaGraphEdges, resolveOwlType } from '@/lib/schemaGraph';
import {
  ChevronLeft, ArrowRight, Download, Network,
  CheckCircle2, Table2, Layers,
} from 'lucide-react';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  onProceed: () => void;
  onBack: () => void;
}

function downloadJSON(obj: unknown, name: string) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}

// OWL relationship metadata
const OWL_META: Record<string, { label: string; color: string; description: string; variant: 'default' | 'success' | 'warning' | 'muted' }> = {
  'owl:equivalentProperty': { label: 'owl:equivalentProperty', color: '#6366f1', description: 'Equivalent statistical measures within the same domain', variant: 'default' },
  'owl:ObjectProperty': { label: 'owl:ObjectProperty', color: '#14b8a6', description: 'Cross-domain or semantic object relationship', variant: 'success' },
  'rdfs:subPropertyOf': { label: 'rdfs:subPropertyOf', color: '#8b5cf6', description: 'Hierarchical sub-property within same domain', variant: 'default' },
  'rdfs:seeAlso': { label: 'rdfs:seeAlso', color: '#94a3b8', description: 'Related statistical variable — informational link', variant: 'muted' },
};

function owlBadge(owlType?: string) {
  const meta = OWL_META[owlType ?? ''] ?? { label: owlType ?? '—', color: '#64748b', variant: 'muted' as const };
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono border',
      meta.variant === 'default' ? 'bg-indigo-50 border-indigo-200 text-indigo-700' :
      meta.variant === 'success' ? 'bg-teal-50 border-teal-200 text-teal-700' :
      meta.variant === 'muted' ? 'bg-slate-50 border-slate-200 text-slate-500' :
      'bg-purple-50 border-purple-200 text-purple-700'
    )}>
      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: meta.color }} />
      {meta.label}
    </span>
  );
}

function relBadge(rel?: string) {
  const r = rel?.toLowerCase() ?? '';
  const variant: 'default' | 'success' | 'warning' | 'muted' =
    r.includes('intra') ? 'default' : r.includes('co_cluster') ? 'success' : r.includes('cross') ? 'warning' : 'muted';
  return <Badge variant={variant}>{rel ?? 'related'}</Badge>;
}

function buildDomainMap(results: AnalysisResult): Map<string, string> {
  const m = new Map<string, string>();
  for (const row of results.semantic_mapping ?? []) {
    if (row.column && row.domain) m.set(String(row.column), String(row.domain));
  }
  return m;
}

// ── Blueprint grouped schema table ────────────────────────────────────────────
function BlueprintTable({ edges, domainMap }: { edges: GraphEdge[]; domainMap: Map<string, string> }) {
  const groups = useMemo(() => {
    const byType: Record<string, GraphEdge[]> = {};
    for (const e of edges) {
      const key = resolveOwlType(e);
      byType[key] = [...(byType[key] ?? []), e];
    }
    return byType;
  }, [edges]);

  const groupOrder = ['owl:equivalentProperty', 'rdfs:subPropertyOf', 'owl:ObjectProperty', 'rdfs:seeAlso'];
  const orderedKeys = [
    ...groupOrder.filter(k => groups[k]),
    ...Object.keys(groups).filter(k => !groupOrder.includes(k)),
  ];

  return (
    <div className="space-y-6">
      {orderedKeys.map((owlKey) => {
        const groupEdges = groups[owlKey] ?? [];
        const meta = OWL_META[owlKey] ?? { label: owlKey, description: '', color: '#64748b' };
        return (
          <div key={owlKey} className="rounded-xl border border-border overflow-hidden">
            {/* Group header */}
            <div className="flex items-start gap-3 px-5 py-3 bg-surface border-b border-border">
              <div className="w-3 h-3 rounded-full mt-1 shrink-0" style={{ backgroundColor: meta.color }} />
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs font-semibold text-text">{meta.label}</span>
                  <Badge variant="muted">{groupEdges.length} relation{groupEdges.length !== 1 ? 's' : ''}</Badge>
                </div>
                {'description' in meta && (
                  <p className="text-xs text-text-muted mt-0.5">{meta.description}</p>
                )}
              </div>
            </div>
            {/* Edges in this group */}
            <div className="divide-y divide-border/40">
              {groupEdges.map((edge, i) => {
                const sd = edge.source_domain || domainMap.get(edge.source);
                const td = edge.target_domain || domainMap.get(edge.target);
                return (
                  <div key={i} className="flex items-center gap-4 px-5 py-2.5 hover:bg-surface/60 transition-colors">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <span className="font-mono text-xs font-medium text-text truncate">{edge.source}</span>
                      {sd && <span className="text-[10px] text-text-muted">({sd})</span>}
                      <ArrowRight className="h-3.5 w-3.5 text-text-muted shrink-0" />
                      <span className="font-mono text-xs font-medium text-text truncate">{edge.target}</span>
                      {td && <span className="text-[10px] text-text-muted">({td})</span>}
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-[11px] text-text-muted font-mono">
                        w={edge.weight?.toFixed(3) ?? '—'}
                      </span>
                      <p className="text-[10px] text-text-muted max-w-[200px] truncate hidden xl:block">
                        {edge.semantic_reason ?? '—'}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Step5SchemaKG({ results, analysisId, onProceed, onBack }: Props) {
  const [graphPayload, setGraphPayload] = useState<GraphPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [schemaView, setSchemaView] = useState<'graph' | 'blueprint' | 'table'>('graph');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    analysisApi
      .getGraph(analysisId)
      .then((g) => {
        if (!cancelled && g?.edges?.length) setGraphPayload(g);
      })
      .catch(() => null)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId]);

  const domainMap = buildDomainMap(results);
  const edges: GraphEdge[] = useMemo(() => {
    const raw =
      (graphPayload?.edges as GraphEdge[] | undefined) ??
      (results.schema_graph?.edges as GraphEdge[] | undefined) ??
      [];
    return normalizeSchemaGraphEdges(raw, domainMap);
  }, [graphPayload?.edges, results.schema_graph?.edges, domainMap]);
  const schemaNodes = useMemo(() => {
    const nodeDomainFromPayload = new Map<string, string>();
    for (const n of graphPayload?.nodes ?? []) {
      const name = typeof n.name === 'string' ? n.name : undefined;
      const domain = typeof n.domain === 'string' ? n.domain : undefined;
      if (name && domain) nodeDomainFromPayload.set(name, domain);
    }
    const ids = new Set<string>();
    for (const e of edges) {
      ids.add(e.source);
      ids.add(e.target);
    }
    return [...ids].map((id) => ({
      id,
      domain: nodeDomainFromPayload.get(id) ?? domainMap.get(id),
      label: id,
    }));
  }, [edges, domainMap, graphPayload?.nodes]);

  const schemaEdgesForGraph: GEdge[] = edges.map(e => ({
    source: e.source,
    target: e.target,
    weight: e.weight,
    relationship_type: e.relationship_type,
    semantic_reason: e.semantic_reason,
  }));

  const owlTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of edges) {
      const k = resolveOwlType(e);
      counts[k] = (counts[k] ?? 0) + 1;
    }
    return counts;
  }, [edges]);

  return (
    <div className="space-y-6">
      <Card
        title={`Schema graph — ${schemaNodes.length} nodes, ${edges.length} edges`}
        description="Column relationships inferred during semantic analysis — typed with OWL/RDF ontology terms."
      >
            {loading ? <Skeleton className="h-[520px]" /> : edges.length === 0 ? (
              <p className="text-sm text-text-muted">No graph edges available.</p>
            ) : (
              <>
                {/* View toggle */}
                <div className="flex gap-2 mb-4">
                  <button onClick={() => setSchemaView('graph')} className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border', schemaView === 'graph' ? 'bg-accent text-white border-accent' : 'border-border text-text-muted hover:bg-border/50')}>
                    <Network className="h-3.5 w-3.5" /> Graph
                  </button>
                  <button onClick={() => setSchemaView('blueprint')} className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border', schemaView === 'blueprint' ? 'bg-accent text-white border-accent' : 'border-border text-text-muted hover:bg-border/50')}>
                    <Layers className="h-3.5 w-3.5" /> Blueprint
                  </button>
                  <button onClick={() => setSchemaView('table')} className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border', schemaView === 'table' ? 'bg-accent text-white border-accent' : 'border-border text-text-muted hover:bg-border/50')}>
                    <Table2 className="h-3.5 w-3.5" /> Table
                  </button>
                </div>

                {schemaView === 'graph' && <GraphCanvas nodes={schemaNodes} edges={schemaEdgesForGraph} height={520} />}

                {schemaView === 'blueprint' && <BlueprintTable edges={edges} domainMap={domainMap} />}

                {schemaView === 'table' && (
                  <div className="overflow-x-auto -mx-6">
                    <table className="w-full text-sm min-w-[700px]">
                      <thead>
                        <tr className="border-b border-border">
                          {['Source', '', 'Target', 'OWL type', 'Rel. type', 'Weight', 'Reason'].map(h => (
                            <th key={h} className="px-4 pb-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {edges.map((edge, i) => (
                          <tr key={i} className="border-b border-border/30 hover:bg-surface/60">
                            <td className="px-4 py-2.5 font-mono text-xs font-medium">{edge.source}</td>
                            <td className="px-2"><ArrowRight className="h-3.5 w-3.5 text-text-muted" /></td>
                            <td className="px-4 py-2.5 font-mono text-xs font-medium">{edge.target}</td>
                            <td className="px-4 py-2.5">{owlBadge(resolveOwlType(edge))}</td>
                            <td className="px-4 py-2.5">{relBadge(edge.relationship_type)}</td>
                            <td className="px-4 py-2.5 text-xs font-mono text-text-muted">{edge.weight?.toFixed(3) ?? '—'}</td>
                            <td className="px-4 py-2.5 text-xs text-text-muted max-w-[180px] truncate">{edge.semantic_reason ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <div className="mt-4 pt-4 border-t border-border flex flex-wrap items-center justify-between gap-3">
                  {/* OWL type summary */}
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(owlTypeCounts).map(([k, c]) => (
                      <div key={k} className="flex items-center gap-1.5 text-xs">
                        <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: OWL_META[k]?.color ?? '#64748b' }} />
                        <span className="font-mono text-text-muted">{OWL_META[k]?.label ?? k}</span>
                        <span className="text-text-muted">×{c}</span>
                      </div>
                    ))}
                  </div>
                  <Button variant="outline" onClick={() => downloadJSON({ nodes: schemaNodes, edges }, 'schema_graph.json')} className="flex items-center gap-1.5 text-sm">
                    <Download className="h-4 w-4" /> Export
                  </Button>
                </div>
              </>
            )}
      </Card>

      {!loading && edges.length > 0 && (
        <Card title="OWL / RDF relationship ontology" className="mt-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Object.entries(OWL_META).map(([k, m]) => (
              <div key={k} className="flex items-start gap-3 p-3 rounded-lg bg-surface border border-border">
                <div className="w-3 h-3 rounded-full mt-0.5 shrink-0" style={{ backgroundColor: m.color }} />
                <div>
                  <p className="font-mono text-xs font-semibold text-text">{m.label}</p>
                  <p className="text-[11px] text-text-muted mt-0.5">{m.description}</p>
                </div>
                <span className="ml-auto text-[11px] font-mono text-text-muted shrink-0">×{owlTypeCounts[k] ?? 0}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button variant="ghost" onClick={onBack} className="flex items-center gap-1">
          <ChevronLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" />
          <span className="text-sm text-text-muted">Schema graph verified</span>
          <Button onClick={onProceed} size="lg" className="gap-2">
            <Network className="h-4 w-4" />
            Proceed to rule validation →
          </Button>
        </div>
      </div>
    </div>
  );
}
