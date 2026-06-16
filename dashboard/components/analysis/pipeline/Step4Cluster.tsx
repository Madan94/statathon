'use client';

import { useEffect, useState } from 'react';
import { analysisApi, ClustersPayload, ClusterGroup } from '@/lib/api';
import type { AnalysisResult } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { formatDistributionPct, normalizeClusterGroup, normalizeDomainDistribution, clusterScoreBarValue } from '@/lib/clusterUtils';
import { ChevronLeft, Layers, CheckCircle2, Info } from 'lucide-react';

interface ExtendedCluster extends ClusterGroup {
  embedding_coherence?: number;
  domain_purity?: number;
  avg_domain_confidence?: number;
}

function miniBar(val: number, label: string, color: string) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] opacity-70 w-[72px] shrink-0">{label}</span>
      <div className="flex-1 h-1 rounded-full bg-black/20 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.min(val * 100, 100)}%`, backgroundColor: color }} />
      </div>
      <span className="text-[10px] font-mono opacity-70 w-7 text-right">{(val * 100).toFixed(0)}</span>
    </div>
  );
}

interface Props {
  results: AnalysisResult;
  analysisId: number;
  onProceed: () => void;
  onBack: () => void;
}

const CLUSTER_COLORS = [
  'bg-blue-500/15 border-blue-500/30 text-blue-700',
  'bg-purple-500/15 border-purple-500/30 text-purple-700',
  'bg-green-500/15 border-green-500/30 text-green-700',
  'bg-orange-500/15 border-orange-500/30 text-orange-700',
  'bg-pink-500/15 border-pink-500/30 text-pink-700',
  'bg-teal-500/15 border-teal-500/30 text-teal-700',
  'bg-indigo-500/15 border-indigo-500/30 text-indigo-700',
  'bg-amber-500/15 border-amber-500/30 text-amber-700',
];

function scoreBar(score: number | null | undefined, fallback = 0) {
  const val = clusterScoreBarValue(score, fallback);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-border overflow-hidden">
        {score != null && Number.isFinite(Number(score)) ? (
          <div
            className={cn(
              'h-full rounded-full',
              val >= 0.7 ? 'bg-success' : val >= 0.4 ? 'bg-warning' : 'bg-danger'
            )}
            style={{ width: `${Math.min(val * 100, 100)}%` }}
          />
        ) : (
          <div className="h-full w-0" />
        )}
      </div>
      <span className="text-xs font-mono text-text-muted w-8 text-right">
        {score != null && Number.isFinite(Number(score)) ? (val * 100).toFixed(0) : '—'}
      </span>
    </div>
  );
}

export default function Step4Cluster({ results, analysisId, onProceed, onBack }: Props) {
  const [payload, setPayload] = useState<ClustersPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    analysisApi
      .getClusters(analysisId)
      .then((data) => {
        if (!cancelled) setPayload(data);
      })
      .catch(() => {
        if (!cancelled) setPayload(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId]);

  const rawClusters = (
    payload?.clusters?.length
      ? payload.clusters
      : (results.clusters as ClusterGroup[] | undefined) ?? []
  ).map((cl) => normalizeClusterGroup(cl as ClusterGroup & Record<string, unknown>));

  return (
    <div className="space-y-6">
      <Card
        title="Column clustering"
        description="Columns are grouped into semantic clusters based on embedding similarity. Each cluster maps to a statistical domain."
      >
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : rawClusters.length === 0 ? (
          <p className="text-sm text-text-muted">No clustering data available.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {rawClusters.map((cluster, idx) => {
              const colorCls = CLUSTER_COLORS[idx % CLUSTER_COLORS.length];
              const domainDistribution = normalizeDomainDistribution(
                cluster.domain_distribution,
                cluster.domain,
                cluster.columns?.length
              );
              const distributionEntries = Object.entries(domainDistribution).sort(
                (a, b) => b[1] - a[1]
              );

              return (
                <div
                  key={cluster.cluster_id}
                  className={cn('rounded-xl border p-4 space-y-3', colorCls)}
                >
                  {/* Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Layers className="h-4 w-4 shrink-0" />
                      <span className="font-semibold text-sm">{cluster.domain}</span>
                    </div>
                    <Badge variant="muted">{cluster.cluster_id}</Badge>
                  </div>

                  {/* Score breakdown */}
                  <div className="space-y-1">
                    <p className="text-xs opacity-70 mb-1">Accuracy signals</p>
                    {miniBar(cluster.support_score, 'Overall', '#ffffff')}
                    {cluster.domain_purity != null && miniBar(cluster.domain_purity, 'Domain purity', '#22c55e')}
                    {cluster.avg_domain_confidence != null && miniBar(cluster.avg_domain_confidence, 'Confidence', '#6366f1')}
                    {cluster.embedding_coherence != null && miniBar(cluster.embedding_coherence, 'Coherence', '#14b8a6')}
                  </div>

                  {/* Columns */}
                  <div>
                    <p className="text-xs opacity-70 mb-1.5">
                      {cluster.columns.length} column{cluster.columns.length !== 1 ? 's' : ''}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {cluster.columns.map((c) => (
                        <span
                          key={c}
                          className="inline-block px-2 py-0.5 rounded-full text-[11px] font-mono border bg-white/40"
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Domain distribution — always shown; normalized to sum 100% */}
                  {distributionEntries.length > 0 && (
                    <details className="text-xs opacity-80" open>
                      <summary className="cursor-pointer hover:opacity-100">
                        Domain distribution
                      </summary>
                      <ul className="mt-1.5 space-y-1 pl-2">
                        {distributionEntries.map(([d, pct]) => (
                          <li key={d} className="flex justify-between gap-2">
                            <span className="truncate">{d}</span>
                            <span className="font-mono shrink-0">{formatDistributionPct(pct)}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Summary table */}
      {rawClusters.length > 0 && (
        <Card title="Clustering summary">
          <div className="flex items-start gap-2 mb-4 text-xs text-text-muted bg-primary/5 border border-primary/20 rounded-lg p-3">
            <Info className="h-3.5 w-3.5 shrink-0 mt-0.5 text-primary" />
            <div>
              <strong className="text-text">How cluster accuracy is computed: </strong>
              Overall support = 40% domain purity + 35% avg domain confidence + 25% embedding coherence.
              Purity = fraction of cluster members sharing the winning domain.
              Coherence = mean pairwise cosine similarity of member embeddings.
            </div>
          </div>
          <div className="overflow-x-auto -mx-6">
            <table className="w-full text-sm min-w-[700px]">
              <thead>
                <tr className="border-b border-border">
                  {['Cluster ID', 'Domain', 'Columns', 'Purity', 'Coherence', 'Overall'].map((h) => (
                    <th key={h} className="px-4 pb-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rawClusters.map((cl) => (
                  <tr key={cl.cluster_id} className="border-b border-border/30 hover:bg-surface/60">
                    <td className="px-4 py-2 font-mono text-xs">{cl.cluster_id}</td>
                    <td className="px-4 py-2 text-xs font-semibold text-primary">{cl.domain}</td>
                    <td className="px-4 py-2 text-xs text-text-muted">{cl.columns.join(', ')}</td>
                    <td className="px-4 py-2 w-24">{scoreBar(cl.domain_purity)}</td>
                    <td className="px-4 py-2 w-24">{scoreBar(cl.embedding_coherence)}</td>
                    <td className="px-4 py-2 w-24">{scoreBar(cl.support_score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button variant="ghost" onClick={onBack} className="flex items-center gap-1">
          <ChevronLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
          <span className="text-sm text-text-muted">
            {rawClusters.length} cluster{rawClusters.length !== 1 ? 's' : ''} verified
          </span>
          <Button onClick={onProceed} size="lg">
            Confirm Clusters & Proceed to Schema →
          </Button>
        </div>
      </div>
    </div>
  );
}
