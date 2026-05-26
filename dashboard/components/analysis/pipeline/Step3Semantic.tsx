'use client';

import { useEffect, useState } from 'react';
import { analysisApi, DomainsPayload, SemanticMappingRow } from '@/lib/api';
import type { AnalysisResult } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { ChevronLeft, CheckCircle2, Info } from 'lucide-react';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  overrides: Record<string, string>;
  onProceed: (overrides: Record<string, string>) => void;
  onBack: () => void;
}

function confidenceColor(c?: number): string {
  if (!c) return 'text-text-muted';
  if (c >= 0.8) return 'text-success';
  if (c >= 0.5) return 'text-warning';
  return 'text-danger';
}
function confidenceVariant(c?: number): 'success' | 'warning' | 'danger' | 'muted' {
  if (!c) return 'muted';
  if (c >= 0.8) return 'success';
  if (c >= 0.5) return 'warning';
  return 'danger';
}

export default function Step3Semantic({ results, analysisId, overrides, onProceed, onBack }: Props) {
  const [domainsPayload, setDomainsPayload] = useState<DomainsPayload | null>(null);
  const [domainsLoading, setDomainsLoading] = useState(true);
  const [localOverrides, setLocalOverrides] = useState<Record<string, string>>(overrides);
  const [expandedDomain, setExpandedDomain] = useState<string | null>(null);

  useEffect(() => {
    analysisApi
      .getDomains(analysisId)
      .then(setDomainsPayload)
      .finally(() => setDomainsLoading(false));
  }, [analysisId]);

  const mappingRows: SemanticMappingRow[] = results.semantic_mapping ?? [];
  const allDomainNames = Object.keys(domainsPayload?.static_domains_taxonomy ?? {});

  const overrideCount = Object.keys(localOverrides).length;

  const handleOverride = (column: string, domain: string) => {
    setLocalOverrides((p) => {
      if (domain === '_original') {
        const next = { ...p };
        delete next[column];
        return next;
      }
      return { ...p, [column]: domain };
    });
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: domain taxonomy */}
        <Card
          title="Static domain taxonomy"
          description="MOSPI ontology — predefined statistical domains used for mapping."
          className="lg:col-span-1 h-fit"
        >
          {domainsLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-8" />
              ))}
            </div>
          ) : (
            <ul className="space-y-1 max-h-[500px] overflow-y-auto pr-1">
              {allDomainNames.map((domain) => {
                const info = domainsPayload!.static_domains_taxonomy[domain];
                const colsInDomain = mappingRows.filter(
                  (r) => (localOverrides[r.column] ?? r.domain) === domain
                ).length;
                return (
                  <li key={domain}>
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedDomain((prev) => (prev === domain ? null : domain))
                      }
                      className={cn(
                        'w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-center justify-between gap-2',
                        expandedDomain === domain
                          ? 'bg-accent/10 text-primary font-medium'
                          : 'hover:bg-border/50 text-text'
                      )}
                    >
                      <span className="truncate">{domain}</span>
                      {colsInDomain > 0 && (
                        <Badge variant="default" className="shrink-0">
                          {colsInDomain}
                        </Badge>
                      )}
                    </button>
                    {expandedDomain === domain && info?.description && (
                      <p className="px-3 py-2 text-xs text-text-muted bg-surface rounded-b-lg border border-t-0 border-border">
                        {String(info.description)}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {domainsPayload?.ontology_macro_type_best_hint && (
            <div className="mt-4 flex items-start gap-2 text-xs text-text-muted border-t border-border pt-3">
              <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>
                Best macro-type hint:{' '}
                <strong className="text-text">{domainsPayload.ontology_macro_type_best_hint}</strong>
              </span>
            </div>
          )}
        </Card>

        {/* Right: mapping table */}
        <Card
          title="Column → domain mapping"
          description="Pipeline-assigned domains with confidence scores. Override any assignment using the dropdown."
          className="lg:col-span-2"
        >
          {overrideCount > 0 && (
            <div className="mb-4 flex items-center gap-2">
              <Badge variant="warning">{overrideCount} manual override{overrideCount > 1 ? 's' : ''}</Badge>
              <button
                type="button"
                onClick={() => setLocalOverrides({})}
                className="text-xs text-text-muted hover:text-danger transition-colors"
              >
                Reset all overrides
              </button>
            </div>
          )}
          <div className="overflow-x-auto -mx-6">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="border-b border-border">
                  {['Column', 'Assigned domain', 'Confidence', 'Cluster', 'Override'].map((h) => (
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
                {mappingRows.map((row) => {
                  const effective = localOverrides[row.column] ?? row.domain ?? '—';
                  const isOverridden = !!localOverrides[row.column];
                  return (
                    <tr
                      key={row.column}
                      className={cn(
                        'border-b border-border/30 hover:bg-surface/60 transition-colors',
                        isOverridden && 'bg-warning/5'
                      )}
                    >
                      <td className="px-4 py-3 font-mono text-xs font-medium text-text">
                        {row.column}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            'text-xs font-semibold',
                            isOverridden ? 'text-warning' : 'text-primary'
                          )}
                        >
                          {effective}
                          {isOverridden && (
                            <span className="ml-1 text-[10px] font-normal text-text-muted">
                              (was: {row.domain})
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-14 h-1.5 rounded-full bg-border overflow-hidden">
                            <div
                              className={cn(
                                'h-full rounded-full',
                                (row.confidence ?? 0) >= 0.8
                                  ? 'bg-success'
                                  : (row.confidence ?? 0) >= 0.5
                                  ? 'bg-warning'
                                  : 'bg-danger'
                              )}
                              style={{ width: `${((row.confidence ?? 0) * 100).toFixed(0)}%` }}
                            />
                          </div>
                          <Badge variant={confidenceVariant(row.confidence)}>
                            {row.confidence != null
                              ? `${(row.confidence * 100).toFixed(0)}%`
                              : '—'}
                          </Badge>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-text-muted">
                        {row.cluster_id ?? '—'}
                      </td>
                      <td className="px-4 py-3">
                        <select
                          value={localOverrides[row.column] ?? '_original'}
                          onChange={(e) => handleOverride(row.column, e.target.value)}
                          className="rounded border border-border bg-surface px-2 py-1 text-xs text-text focus:outline-none focus:ring-2 focus:ring-accent/30"
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
                })}
              </tbody>
            </table>
          </div>

          {/* Audit note */}
          <p className="mt-4 text-xs text-text-muted border-t border-border pt-3">
            All {mappingRows.length} column mappings are recorded in the audit trail. Manual
            overrides will be flagged as &quot;human-reviewed&quot; in the final report.
          </p>
        </Card>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button variant="ghost" onClick={onBack} className="flex items-center gap-1">
          <ChevronLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
          <span className="text-sm text-text-muted">
            {mappingRows.length} columns mapped
            {overrideCount > 0 && `, ${overrideCount} overridden`}
          </span>
          <Button onClick={() => onProceed(localOverrides)} size="lg">
            Confirm Mapping & Proceed to Clustering →
          </Button>
        </div>
      </div>
    </div>
  );
}
