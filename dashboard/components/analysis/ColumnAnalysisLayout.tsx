'use client';

import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
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
  Network, LayoutList, ChevronRight, CheckCircle2, ClipboardCheck,
} from 'lucide-react';
import { toast } from '@/lib/toast';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  onBack: () => void;
  onProceedToDatasetReview: () => void;
}

type PhaseStatus = Awaited<ReturnType<typeof analysisApi.getPhaseStatus>>;

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

export default function ColumnAnalysisLayout({
  results: initialResults,
  analysisId,
  onBack,
  onProceedToDatasetReview,
}: Props) {
  const [results, setResults] = useState(initialResults);
  const [phaseStatus, setPhaseStatus] = useState<PhaseStatus | null>(null);
  const columns = useMemo(() => orderedColumns(results), [results]);
  const [selectedColumn, setSelectedColumn] = useState<string | null>(columns[0] ?? null);
  const [reviewedColumns, setReviewedColumns] = useState<Set<string>>(new Set());
  const [columnDecisionsComplete, setColumnDecisionsComplete] = useState<Set<string>>(new Set());
  const autoCompleteRef = useRef<Set<string>>(new Set());

  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};

  const reviewColumns = columns.filter((c) => columnNeedsReview(c, results));
  const reviewedIssueCount = reviewColumns.filter((c) => reviewedColumns.has(c)).length;

  const currentIndex = selectedColumn ? columns.indexOf(selectedColumn) : -1;
  const nextColumn = currentIndex >= 0 && currentIndex < columns.length - 1
    ? columns[currentIndex + 1]
    : null;

  const validationComplete = Boolean(phaseStatus?.rule_validation_completed);

  const selectedBlock = selectedColumn ? resolveAnomalyBlock(selectedColumn, results) : null;
  const isNumeric = selectedColumn ? isNumericColumn(selectedColumn, results) : false;
  const detectionRun = Boolean(selectedBlock?.detection_run);
  const showMissing = !isNumeric || (detectionRun && columnDecisionsComplete.has(selectedColumn ?? ''));

  const refreshPhaseStatus = useCallback(async () => {
    const status = await analysisApi.getPhaseStatus(analysisId);
    setPhaseStatus(status);

    const anomalyReviews = status.column_reviews?.anomaly ?? [];
    const imputationReviews = status.column_reviews?.imputation ?? [];
    const autoDone = new Set<string>();
    const decisionsDone = new Set<string>();
    const reviewed = new Set<string>();

    for (const row of anomalyReviews) {
      if (row.status === 'auto_reviewed' || row.status === 'reviewed') {
        autoDone.add(row.column);
        decisionsDone.add(row.column);
        reviewed.add(row.column);
      }
    }
    for (const row of imputationReviews) {
      if (row.status === 'auto_reviewed' || row.status === 'reviewed') {
        reviewed.add(row.column);
      }
    }
    setColumnDecisionsComplete((prev) => new Set([...prev, ...decisionsDone]));
    setReviewedColumns((prev) => new Set([...prev, ...reviewed]));
    autoCompleteRef.current = autoDone;
  }, [analysisId]);

  const refreshResults = useCallback(async () => {
    const updated = await analysisApi.getResults(analysisId, { includePhase3: true });
    setResults(updated);
  }, [analysisId]);

  useEffect(() => {
    void refreshPhaseStatus().catch(() => {});
  }, [refreshPhaseStatus]);

  const canProceedToDatasetReview = Boolean(
    phaseStatus?.rule_validation_completed &&
    phaseStatus?.anomaly_completed &&
    phaseStatus?.missing_value_completed,
  );

  const pendingAnomaly = useMemo(
    () => (phaseStatus?.column_reviews?.anomaly ?? [])
      .filter((r) => r.status === 'pending')
      .map((r) => r.column),
    [phaseStatus],
  );
  const pendingImputation = useMemo(
    () => (phaseStatus?.column_reviews?.imputation ?? [])
      .filter((r) => r.status === 'pending')
      .map((r) => r.column),
    [phaseStatus],
  );

  const markColumnReviewed = () => {
    if (!selectedColumn) return;
    if (isNumeric && !detectionRun) return;
    if (isNumeric && !columnDecisionsComplete.has(selectedColumn)) return;
    setReviewedColumns((prev) => new Set(prev).add(selectedColumn));
    if (nextColumn) setSelectedColumn(nextColumn);
  };

  const handleProceed = () => {
    if (!canProceedToDatasetReview) {
      toast.error('Complete anomaly and missing-value review before proceeding');
      return;
    }
    onProceedToDatasetReview();
  };

  const canMarkDone = !isNumeric
    || (detectionRun && columnDecisionsComplete.has(selectedColumn ?? ''));

  const anomalyAuto = phaseStatus?.anomaly?.auto_reviewed ?? 0;
  const imputationAuto = phaseStatus?.imputation?.auto_reviewed ?? 0;

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

              {!validationComplete && (
                <Alert variant="warning" title="Complete rule validation first">
                  Return to Step 6 (Rule Validation) and proceed through the validation gate before reviewing anomalies.
                </Alert>
              )}

              {phaseStatus && (
                <div className="rounded-lg border border-border p-3 text-sm space-y-1">
                  <p className="text-text-muted">
                    Anomaly columns reviewed:{' '}
                    <strong>{phaseStatus.anomaly.columns_reviewed} / {phaseStatus.anomaly.columns_total}</strong>
                    {anomalyAuto > 0 && (
                      <> · including <strong>{anomalyAuto}</strong> auto-reviewed</>
                    )}
                  </p>
                  <p className="text-text-muted">
                    Missing-value columns reviewed:{' '}
                    <strong>{phaseStatus.imputation.columns_reviewed} / {phaseStatus.imputation.columns_total}</strong>
                    {imputationAuto > 0 && (
                      <> · including <strong>{imputationAuto}</strong> auto-reviewed</>
                    )}
                  </p>
                </div>
              )}

              {phaseStatus && !canProceedToDatasetReview && (pendingAnomaly.length > 0 || pendingImputation.length > 0) && (
                <Alert variant="warning" title="Review still pending">
                  {pendingAnomaly.length > 0 && (
                    <p className="text-sm">
                      Anomaly: save decisions for{' '}
                      <strong>{pendingAnomaly.slice(0, 8).join(', ')}</strong>
                      {pendingAnomaly.length > 8 ? ` (+${pendingAnomaly.length - 8} more)` : ''}
                    </p>
                  )}
                  {pendingImputation.length > 0 && (
                    <p className="text-sm mt-1">
                      Missing values: save decisions for{' '}
                      <strong>{pendingImputation.slice(0, 8).join(', ')}</strong>
                      {pendingImputation.length > 8 ? ` (+${pendingImputation.length - 8} more)` : ''}
                    </p>
                  )}
                </Alert>
              )}

              {isNumeric && validationComplete ? (
                <>
                  <MethodSelectionPanel
                    column={selectedColumn}
                    analysisId={analysisId}
                    results={results}
                    onComplete={(updated) => {
                      setResults(updated);
                      void refreshResults();
                      void refreshPhaseStatus();
                    }}
                  />
                  {detectionRun && (
                    <AnomalyPanel
                      column={selectedColumn}
                      analysisId={analysisId}
                      results={results}
                      onDecisionsComplete={() => {
                        setColumnDecisionsComplete((prev) => new Set(prev).add(selectedColumn));
                        setReviewedColumns((prev) => new Set(prev).add(selectedColumn));
                        void refreshPhaseStatus();
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
                    if (selectedColumn) {
                      setReviewedColumns((prev) => new Set(prev).add(selectedColumn));
                    }
                    void refreshPhaseStatus();
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
            <CheckCircle2 className={cn('h-4 w-4', canProceedToDatasetReview ? 'text-success' : 'text-text-muted')} />
            <span>
              Columns {reviewedIssueCount}/{reviewColumns.length}
              {phaseStatus && (
                <> · Anomaly {phaseStatus.anomaly.columns_reviewed}/{phaseStatus.anomaly.columns_total}</>
              )}
            </span>
          </div>

          <Button onClick={handleProceed} size="lg" className="gap-2" disabled={!canProceedToDatasetReview}>
            <ClipboardCheck className="h-4 w-4" />
            Complete review & proceed to Dataset Review →
          </Button>
        </div>
      </div>
    </div>
  );
}
