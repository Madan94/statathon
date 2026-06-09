'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ArrowRight, Loader2, Sparkles, Upload as UploadIcon } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { BindingStepper } from '@/components/report-builder/binding/BindingStepper';
import { DatasetProfileCard } from '@/components/report-builder/binding/DatasetProfileCard';
import { EntityBindingCard } from '@/components/report-builder/binding/EntityBindingCard';
import { CoveragePanel } from '@/components/report-builder/binding/CoveragePanel';
import {
  bindingPhaseApi,
  type BindingAction,
  type BindingFinalizeResult,
  type BindingStartResult,
} from '@/lib/api';

type Decision = { action: BindingAction; columns?: string[] };

const STEPS = [
  { id: 'upload', label: 'Upload dataset', hint: 'CSV + template' },
  { id: 'confirm', label: 'Confirm bindings', hint: 'Review every match' },
  { id: 'coverage', label: 'Coverage gate', hint: 'Ready to generate' },
];

function errMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (detail) return detail;
  }
  return err instanceof Error ? err.message : fallback;
}

export default function BindingWorkflowPage() {
  const [step, setStep] = useState(0);

  // step 0
  const [templateId, setTemplateId] = useState('tpl_plfs_annual_v1');
  const [datasetFile, setDatasetFile] = useState<File | null>(null);
  const [blueprintFile, setBlueprintFile] = useState<File | null>(null);
  const [starting, setStarting] = useState(false);

  // session
  const [session, setSession] = useState<BindingStartResult | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busyEntity, setBusyEntity] = useState<string | null>(null);

  // step 2
  const [finalizing, setFinalizing] = useState(false);
  const [result, setResult] = useState<BindingFinalizeResult | null>(null);

  const [error, setError] = useState<string | null>(null);

  const proposals = useMemo(() => session?.proposals ?? [], [session]);
  const decidedCount = Object.keys(decisions).length;
  const allDecided = proposals.length > 0 && decidedCount >= proposals.length;

  const remaining = useMemo(
    () => proposals.filter((p) => !decisions[p.entityId]).length,
    [proposals, decisions]
  );

  const onStart = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!datasetFile) return;
    setStarting(true);
    setError(null);
    try {
      const res = await bindingPhaseApi.start(datasetFile, templateId.trim() || 'tpl_plfs_annual_v1', blueprintFile ?? undefined);
      setSession(res);
      setDecisions({});
      setResult(null);
      setStep(1);
    } catch (err) {
      setError(errMessage(err, 'Could not start the binding session'));
    } finally {
      setStarting(false);
    }
  };

  const onDecide = async (entityId: string, decision: Decision) => {
    if (!session) return;
    // "Change" re-opens a decided entity (sentinel: confirm with undefined columns).
    if (decision.action === 'confirm' && decision.columns === undefined && decisions[entityId]) {
      setDecisions((prev) => {
        const next = { ...prev };
        delete next[entityId];
        return next;
      });
      return;
    }
    setBusyEntity(entityId);
    setError(null);
    try {
      await bindingPhaseApi.confirm(session.template_id, session.signature, {
        entity_id: entityId,
        action: decision.action,
        columns: decision.columns,
      });
      setDecisions((prev) => ({ ...prev, [entityId]: decision }));
    } catch (err) {
      setError(errMessage(err, 'Could not record that decision'));
    } finally {
      setBusyEntity(null);
    }
  };

  const confirmAllRemaining = async () => {
    if (!session) return;
    setError(null);
    for (const p of proposals) {
      if (decisions[p.entityId]) continue;
      if (!p.columns[0]) continue; // can't auto-confirm an unmatched entity
      setBusyEntity(p.entityId);
      try {
        await bindingPhaseApi.confirm(session.template_id, session.signature, {
          entity_id: p.entityId,
          action: 'confirm',
        });
        setDecisions((prev) => ({ ...prev, [p.entityId]: { action: 'confirm' } }));
      } catch (err) {
        setError(errMessage(err, 'Could not confirm all bindings'));
        break;
      }
    }
    setBusyEntity(null);
  };

  const onFinalize = async () => {
    if (!session) return;
    setFinalizing(true);
    setError(null);
    try {
      const res = await bindingPhaseApi.finalize(session.template_id, session.signature);
      setResult(res);
      setStep(2);
    } catch (err) {
      setError(errMessage(err, 'Could not finalize the bindings'));
    } finally {
      setFinalizing(false);
    }
  };

  const resetAll = () => {
    setSession(null);
    setDecisions({});
    setResult(null);
    setDatasetFile(null);
    setBlueprintFile(null);
    setStep(0);
    setError(null);
  };

  return (
    <>
      <PageHeader
        title="Bind dataset to template"
        description="Map your dataset's columns to the report's expected entities — one confirmation at a time — then check the coverage gate before generating."
        actions={
          <Link href="/report-builder">
            <Button variant="outline" size="sm">
              <ArrowLeft className="h-4 w-4" /> Report Builder
            </Button>
          </Link>
        }
      />

      <div className="mx-auto max-w-3xl">
        <BindingStepper steps={STEPS} current={step} className="mb-8" />
      </div>

      <div className="space-y-6">
        {error && <Alert variant="error">{error}</Alert>}

        {/* ───────────────────────── Step 0 — upload ───────────────────────── */}
        {step === 0 && (
          <div className="mx-auto max-w-2xl">
            <Card
              title="Upload your dataset"
              description="We profile every column, then propose how each maps to the template's entities."
            >
              <form onSubmit={onStart} className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-text-muted">Template ID</label>
                  <input
                    type="text"
                    value={templateId}
                    onChange={(e) => setTemplateId(e.target.value)}
                    placeholder="tpl_plfs_annual_v1"
                    className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                  <p className="mt-1 text-xs text-text-muted">
                    Built-in ids (<span className="font-mono">tpl_plfs_annual_v1</span>, <span className="font-mono">gold</span>) use the
                    bundled PLFS blueprint. Otherwise attach a blueprint below.
                  </p>
                </div>

                <label
                  htmlFor="binding-dataset"
                  className="block cursor-pointer rounded-xl border-2 border-dashed border-border p-6 text-center transition-colors hover:border-accent/50"
                >
                  <UploadIcon className="mx-auto mb-2 h-6 w-6 text-text-muted" />
                  <p className="text-sm font-medium text-text">
                    {datasetFile ? datasetFile.name : 'Click to choose a CSV dataset'}
                  </p>
                  <p className="mt-1 text-xs text-text-muted">CSV only.</p>
                </label>
                <input
                  id="binding-dataset"
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={(e) => setDatasetFile(e.target.files?.[0] ?? null)}
                />

                <div>
                  <label
                    htmlFor="binding-blueprint"
                    className="flex cursor-pointer items-center justify-between rounded-lg border border-border bg-surface px-3 py-2 text-sm transition-colors hover:border-accent/50"
                  >
                    <span className="text-text-muted">
                      {blueprintFile ? blueprintFile.name : 'Optional: attach a blueprint.json'}
                    </span>
                    <span className="text-xs font-medium text-primary">Browse</span>
                  </label>
                  <input
                    id="binding-blueprint"
                    type="file"
                    accept="application/json,.json"
                    className="hidden"
                    onChange={(e) => setBlueprintFile(e.target.files?.[0] ?? null)}
                  />
                </div>

                <Button type="submit" disabled={starting || !datasetFile} className="w-full">
                  {starting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Profiling &amp; proposing…
                    </>
                  ) : (
                    <>
                      Profile &amp; propose bindings <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </Button>
              </form>
            </Card>
          </div>
        )}

        {/* ──────────────────────── Step 1 — confirm ──────────────────────── */}
        {step === 1 && session && (
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div className="order-2 space-y-4 lg:order-1">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-text">Confirm each binding</h2>
                  <p className="text-sm text-text-muted">
                    {remaining > 0
                      ? `${remaining} of ${proposals.length} still need a decision.`
                      : 'All bindings reviewed — finalize to check coverage.'}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={confirmAllRemaining}
                  disabled={!!busyEntity || remaining === 0}
                >
                  <Sparkles className="h-4 w-4" /> Confirm all proposed
                </Button>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {proposals.map((b) => (
                  <EntityBindingCard
                    key={b.entityId}
                    binding={b}
                    columns={session.dataset_ast.columns}
                    decided={decisions[b.entityId]}
                    busy={busyEntity === b.entityId}
                    onDecide={onDecide}
                  />
                ))}
              </div>

              <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
                <Button variant="ghost" size="sm" onClick={resetAll} className="text-text-muted">
                  <ArrowLeft className="h-4 w-4" /> Start over
                </Button>
                <Button onClick={onFinalize} disabled={finalizing || !allDecided}>
                  {finalizing ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Resolving questions…
                    </>
                  ) : (
                    <>
                      Check coverage <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </Button>
              </div>
            </div>

            <aside className="order-1 lg:order-2">
              <DatasetProfileCard dataset={session.dataset_ast} className="lg:sticky lg:top-6" />
            </aside>
          </div>
        )}

        {/* ─────────────────────── Step 2 — coverage ─────────────────────── */}
        {step === 2 && result && (
          <div className="mx-auto max-w-3xl space-y-6">
            <CoveragePanel
              coverage={result.coverage}
              questionBindings={result.question_bindings}
              hasErrors={result.has_errors}
            />
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <Button variant="outline" size="sm" onClick={() => setStep(1)}>
                <ArrowLeft className="h-4 w-4" /> Back to bindings
              </Button>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={resetAll} className="text-text-muted">
                  Bind another dataset
                </Button>
                <Link href="/report-builder">
                  <Button disabled={result.has_errors}>
                    Continue to generate <ArrowRight className="h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
