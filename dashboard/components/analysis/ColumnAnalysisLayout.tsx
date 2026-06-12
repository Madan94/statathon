'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { AnalysisResult, AnomalyCandidate, ColumnProfile } from '@/lib/api';
import ColumnNav from './columns/ColumnNav';
import AnomalyPanel, { type AnomalyDecision } from './columns/AnomalyPanel';
import MissingPanel from './columns/MissingPanel';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import {
  Network, LayoutList, ChevronRight, CheckCircle2, FileText,
} from 'lucide-react';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  onBack: () => void;
}

function orderedColumns(results: AnalysisResult): string[] {
  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};
  const allColumns = Object.keys(columnProfiles ?? schema);

  const domainMap: Record<string, string> = {};
  results.semantic_mapping?.forEach((row) => {
    if (row.domain) domainMap[row.column] = row.domain;
  });

  const domains = [...new Set(Object.values(domainMap))].sort();
  const ordered: string[] = [];
  for (const domain of domains) {
    ordered.push(...allColumns.filter((c) => domainMap[c] === domain));
  }
  ordered.push(...allColumns.filter((c) => !domainMap[c]));
  return ordered.length ? ordered : allColumns;
}

function columnHasIssues(
  col: string,
  results: AnalysisResult,
): boolean {
  const health = results.health as { missing_per_column?: Record<string, number>; rows?: number } | undefined;
  const anomalies = (
    (results.phase3 as { anomaly_candidates?: AnomalyCandidate[] } | undefined)
      ?.anomaly_candidates ?? []
  ).filter((c) => c.column === col);
  const missing = health?.missing_per_column?.[col] ?? 0;
  return anomalies.length > 0 || missing > 0;
}

export default function ColumnAnalysisLayout({ results, analysisId, onBack }: Props) {
  const router = useRouter();
  const columns = useMemo(() => orderedColumns(results), [results]);
  const [selectedColumn, setSelectedColumn] = useState<string | null>(columns[0] ?? null);
  const [reviewedColumns, setReviewedColumns] = useState<Set<string>>(new Set());
  const [anomalyDecisions, setAnomalyDecisions] = useState<
    Record<string, Record<number, AnomalyDecision>>
  >({});

  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};

  const issueColumns = columns.filter((c) => columnHasIssues(c, results));
  const reviewedIssueCount = issueColumns.filter((c) => reviewedColumns.has(c)).length;
  const allReviewed = issueColumns.length === 0 || reviewedIssueCount === issueColumns.length;

  const currentIndex = selectedColumn ? columns.indexOf(selectedColumn) : -1;
  const nextColumn = currentIndex >= 0 && currentIndex < columns.length - 1
    ? columns[currentIndex + 1]
    : null;

  const markColumnReviewed = () => {
    if (!selectedColumn) return;
    setReviewedColumns((prev) => new Set(prev).add(selectedColumn));
    if (nextColumn) setSelectedColumn(nextColumn);
  };

  const handleProceed = () => {
    router.push(`/report/report-builder?analysisId=${analysisId}`);
  };

  return (
    <div className="flex flex-col pb-24" style={{ minHeight: 'calc(100vh - 160px)' }}>
      <WorkflowStepper currentStep={3} className="mb-4" />
      <AnalysisStepper currentStep={6} className="mb-4" />

      <div className="flex flex-1 overflow-hidden rounded-xl border border-border min-h-[520px]">
        <ColumnNav
          results={results}
          selectedColumn={selectedColumn}
          onSelectColumn={setSelectedColumn}
          onBack={onBack}
          reviewedColumns={reviewedColumns}
        />

        <main className="flex-1 overflow-y-auto p-6">
          {selectedColumn ? (
            <div className="space-y-6 max-w-4xl">
              <div className="flex flex-wrap items-start justify-between gap-3 pb-4 border-b border-border">
                <div className="flex items-center gap-3">
                  <div className="h-8 w-8 rounded-lg bg-accent/10 flex items-center justify-center">
                    <Network className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-text font-mono">{selectedColumn}</h2>
                    <p className="text-xs text-text-muted mt-0.5">
                      Column {currentIndex + 1} of {columns.length} ·{' '}
                      {schema[selectedColumn] ??
                        columnProfiles?.[selectedColumn]?.datatype ??
                        'unknown type'}{' '}
                      ·{' '}
                      {results.semantic_mapping?.find((r) => r.column === selectedColumn)?.domain ??
                        'no domain'}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                  {reviewedColumns.has(selectedColumn) && (
                    <Badge variant="success" className="gap-1">
                      <CheckCircle2 className="h-3 w-3" /> Reviewed
                    </Badge>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={markColumnReviewed}
                    className="gap-1"
                  >
                    {nextColumn ? (
                      <>Mark done & next column <ChevronRight className="h-3.5 w-3.5" /></>
                    ) : (
                      <>Mark column reviewed <CheckCircle2 className="h-3.5 w-3.5" /></>
                    )}
                  </Button>
                </div>
              </div>

              <AnomalyPanel
                column={selectedColumn}
                results={results}
                decisions={anomalyDecisions[selectedColumn]}
                onDecisionsChange={(d) =>
                  setAnomalyDecisions((prev) => ({ ...prev, [selectedColumn]: d }))
                }
              />
              <MissingPanel column={selectedColumn} results={results} />
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center py-24 text-center">
              <LayoutList className="h-12 w-12 text-text-muted mb-4" aria-hidden />
              <p className="font-semibold text-text text-lg">Select a column</p>
              <p className="mt-2 text-sm text-text-muted max-w-md">
                {columns.length} columns available. Click any column in the left panel to
                review anomalies and missing values.
              </p>
              {columns[0] && (
                <Button className="mt-4" onClick={() => setSelectedColumn(columns[0])}>
                  Start with {columns[0]} →
                </Button>
              )}
            </div>
          )}
        </main>
      </div>

      {/* Sticky footer — proceed to Report phase */}
      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface-card/95 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" onClick={onBack} className="gap-1">
            ← Back to Schema & KG
          </Button>

          <div className="flex items-center gap-3 text-sm text-text-muted">
            <CheckCircle2 className={cn('h-4 w-4', allReviewed ? 'text-success' : 'text-text-muted')} />
            <span>
              {issueColumns.length === 0
                ? 'No column issues detected'
                : `${reviewedIssueCount} / ${issueColumns.length} columns with issues reviewed`}
            </span>
          </div>

          <Button
            onClick={handleProceed}
            size="lg"
            className="gap-2"
          >
            <FileText className="h-4 w-4" />
            Complete review & proceed to Report →
          </Button>
        </div>
      </div>
    </div>
  );
}
