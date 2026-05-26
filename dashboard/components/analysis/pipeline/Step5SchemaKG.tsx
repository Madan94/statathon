'use client';

import { useEffect, useState } from 'react';
import { analysisApi, GraphPayload, GraphEdge } from '@/lib/api';
import type { AnalysisResult } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/Tabs';
import { cn } from '@/lib/cn';
import { ChevronLeft, ArrowRight, Download, GitBranch, Network, CheckCircle2 } from 'lucide-react';

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
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function edgeVariant(rel?: string): 'default' | 'success' | 'warning' | 'muted' {
  if (!rel) return 'muted';
  const r = rel.toLowerCase();
  if (r.includes('strong') || r.includes('direct')) return 'success';
  if (r.includes('weak') || r.includes('indirect')) return 'warning';
  return 'default';
}

export default function Step5SchemaKG({ results, analysisId, onProceed, onBack }: Props) {
  const [graphPayload, setGraphPayload] = useState<GraphPayload | null>(null);
  const [kgPayload, setKgPayload] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      analysisApi.getGraph(analysisId).catch(() => null),
      analysisApi.getKnowledgeGraph(analysisId).catch(() => null),
    ]).then(([g, kg]) => {
      if (g) setGraphPayload(g);
      if (kg) setKgPayload((kg as { knowledge_graph?: Record<string, unknown> }).knowledge_graph ?? null);
      setLoading(false);
    });
  }, [analysisId]);

  // Fall back to embedded data in results
  const edges: GraphEdge[] =
    (graphPayload?.edges as GraphEdge[] | undefined) ??
    (results.schema_graph?.edges as GraphEdge[] | undefined) ??
    [];
  const nodes =
    graphPayload?.nodes ??
    (results.schema_graph?.nodes as { name: string }[] | undefined) ??
    [];

  const kgData = kgPayload ?? {};

  return (
    <div className="space-y-6">
      <Tabs defaultValue="schema">
        <TabsList>
          <TabsTrigger value="schema">
            <GitBranch className="h-3.5 w-3.5 mr-1.5" aria-hidden />
            Schema graph
          </TabsTrigger>
          <TabsTrigger value="kg">
            <Network className="h-3.5 w-3.5 mr-1.5" aria-hidden />
            Knowledge graph
          </TabsTrigger>
        </TabsList>

        {/* ── Schema graph ── */}
        <TabsContent value="schema">
          <Card
            title={`Schema graph — ${nodes.length} nodes, ${edges.length} edges`}
            description="Column relationships inferred during semantic analysis. Edges encode dependency strength and type."
          >
            {loading ? (
              <div className="space-y-2">
                {[1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} className="h-10" />
                ))}
              </div>
            ) : edges.length === 0 ? (
              <p className="text-sm text-text-muted">No graph edges available.</p>
            ) : (
              <>
                <div className="overflow-x-auto -mx-6">
                  <table className="w-full text-sm min-w-[600px]">
                    <thead>
                      <tr className="border-b border-border">
                        {['Source', '', 'Target', 'Relationship', 'Weight', 'Reason'].map((h) => (
                          <th
                            key={h}
                            className="px-4 pb-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {edges.map((edge, i) => (
                        <tr
                          key={i}
                          className="border-b border-border/30 hover:bg-surface/60 transition-colors"
                        >
                          <td className="px-4 py-2.5 font-mono text-xs text-text font-medium">
                            {edge.source}
                          </td>
                          <td className="px-2 py-2.5 text-text-muted">
                            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                          </td>
                          <td className="px-4 py-2.5 font-mono text-xs text-text font-medium">
                            {edge.target}
                          </td>
                          <td className="px-4 py-2.5">
                            <Badge variant={edgeVariant(edge.relationship_type)}>
                              {edge.relationship_type ?? 'related'}
                            </Badge>
                          </td>
                          <td className="px-4 py-2.5 text-xs text-text-muted font-mono">
                            {edge.weight != null ? edge.weight.toFixed(3) : '—'}
                          </td>
                          <td className="px-4 py-2.5 text-xs text-text-muted max-w-[200px] truncate">
                            {edge.semantic_reason ?? '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-4 pt-4 border-t border-border flex justify-end">
                  <Button
                    variant="outline"
                    onClick={() => downloadJSON({ nodes, edges }, 'schema_graph.json')}
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <Download className="h-4 w-4" /> Export schema graph
                  </Button>
                </div>
              </>
            )}
          </Card>
        </TabsContent>

        {/* ── Knowledge graph ── */}
        <TabsContent value="kg">
          <Card
            title="Knowledge graph"
            description="Enriched ontology relationships, entity types and Neo4j sync summary."
          >
            {loading ? (
              <Skeleton className="h-40" />
            ) : Object.keys(kgData).length === 0 ? (
              <p className="text-sm text-text-muted">
                No knowledge graph data found. Neo4j sync may not be configured.
              </p>
            ) : (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                  {Object.entries(kgData)
                    .filter(([, v]) => typeof v !== 'object' || v === null)
                    .slice(0, 8)
                    .map(([k, v]) => (
                      <div key={k} className="rounded-lg border border-border p-3 bg-surface">
                        <p className="text-[10px] uppercase tracking-wide text-text-muted">
                          {k.replace(/_/g, ' ')}
                        </p>
                        <p className="mt-1 font-semibold text-text text-sm">{String(v)}</p>
                      </div>
                    ))}
                </div>

                <details>
                  <summary className="text-sm cursor-pointer text-primary hover:underline">
                    Full KG payload (JSON)
                  </summary>
                  <pre className="mt-3 max-h-64 overflow-auto rounded-lg bg-surface border border-border p-3 text-xs font-mono text-text-muted">
                    {JSON.stringify(kgData, null, 2)}
                  </pre>
                </details>

                <div className="mt-4 pt-4 border-t border-border flex justify-end">
                  <Button
                    variant="outline"
                    onClick={() => downloadJSON(kgData, 'knowledge_graph.json')}
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <Download className="h-4 w-4" /> Export KG
                  </Button>
                </div>
              </>
            )}
          </Card>
        </TabsContent>
      </Tabs>

      {/* Priority dependencies */}
      {results.priority_dependencies && (
        <Card
          title="Priority dependencies"
          description="High-confidence column dependencies surfaced by the semantic pipeline."
        >
          <pre className="max-h-40 overflow-auto rounded-lg bg-surface border border-border p-3 text-xs font-mono text-text-muted">
            {JSON.stringify(results.priority_dependencies, null, 2)}
          </pre>
        </Card>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button variant="ghost" onClick={onBack} className="flex items-center gap-1">
          <ChevronLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
          <span className="text-sm text-text-muted">Pipeline complete — verify columns</span>
          <Button onClick={onProceed} size="lg" className="gap-2">
            <Network className="h-4 w-4" aria-hidden />
            Proceed to Column Analysis →
          </Button>
        </div>
      </div>
    </div>
  );
}
