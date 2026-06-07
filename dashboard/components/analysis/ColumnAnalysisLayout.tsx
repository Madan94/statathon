'use client';

import { useEffect, useMemo, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import type { AnalysisResult, ColumnProfile } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import { isNumericColumn, resolveAnomalyBlock } from '@/lib/outlierColumnUtils';
import ColumnNav from './columns/ColumnNav';
import MethodSelectionPanel from './columns/MethodSelectionPanel';
import AnomalyPanel from './columns/AnomalyPanel';
import MissingPanel from './columns/MissingPanel';
import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import {
  Network, LayoutList, ChevronRight, CheckCircle2, FileText,
} from 'lucide-react';
import { toast } from '@/lib/toast';

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

function columnNeedsReview(col: string, results: AnalysisResult): boolean {
  if (!isNumericColumn(col, results)) {
    const health = results.health as { missing_per_column?: Record<string, number> } | undefined;
    return (health?.missing_per_column?.[col] ?? 0) > 0;
  }
  return true;
}

export default function ColumnAnalysisLayout({ results: initialResults, analysisId, onBack }: Props) {
  const router = useRouter();
  const [results, setResults] = useState(initialResults);
  const columns = useMemo(() => orderedColumns(results), [results]);
  const [selectedColumn, setSelectedColumn] = useState<string | null>(columns[0] ?? null);
  const [reviewedColumns, setReviewedColumns] = useState<Set<string>>(new Set());
  const [columnDecisionsComplete, setColumnDecisionsComplete] = useState<Set<string>>(new Set());
  const [anomalyProgress, setAnomalyProgress] = useState({ reviewed: 0, total: 0, complete: false });
  const [imputationProgress, setImputationProgress] = useState({ complete: false });

  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};

  const reviewColumns = columns.filter((c) => columnNeedsReview(c, results));
  const reviewedIssueCount = reviewColumns.filter((c) => reviewedColumns.has(c)).length;
  const allColumnsReviewed = reviewColumns.length === 0 || reviewedIssueCount === reviewColumns.length;

  const currentIndex = selectedColumn ? columns.indexOf(selectedColumn) : -1;
  const nextColumn = currentIndex >= 0 && currentIndex < columns.length - 1
    ? columns[currentIndex + 1]
    : null;

  const validationAcknowledged = Boolean(
    (results.phase3 as { validation_acknowledged?: boolean } | undefined)?.validation_acknowledged,
  );

  const selectedBlock = selectedColumn ? resolveAnomalyBlock(selectedColumn, results) : null;
  const isNumeric = selectedColumn ? isNumericColumn(selectedColumn, results) : false;
  const detectionRun = Boolean(selectedBlock?.detection_run);
  const showMissing = !isNumeric || (detectionRun && columnDecisionsComplete.has(selectedColumn ?? ''));

  const refreshResults = useCallback(async () => {
    const updated = await analysisApi.getResults(analysisId, { includePhase3: true });
    setResults(updated);
  }, [analysisId]);

  useEffect(() => {
    analysisApi.getAnomalyReviewProgress(analysisId).then((p) => {
      setAnomalyProgress({
        reviewed: p.reviewed,
        total: p.total_anomalies,
        complete: p.complete,
      });
    }).catch(() => {});
    analysisApi.getImputationReviewProgress(analysisId).then((p) => {
      setImputationProgress({ complete: p.complete });
    }).catch(() => {});
  }, [analysisId, results]);

  const canProceedToReport =
    validationAcknowledged &&
    allColumnsReviewed &&
    (anomalyProgress.total === 0 || anomalyProgress.complete) &&
    imputationProgress.complete;

  const markColumnReviewed = () => {
    if (!selectedColumn) return;
    if (isNumeric && !detectionRun) return;
    if (isNumeric && !columnDecisionsComplete.has(selectedColumn)) return;
    setReviewedColumns((prev) => new Set(prev).add(selectedColumn));
    if (nextColumn) setSelectedColumn(nextColumn);
  };

  const handleProceed = () => {
    if (!canProceedToReport) {
      toast.error('Complete anomaly and missing-value review before proceeding');
      return;
    }
    router.push(`/report-builder?analysisId=${analysisId}`);
  };

  const canMarkDone = !isNumeric
    || (detectionRun && columnDecisionsComplete.has(selectedColumn ?? ''));

  return (
    <div className="flex flex-col pb-24" style={{ minHeight: 'calc(100vh - 160px)' }}>
      <WorkflowStepper currentStep={3} className="mb-4" />
      <AnalysisStepper currentStep={7} className="mb-4" />

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
            <div className="space-y-6 max-w-5xl">
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
                    disabled={!canMarkDone}
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

              {!validationAcknowledged && (
                <Alert variant="warning" title="Complete rule validation first">
                  Return to Step 6 (Rule Validation) and proceed through the validation gate before reviewing anomalies.
                </Alert>
              )}

              {anomalyProgress.total > 0 && (
                <div className="rounded-lg border border-border p-3 text-sm">
                  <p className="text-text-muted">
                    Anomalies reviewed: <strong>{anomalyProgress.reviewed} / {anomalyProgress.total}</strong>
                    {' · '}
                    Remaining: <strong>{Math.max(0, anomalyProgress.total - anomalyProgress.reviewed)}</strong>
                    {' · '}
                    Progress: <strong>{anomalyProgress.total ? Math.round((anomalyProgress.reviewed / anomalyProgress.total) * 100) : 100}%</strong>
                  </p>
                </div>
              )}

              {isNumeric && validationAcknowledged ? (
                <>
                  <MethodSelectionPanel
                    column={selectedColumn}
                    analysisId={analysisId}
                    results={results}
                    onComplete={(updated) => {
                      setResults(updated);
                      void refreshResults();
                    }}
                  />
                  {detectionRun && (
                    <AnomalyPanel
                      column={selectedColumn}
                      analysisId={analysisId}
                      results={results}
                      onDecisionsComplete={() => {
                        setColumnDecisionsComplete((prev) => new Set(prev).add(selectedColumn));
                        void analysisApi.getAnomalyReviewProgress(analysisId).then((p) => {
                          setAnomalyProgress({
                            reviewed: p.reviewed,
                            total: p.total_anomalies,
                            complete: p.complete,
                          });
                        });
                      }}
                      onProgress={(reviewed, total) => {
                        setAnomalyProgress((prev) => ({
                          ...prev,
                          reviewed,
                          total,
                          complete: total === 0 || reviewed >= total,
                        }));
                      }}
                    />
                  )}
                </>
              ) : (
                !isNumeric && (
                  <p className="text-sm text-text-muted">
                    Column type is non-numeric — outlier detection is not applicable.
                  </p>
                )
              )}

              {showMissing && (
                <MissingPanel
                  column={selectedColumn}
                  analysisId={analysisId}
                  results={results}
                  onSaved={() => {
                    void analysisApi.getImputationReviewProgress(analysisId).then((p) => {
                      setImputationProgress({ complete: p.complete });
                    });
                  }}
                />
              )}
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center py-24 text-center">
              <LayoutList className="h-12 w-12 text-text-muted mb-4" aria-hidden />
              <p className="font-semibold text-text text-lg">Select a column</p>
              <p className="mt-2 text-sm text-text-muted max-w-md">
                {columns.length} columns available. Choose a method, review outliers, then missing values.
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

      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface-card/95 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" onClick={onBack} className="gap-1">
            ← Back to Rule Validation
          </Button>

          <div className="flex items-center gap-3 text-sm text-text-muted">
            <CheckCircle2 className={cn('h-4 w-4', canProceedToReport ? 'text-success' : 'text-text-muted')} />
            <span>
              Columns {reviewedIssueCount}/{reviewColumns.length}
              {anomalyProgress.total > 0 && ` · Anomalies ${anomalyProgress.reviewed}/${anomalyProgress.total}`}
            </span>
          </div>

          <Button onClick={handleProceed} size="lg" className="gap-2" disabled={!canProceedToReport}>
            <FileText className="h-4 w-4" />
            Complete review & proceed to Report →
          </Button>
        </div>
      </div>
    </div>
  );
}
