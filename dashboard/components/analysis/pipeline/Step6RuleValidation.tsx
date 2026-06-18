'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { AnalysisResult, ValidationCandidate } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import ValidationRulesInventory, {
  type RulesInventoryRow,
} from '@/components/analysis/ValidationRulesInventory';
import ValidationTable, {
  type ValidationLoadState,
  type ValidationTableHandle,
} from '@/components/analysis/ValidationTable';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import {
  Shield,
  ShieldAlert,
  ShieldCheck,
  ArrowRight,
  AlertTriangle,
  Loader2,
  CheckCircle2,
  Database,
  FlaskConical,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { toast } from '@/lib/toast';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  loadState?: ValidationLoadState;
  loadError?: string | null;
  onProceed: () => void;
  onBack: () => void;
  onRefresh?: () => void | Promise<void>;
}

type ProceedPhase = 'idle' | 'saving' | 'saved' | 'moving' | 'error';
type ApplyPhase = 'idle' | 'applying' | 'done' | 'error';
type DemoPhase = 'idle' | 'injecting' | 'refreshing' | 'removing';

interface DemoNoiseStatus {
  enabled: boolean;
  active: boolean;
  rows_added: number;
  baseline_row_count: number | null;
  current_row_count: number | null;
  candidate_count: number;
  pending_refresh: boolean;
}

function countBySeverity(candidates: ValidationCandidate[]) {
  const counts: Record<string, number> = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
  for (const c of candidates) {
    const s = String(c.severity ?? 'LOW').toUpperCase();
    if (s in counts) counts[s] += 1;
    else counts.LOW += 1;
  }
  return counts;
}

export default function Step6RuleValidation({
  results,
  analysisId,
  loadState = 'loaded',
  loadError,
  onProceed,
  onBack,
  onRefresh,
}: Props) {
  const tableRef = useRef<ValidationTableHandle>(null);
  const [acknowledged, setAcknowledged] = useState(
    Boolean((results.phase3 as { validation_acknowledged?: boolean } | undefined)?.validation_acknowledged),
  );
  const [proceedPhase, setProceedPhase] = useState<ProceedPhase>('idle');
  const [applyPhase, setApplyPhase] = useState<ApplyPhase>('idle');
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [savedDecisionCount, setSavedDecisionCount] = useState(0);
  const [emptyReviewAck, setEmptyReviewAck] = useState(false);
  const [validationProgress, setValidationProgress] = useState({
    reviewed: 0,
    total: 0,
    reportedTotal: null as number | null,
    reviewComplete: false,
    phaseComplete: false,
    complete: false,
    displaySampleEnabled: false,
    displaySampleSize: null as number | null,
    fullTotal: null as number | null,
  });
  const [demoPhase, setDemoPhase] = useState<DemoPhase>('idle');
  const [tableRefreshKey, setTableRefreshKey] = useState(0);
  const [demoStatus, setDemoStatus] = useState<DemoNoiseStatus | null>(null);

  const demoNoiseEnabled = Boolean(results.meta?.demo_noise_enabled);

  const phase3 = results.phase3 ?? {};
  const candidates = (phase3.validation_candidates as ValidationCandidate[] | undefined) ?? [];
  const validationResults = (phase3.validation_results as {
    summary?: { gate?: Record<string, unknown>; severity_breakdown?: Record<string, number> };
    rules_inventory?: RulesInventoryRow[];
    single_column?: unknown[];
    multi_column?: unknown[];
  } | undefined) ?? {};
  const gateSummary = (validationResults.summary?.gate ?? validationResults.summary ?? {}) as Record<string, unknown>;
  const totalCandidates = Number(
    (phase3 as { validation_candidates_total?: number }).validation_candidates_total
      ?? validationProgress.total
      ?? candidates.length,
  );

  const displaySampleEnabled = Boolean(
    (phase3 as { validation_display_sample_enabled?: boolean }).validation_display_sample_enabled
      ?? validationProgress.displaySampleEnabled,
  );
  const displaySampleSize = Number(
    (phase3 as { validation_display_sample_size?: number }).validation_display_sample_size
      ?? validationProgress.displaySampleSize
      ?? 0,
  ) || null;
  const fullValidationTotal = Number(
    (phase3 as { validation_full_total?: number }).validation_full_total
      ?? validationProgress.fullTotal
      ?? 0,
  ) || null;

  const loadReviewProgress = () => {
    analysisApi
      .getValidationReviewProgress(analysisId)
      .then((p) => {
        setValidationProgress({
          reviewed: p.reviewed,
          total: p.total,
          reportedTotal: p.reported_total ?? null,
          reviewComplete: p.review_complete ?? (p.total > 0 && p.reviewed >= p.total),
          phaseComplete: p.phase_complete ?? p.complete,
          complete: p.complete,
          displaySampleEnabled: Boolean(p.display_sample_enabled),
          displaySampleSize: p.display_sample_size ?? null,
          fullTotal: p.full_total ?? null,
        });
        if (p.acknowledged) setAcknowledged(true);
      })
      .catch(() => {});
  };

  const loadDemoStatus = () => {
    if (!demoNoiseEnabled) return;
    analysisApi
      .getValidationDemoNoiseStatus(analysisId)
      .then(setDemoStatus)
      .catch(() => setDemoStatus(null));
  };

  useEffect(() => {
    loadReviewProgress();
  }, [analysisId, totalCandidates]);

  useEffect(() => {
    loadDemoStatus();
  }, [analysisId, demoNoiseEnabled, tableRefreshKey]);

  const resetReviewStateAfterDemo = () => {
    setAcknowledged(false);
    setEmptyReviewAck(false);
    setSavedDecisionCount(0);
    loadReviewProgress();
  };

  const afterDemoMutation = async () => {
    resetReviewStateAfterDemo();
    setTableRefreshKey((k) => k + 1);
    await onRefresh?.();
    loadDemoStatus();
  };

  const handleInjectDemoNoise = async () => {
    setDemoPhase('injecting');
    try {
      const res = await analysisApi.injectValidationDemoNoise(analysisId);
      toast.success(
        res.message ?? `${res.rows_added} demo row(s) appended — click Refresh validation`,
      );
      await afterDemoMutation();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err instanceof Error ? err.message : 'Failed to inject demo noise');
      toast.error(String(msg));
    } finally {
      setDemoPhase('idle');
    }
  };

  const handleRefreshDemoValidation = async () => {
    setDemoPhase('refreshing');
    try {
      const res = await analysisApi.refreshValidationDemoNoise(analysisId);
      toast.success(
        `Validation refreshed — ${res.candidate_count} violation(s) detected`,
      );
      await afterDemoMutation();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err instanceof Error ? err.message : 'Failed to refresh validation');
      toast.error(String(msg));
    } finally {
      setDemoPhase('idle');
    }
  };

  const handleRemoveDemoNoise = async () => {
    setDemoPhase('removing');
    try {
      const res = await analysisApi.removeValidationDemoNoise(analysisId);
      toast.success(res.message ?? 'Demo noise removed');
      await afterDemoMutation();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err instanceof Error ? err.message : 'Failed to remove demo noise');
      toast.error(String(msg));
    } finally {
      setDemoPhase('idle');
    }
  };

  const reportedCandidateTotal = Number(
    (phase3 as { validation_candidates_reported_total?: number }).validation_candidates_reported_total
      || gateSummary.candidate_count
      || 0,
  );
  const candidatesTruncated = Boolean(
    (phase3 as { validation_candidates_truncated?: boolean }).validation_candidates_truncated,
  );

  const rulesInventory = validationResults.rules_inventory ?? [];

  const domainByColumn = useMemo(() => {
    const map: Record<string, string> = {};
    for (const row of results.semantic_mapping ?? []) {
      if (row.column && row.domain) map[String(row.column)] = String(row.domain);
    }
    for (const [col, dom] of Object.entries(results.semantic ?? {})) {
      if (!map[col]) map[col] = String(dom);
    }
    return map;
  }, [results.semantic_mapping, results.semantic]);

  const gateSeverity = (gateSummary.severity_breakdown ?? validationResults.summary?.severity_breakdown) as
    | Record<string, number>
    | undefined;
  const severity = gateSeverity
    ? {
        CRITICAL: Number(gateSeverity.CRITICAL ?? 0),
        HIGH: Number(gateSeverity.HIGH ?? 0),
        MEDIUM: Number(gateSeverity.MEDIUM ?? 0),
        LOW: Number(gateSeverity.LOW ?? 0),
      }
    : countBySeverity(candidates);
  const criticalCount = severity.CRITICAL;
  const rulesDiscovered = Number(gateSummary.rules_discovered ?? 0);
  const rulesFired = Number(gateSummary.rules_fired ?? totalCandidates);
  const singleCount = Number(
    gateSummary.rules_matched_columns
      ?? candidates.filter((c) => (c.kind ?? '').includes('single')).length,
  );
  const multiCount = (validationResults.multi_column ?? []).length;
  const approved = gateSummary.approved !== false && criticalCount === 0;
  const needsEmptyReviewAck = totalCandidates === 0;
  const identifierColumns = (gateSummary.identifier_columns as string[] | undefined) ?? [];
  const variableColumns = (gateSummary.variable_columns as string[] | undefined) ?? [];
  const variableColumnsWithRules = Number(gateSummary.variable_columns_with_rules ?? 0);
  const missingByColumn = (results.health as { missing_per_column?: Record<string, number> } | undefined)
    ?.missing_per_column ?? {};
  const isLoading = loadState === 'loading' || loadState === 'idle';

  const canProceed =
    (approved || acknowledged) &&
    (validationProgress.reviewComplete || totalCandidates === 0) &&
    (!needsEmptyReviewAck || emptyReviewAck) &&
    proceedPhase !== 'saving' &&
    proceedPhase !== 'moving';

  const proceedBlockedReason = (() => {
    if (needsEmptyReviewAck && !emptyReviewAck) {
      return 'Confirm rules inventory review above';
    }
    if (!validationProgress.reviewComplete && totalCandidates > 0) {
      const remaining = Math.max(0, validationProgress.total - validationProgress.reviewed);
      return remaining > 0
        ? `Save decisions for ${remaining} remaining violation(s)`
        : 'Save validation decisions for all violations';
    }
    if (!approved && !acknowledged) {
      return 'Acknowledge critical violations using the checkbox above';
    }
    return null;
  })();
  const canApply = applyPhase !== 'applying' && !isLoading;
  const applyDisabledReason =
    isLoading
      ? 'Loading validation results…'
      : applyPhase === 'applying'
        ? 'Applying…'
        : null;

  const handleApplyToDataset = async () => {
    setApplyPhase('applying');
    setApplyMessage(null);
    try {
      if (tableRef.current?.hasPendingChanges()) {
        await tableRef.current.saveDecisions();
      }
      const res = await analysisApi.applyLineage(analysisId);
      const snapshotError = (res as { snapshot_error?: string })?.snapshot_error;
      if (snapshotError) {
        toast.info(`Apply completed with warnings: ${snapshotError}`);
      } else {
        toast.success('Validation decisions applied to working dataset snapshots.');
      }
      const lineage = await analysisApi.getLineage(analysisId);
      const stages = Array.isArray((lineage as { lineage?: Array<{ stage?: string }> }).lineage)
        ? ((lineage as { lineage?: Array<{ stage?: string }> }).lineage ?? [])
            .map((row) => row.stage)
            .filter(Boolean)
        : [];
      setApplyMessage(
        stages.length
          ? `Snapshots updated: ${stages.join(' → ')}`
          : 'Dataset snapshots rebuilt from saved decisions.',
      );
      setApplyPhase('done');
    } catch (err: unknown) {
      setApplyPhase('error');
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err instanceof Error ? err.message : 'Apply failed');
      toast.error(String(msg));
    }
  };

  const handleProceed = async () => {
    setProceedPhase('saving');
    try {
      if (tableRef.current?.hasPendingChanges()) {
        await tableRef.current.saveDecisions();
      }
      const payload = tableRef.current?.getDecisionPayload() ?? [];
      setProceedPhase('moving');

      const res = await analysisApi.proceedValidation(analysisId, payload, {
        critical_count: criticalCount,
        candidate_count: validationProgress.total || totalCandidates,
      });
      if (res.success === false) {
        throw new Error('Failed to confirm validation review');
      }
      setSavedDecisionCount(Number(res.saved ?? payload.length));
      setValidationProgress((prev) => ({
        ...prev,
        reviewed: Number(res.saved ?? payload.length),
        reviewComplete: true,
        phaseComplete: true,
        complete: true,
      }));
      setAcknowledged(true);
      onProceed();
    } catch (err: unknown) {
      setProceedPhase('error');
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err instanceof Error ? err.message : 'Failed to save rule decisions');
      toast.error(String(msg));
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-4">
          <p className="text-xs text-text-muted uppercase">Rules discovered</p>
          <p className="text-2xl font-bold font-mono mt-1">{isLoading ? '…' : rulesDiscovered || '—'}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-text-muted uppercase">Rules fired</p>
          <p className="text-2xl font-bold font-mono mt-1">{isLoading ? '…' : rulesFired}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-text-muted uppercase">Single-column</p>
          <p className="text-2xl font-bold font-mono mt-1">{isLoading ? '…' : singleCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-text-muted uppercase">Multi-column</p>
          <p className="text-2xl font-bold font-mono mt-1">{isLoading ? '…' : multiCount}</p>
        </Card>
      </div>

      {!isLoading && demoNoiseEnabled && (
        <Card className="border-accent/30 bg-accent/5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <FlaskConical className="h-4 w-4 text-accent" />
                <p className="text-sm font-semibold text-text">Jury demo — live validation</p>
              </div>
              <p className="text-xs text-text-muted max-w-xl">
                Append rows with rule-breaking values, refresh validation to detect violations
                dynamically, then review in the table below. Remove demo noise to restore the
                baseline dataset.
              </p>
              {demoStatus && (
                <p className="text-xs text-text-muted">
                  {demoStatus.active ? (
                    <>
                      Demo noise: <strong>{demoStatus.rows_added}</strong> row(s) injected
                      {demoStatus.pending_refresh
                        ? ' · refresh validation to scan'
                        : ` · ${demoStatus.candidate_count} violation(s) in review`}
                    </>
                  ) : (
                    <>No demo noise active · baseline {demoStatus.baseline_row_count ?? '—'} rows</>
                  )}
                </p>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={demoPhase !== 'idle' || Boolean(demoStatus?.active)}
                onClick={() => void handleInjectDemoNoise()}
                className="gap-1.5"
              >
                {demoPhase === 'injecting' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FlaskConical className="h-3.5 w-3.5" />
                )}
                Add noise data
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={demoPhase !== 'idle' || !demoStatus?.active}
                onClick={() => void handleRefreshDemoValidation()}
                className="gap-1.5"
              >
                {demoPhase === 'refreshing' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Refresh validation
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={demoPhase !== 'idle' || !demoStatus?.active}
                onClick={() => void handleRemoveDemoNoise()}
                className="gap-1.5 text-danger hover:text-danger"
              >
                {demoPhase === 'removing' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
                Remove demo noise
              </Button>
            </div>
          </div>
        </Card>
      )}

      {!isLoading && (
        <Card>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            {approved ? (
              <Badge variant="success" className="gap-1">
                <ShieldCheck className="h-3.5 w-3.5" /> Validation gate passed
              </Badge>
            ) : (
              <Badge variant="danger" className="gap-1">
                <ShieldAlert className="h-3.5 w-3.5" /> Critical violations present
              </Badge>
            )}
            {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map((s) =>
              severity[s] > 0 ? (
                <Badge key={s} variant={s === 'CRITICAL' ? 'danger' : s === 'HIGH' ? 'warning' : 'muted'}>
                  {s}: {severity[s]}
                </Badge>
              ) : null,
            )}
          </div>
          <p className="text-sm text-text-muted">
            Rule validation uses semantic domains, column statistics, knowledge-graph relationships,
            and government rulebooks. Review violations before proceeding to anomaly detection.
          </p>
        </Card>
      )}

      {!isLoading && !approved && (
        <Alert variant="warning" title="Critical rule violations detected">
          <p className="text-sm">
            {criticalCount} critical violation(s) require review. You may acknowledge and proceed,
            or resolve violations in the table below first.
          </p>
          <label className="flex items-center gap-2 mt-3 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="rounded border-border"
            />
            I have reviewed critical violations and want to proceed to anomaly detection
          </label>
        </Alert>
      )}

      {!isLoading && displaySampleEnabled && displaySampleSize && fullValidationTotal && fullValidationTotal > displaySampleSize && (
        <Alert variant="info" title="Hackathon review sample">
          <p className="text-sm">
            Showing {displaySampleSize.toLocaleString()} randomly selected violations out of{' '}
            {fullValidationTotal.toLocaleString()} stored. Review and save decisions for this sample only;
            remaining violations are left unchanged.
          </p>
        </Alert>
      )}

      {!isLoading && (
        <ValidationRulesInventory
          inventory={rulesInventory}
          rulesDiscovered={rulesDiscovered}
          className="mb-2"
        />
      )}

      {!isLoading && needsEmptyReviewAck && (
        <Alert variant="warning" title="No violation rows — confirm before proceeding">
          <p className="text-sm">
            {variableColumns.length > 0 && variableColumnsWithRules === 0
              ? 'No rule-based validations for variable columns.'
              : 'The table below has no cells to review'}
            {variableColumns.length > 0 && variableColumnsWithRules === 0
              ? ' Identifier columns were excluded from rule validation; only missing-value checks apply to those.'
              : rulesInventory.length === 0
                ? ' because no rules matched your column names.'
                : ` — ${rulesInventory.filter((r) => r.status === 'passed').length} rule check(s) passed cleanly.`}
            {' '}You must still review the rules inventory and apply decisions before column analysis.
          </p>
          <label className="flex items-center gap-2 mt-3 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={emptyReviewAck}
              onChange={(e) => setEmptyReviewAck(e.target.checked)}
              className="rounded border-border"
            />
            I reviewed the rules inventory and confirm there are no open validation issues
          </label>
        </Alert>
      )}

      <ValidationTable
        key={tableRefreshKey}
        ref={tableRef}
        candidates={candidates}
        analysisId={analysisId}
        loadState={loadState}
        loadError={loadError}
        domainByColumn={domainByColumn}
        paginated
        totalCandidates={totalCandidates}
        reportedTotal={reportedCandidateTotal || undefined}
        candidatesTruncated={candidatesTruncated}
        displaySampleEnabled={displaySampleEnabled}
        displaySampleSize={displaySampleSize ?? undefined}
        fullTotal={fullValidationTotal ?? undefined}
        onSaved={() => {
          void analysisApi.getValidationReviewProgress(analysisId).then((p) => {
            setValidationProgress({
              reviewed: p.reviewed,
              total: p.total,
              reportedTotal: p.reported_total ?? null,
              reviewComplete: p.review_complete ?? (p.total > 0 && p.reviewed >= p.total),
              phaseComplete: p.phase_complete ?? p.complete,
              complete: p.complete,
              displaySampleEnabled: Boolean(p.display_sample_enabled),
              displaySampleSize: p.display_sample_size ?? null,
              fullTotal: p.full_total ?? null,
            });
            if (p.reviewed > 0) setSavedDecisionCount(p.reviewed);
          });
        }}
      />

      {!isLoading && (
        <Card className="p-4">
          <p className="text-sm text-text-muted">
            Reviewed:{' '}
            <strong>
              {validationProgress.reviewed} / {validationProgress.total || totalCandidates}
            </strong>
            {!validationProgress.displaySampleEnabled
              && validationProgress.reportedTotal != null
              && validationProgress.reportedTotal > validationProgress.total && (
              <span className="text-text-muted">
                {' '}
                ({validationProgress.reportedTotal} detected; {validationProgress.total} stored for review)
              </span>
            )}
            {' · '}
            Status:{' '}
            <strong className={
              validationProgress.phaseComplete ? 'text-success'
                : validationProgress.reviewComplete ? 'text-accent'
                : 'text-warning'
            }>
              {validationProgress.phaseComplete
                ? 'Completed'
                : validationProgress.reviewComplete
                  ? 'Ready to proceed'
                  : 'In progress'}
            </strong>
          </p>
        </Card>
      )}

      {(proceedPhase === 'saving' || proceedPhase === 'saved' || proceedPhase === 'moving') && (
        <Card className="p-4 border-accent/30 bg-accent/5">
          <div className="flex items-center gap-3 text-sm">
            {proceedPhase === 'saving' && (
              <>
                <Loader2 className="h-4 w-4 animate-spin text-accent" />
                <span>Saving decisions…</span>
              </>
            )}
            {proceedPhase === 'saved' && (
              <>
                <CheckCircle2 className="h-4 w-4 text-success" />
                <span>✓ {savedDecisionCount} decisions saved</span>
              </>
            )}
            {proceedPhase === 'moving' && (
              <>
                <Loader2 className="h-4 w-4 animate-spin text-accent" />
                <span>Moving to anomaly detection…</span>
              </>
            )}
          </div>
        </Card>
      )}

      {proceedPhase === 'error' && (
        <Alert variant="error" title="Failed to save rule decisions">
          <p className="text-sm">Your decisions were not saved. Fix any errors and try again — you will stay on this step.</p>
        </Alert>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <Button variant="ghost" onClick={onBack} disabled={proceedPhase === 'saving' || proceedPhase === 'moving'}>
          ← Back to schema graph
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={handleApplyToDataset}
            disabled={!canApply}
            title={applyDisabledReason ?? undefined}
            className="gap-2"
          >
            {applyPhase === 'applying' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Database className="h-4 w-4" />
            )}
            Apply to dataset
          </Button>
          {!canProceed && !isLoading && proceedBlockedReason && (
            <span className="text-xs text-text-muted flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" />
              {proceedBlockedReason}
            </span>
          )}
          <Button
            onClick={handleProceed}
            disabled={!canProceed || isLoading}
            className="gap-2"
          >
            <Shield className="h-4 w-4" />
            Proceed to column analysis
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
      {applyMessage && applyPhase === 'done' && (
        <p className="text-xs text-success">{applyMessage}</p>
      )}
    </div>
  );
}
