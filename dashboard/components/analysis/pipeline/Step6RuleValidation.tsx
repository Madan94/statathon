'use client';

import { useMemo, useRef, useState } from 'react';
import type { AnalysisResult, ValidationCandidate } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import ValidationTable, {
  type ValidationLoadState,
  type ValidationTableHandle,
} from '@/components/analysis/ValidationTable';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { Shield, ShieldAlert, ShieldCheck, ArrowRight, AlertTriangle, Loader2, CheckCircle2 } from 'lucide-react';
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
  const [savedDecisionCount, setSavedDecisionCount] = useState(0);

  const phase3 = results.phase3 ?? {};
  const candidates = (phase3.validation_candidates as ValidationCandidate[] | undefined) ?? [];
  const validationResults = (phase3.validation_results as {
    summary?: { gate?: Record<string, unknown> };
    single_column?: unknown[];
    multi_column?: unknown[];
  } | undefined) ?? {};
  const gateSummary = (validationResults.summary?.gate ?? validationResults.summary ?? {}) as Record<string, unknown>;

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
  const singleCount = candidates.filter((c) => (c.kind ?? '').includes('single')).length;
  const multiCount = candidates.filter((c) => !(c.kind ?? '').includes('single')).length;
  const rulesDiscovered = Number(gateSummary.rules_discovered ?? 0);
  const rulesFired = Number(gateSummary.rules_fired ?? candidates.length);
  const approved = gateSummary.approved !== false && criticalCount === 0;

  const canProceed = (approved || acknowledged) && proceedPhase !== 'saving' && proceedPhase !== 'moving';
  const isLoading = loadState === 'loading' || loadState === 'idle';

  const handleProceed = async () => {
    setProceedPhase('saving');
    try {
      const { saved } = await tableRef.current!.saveDecisions();
      setSavedDecisionCount(saved);
      setProceedPhase('saved');

      await new Promise((r) => setTimeout(r, 400));
      setProceedPhase('moving');

      const ack = await analysisApi.acknowledgeValidation(analysisId, {
        critical_count: criticalCount,
        candidate_count: candidates.length,
      });
      if (ack.success === false) {
        throw new Error('Failed to confirm validation review');
      }
      setAcknowledged(true);
      onProceed();
    } catch (err) {
      setProceedPhase('error');
      toast.error(err instanceof Error ? err.message : 'Failed to save rule decisions');
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

      <ValidationTable
        ref={tableRef}
        candidates={candidates}
        analysisId={analysisId}
        loadState={loadState}
        loadError={loadError}
        domainByColumn={domainByColumn}
      />

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
          ← Back to Schema & KG
        </Button>
        <div className="flex items-center gap-2">
          {!canProceed && !isLoading && (
            <span className="text-xs text-text-muted flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" />
              Acknowledge critical issues to proceed
            </span>
          )}
          <Button
            onClick={handleProceed}
            disabled={!canProceed || isLoading || proceedPhase === 'saving' || proceedPhase === 'moving'}
            className="gap-2"
          >
            <Shield className="h-4 w-4" />
            Proceed to Anomaly Detection
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
