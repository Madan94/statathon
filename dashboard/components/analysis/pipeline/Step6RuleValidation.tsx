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
import { Shield, ShieldAlert, ShieldCheck, ArrowRight, AlertTriangle, Loader2, CheckCircle2, Database } from 'lucide-react';
import { toast } from '@/lib/toast';

interface Props {
  results: AnalysisResult;
  analysisId: number;
  loadState?: ValidationLoadState;
  loadError?: string | null;
  onProceed: () => void;
  onBack: () => void;
}

type ProceedPhase = 'idle' | 'saving' | 'saved' | 'moving' | 'error';
type ApplyPhase = 'idle' | 'applying' | 'done' | 'error';

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
    complete: false,
  });

  const phase3 = results.phase3 ?? {};
  const candidates = (phase3.validation_candidates as ValidationCandidate[] | undefined) ?? [];

  useEffect(() => {
    analysisApi.getValidationReviewProgress(analysisId).then((p) => {
      setValidationProgress({
        reviewed: p.reviewed,
        total: p.total,
        complete: p.complete,
      });
    }).catch(() => {});
  }, [analysisId, candidates.length]);

  const validationResults = (phase3.validation_results as {
    summary?: { gate?: Record<string, unknown> };
    rules_inventory?: RulesInventoryRow[];
    single_column?: unknown[];
    multi_column?: unknown[];
  } | undefined) ?? {};
  const gateSummary = (validationResults.summary?.gate ?? validationResults.summary ?? {}) as Record<string, unknown>;
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

  const severity = countBySeverity(candidates);
  const criticalCount = severity.CRITICAL;
  const rulesDiscovered = Number(gateSummary.rules_discovered ?? 0);
  const rulesFired = Number(gateSummary.rules_fired ?? candidates.length);
  const singleCount = Number(
    gateSummary.rules_matched_columns
      ?? candidates.filter((c) => (c.kind ?? '').includes('single')).length,
  );
  const multiCount = (validationResults.multi_column ?? []).length;
  const approved = gateSummary.approved !== false && criticalCount === 0;
  const needsEmptyReviewAck = candidates.length === 0;

  const canProceed =
    (approved || acknowledged) &&
    (validationProgress.complete || candidates.length === 0) &&
    (!needsEmptyReviewAck || emptyReviewAck) &&
    proceedPhase !== 'saving' &&
    proceedPhase !== 'moving';
  const canApply =
    applyPhase !== 'applying' &&
    (savedDecisionCount > 0 || validationProgress.complete || Boolean(phase3.validation_acknowledged));
  const isLoading = loadState === 'loading' || loadState === 'idle';

  const handleApplyToDataset = async () => {
    setApplyPhase('applying');
    setApplyMessage(null);
    try {
      const res = await analysisApi.applyLineage(analysisId);
      const applied = (res as { applied?: Record<string, unknown> })?.applied;
      const snapshotError = (res as { snapshot_error?: string })?.snapshot_error;
      if (snapshotError) {
        toast.info(`Apply completed with warnings: ${snapshotError}`);
      } else {
        toast.success('Validation decisions applied to working dataset snapshots.');
      }
      setApplyMessage(
        applied
          ? `Applied: ${JSON.stringify(applied).slice(0, 120)}…`
          : 'Dataset snapshots rebuilt from saved decisions.'
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
      const payload = tableRef.current?.getDecisionPayload() ?? [];
      setProceedPhase('moving');

      const res = await analysisApi.proceedValidation(analysisId, payload, {
        critical_count: criticalCount,
        candidate_count: validationProgress.total || candidates.length,
      });
      if (res.success === false) {
        throw new Error('Failed to confirm validation review');
      }
      setSavedDecisionCount(Number(res.saved ?? payload.length));
      setValidationProgress({
        reviewed: Number(res.saved ?? payload.length),
        total: validationProgress.total || candidates.length,
        complete: true,
      });
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
            The table below has no cells to review
            {rulesInventory.length === 0
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
        ref={tableRef}
        candidates={candidates}
        analysisId={analysisId}
        loadState={loadState}
        loadError={loadError}
        domainByColumn={domainByColumn}
        onSaved={() => {
          void analysisApi.getValidationReviewProgress(analysisId).then((p) => {
            setValidationProgress({
              reviewed: p.reviewed,
              total: p.total,
              complete: p.complete,
            });
            if (p.reviewed > 0) {
              setSavedDecisionCount(p.reviewed);
            }
          });
        }}
      />

      {!isLoading && (
        <Card className="p-4">
          <p className="text-sm text-text-muted">
            Reviewed: <strong>{validationProgress.reviewed} / {validationProgress.total || candidates.length}</strong>
            {' · '}
            Status:{' '}
            <strong className={validationProgress.complete ? 'text-success' : 'text-warning'}>
              {validationProgress.complete ? 'Completed' : 'In progress'}
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
                <span>✓ {savedDecisionCount} decision(s) saved</span>
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
            disabled={!canApply || isLoading}
            className="gap-2"
          >
            {applyPhase === 'applying' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Database className="h-4 w-4" />
            )}
            Apply to dataset
          </Button>
          {!canProceed && !isLoading && (
            <span className="text-xs text-text-muted flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" />
              {needsEmptyReviewAck && !emptyReviewAck
                ? 'Confirm rules inventory review above'
                : 'Review all violations or acknowledge critical issues'}
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
