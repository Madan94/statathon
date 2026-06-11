'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, EyeOff, Loader2, Lock, Pencil, Plus, Share2, Sparkles, Upload as UploadIcon, type LucideIcon } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { BindingStepper } from '@/components/report-builder/binding/BindingStepper';
import { DatasetProfileCard } from '@/components/report-builder/binding/DatasetProfileCard';
import { EntityBindingCard } from '@/components/report-builder/binding/EntityBindingCard';
import { CoveragePanel } from '@/components/report-builder/binding/CoveragePanel';
import {
  bindingPhaseApi,
  reportBuilderApi,
  type BindingAction,
  type BindingConfirmPayload,
  type BindingExecutionReadyResult,
  type BindingFinalizeResult,
  type BindingRecordResult,
  type BindingStartResult,
  type ComponentDefinition,
  type ExecutionReadyStatus,
  type LearnedEntityRecord,
  type ReportTemplate,
  type ReviewedPlanComponent,
  type ReviewedPlanNode,
  type ReviewedPlanSummary,
} from '@/lib/api';

type Decision = Omit<BindingConfirmPayload, 'entity_id'>;

const STEPS = [
  { id: 'upload', label: 'Upload dataset', hint: 'CSV + template' },
  { id: 'confirm', label: 'Confirm bindings', hint: 'Review every match' },
  { id: 'coverage', label: 'Coverage gate', hint: 'Ready to generate' },
];

const EXECUTION_READY_META: Record<ExecutionReadyStatus, { label: string; badge: 'success' | 'warning' | 'danger'; wrap: string; icon: LucideIcon }> = {
  READY: {
    label: 'Ready for S4',
    badge: 'success',
    wrap: 'border-success/30 bg-success/5',
    icon: CheckCircle2,
  },
  DEGRADED: {
    label: 'Ready with warnings',
    badge: 'warning',
    wrap: 'border-warning/30 bg-warning/5',
    icon: AlertTriangle,
  },
  NOT_READY: {
    label: 'Not ready',
    badge: 'danger',
    wrap: 'border-danger/30 bg-danger/5',
    icon: AlertCircle,
  },
};

function errMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return String((detail as { message?: unknown }).message || fallback);
    }
  }
  return err instanceof Error ? err.message : fallback;
}

function decisionsFromConfirmations(confirmations: Record<string, unknown>): Record<string, Decision> {
  const next: Record<string, Decision> = {};
  Object.entries(confirmations).forEach(([entityId, raw]) => {
    if (!raw || typeof raw !== 'object') return;
    const confirmation = raw as {
      status?: string;
      columns?: string[];
      note?: string;
      sharePolicy?: 'exclusive' | 'shared';
      shareReason?: string;
    };
    if (!confirmation.status) return;
    const action: BindingAction = confirmation.sharePolicy === 'shared'
      ? 'share'
      : confirmation.status === 'overridden'
        ? 'override'
        : confirmation.status === 'rejected'
          ? 'reject'
          : 'confirm';
    next[entityId] = {
      action,
      columns: confirmation.columns,
      note: confirmation.note,
      share_policy: confirmation.sharePolicy,
      share_reason: confirmation.shareReason,
    };
  });
  return next;
}

function readinessTone(readiness: string): string {
  if (readiness === 'executable' || readiness === 'READY') return 'text-success';
  if (readiness === 'degraded' || readiness === 'DEGRADED') return 'text-warning';
  if (readiness === 'blocked' || readiness === 'BLOCKED') return 'text-danger';
  return 'text-text-muted';
}

function collectPlanContainers(nodes: ReviewedPlanNode[]): ReviewedPlanNode[] {
  return nodes.flatMap((node) => [
    ...(node.nodeType !== 'question' ? [node] : []),
    ...collectPlanContainers(node.children),
  ]);
}

function requiredEntitiesToText(requiredEntities: Array<Record<string, unknown>>): string {
  return requiredEntities
    .map((entity) => `${String(entity.entityId || entity.entityRef || '')}:${String(entity.role || 'measure')}`)
    .filter((item) => !item.startsWith(':'))
    .join(', ');
}

function parseRequiredEntities(text: string): Array<Record<string, unknown>> {
  return text.split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [entityId, role = 'measure'] = part.split(':').map((s) => s.trim());
      return { entityId, role, required: true };
    })
    .filter((entity) => entity.entityId);
}

function ReviewedPlanTree({
  nodes,
  depth = 0,
  onRename,
  onToggle,
  onEditEntities,
  onEditFormula,
  busy,
}: {
  nodes: ReviewedPlanNode[];
  depth?: number;
  onRename?: (node: ReviewedPlanNode) => void;
  onToggle?: (node: ReviewedPlanNode) => void;
  onEditEntities?: (node: ReviewedPlanNode) => void;
  onEditFormula?: (node: ReviewedPlanNode, component: ReviewedPlanComponent) => void;
  busy?: boolean;
}) {
  return (
    <div className="space-y-2">
      {nodes.map((node) => (
        <div key={node.nodeId} className={`rounded-lg border border-border bg-surface px-3 py-2 ${node.enabled === false ? 'opacity-60' : ''}`} style={{ marginLeft: depth * 12 }}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[11px] font-medium uppercase text-text-muted">{node.nodeType}</p>
              <p className="mt-0.5 line-clamp-2 text-sm font-semibold text-text">{node.title}</p>
              {node.questionId && <p className="mt-1 font-mono text-[11px] text-text-muted">{node.questionId}</p>}
            </div>
            <span className={`shrink-0 text-xs font-semibold capitalize ${readinessTone(node.readiness)}`}>
              {node.readiness}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {onRename && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onRename(node)}
                className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] font-medium text-text-muted hover:bg-surface-card disabled:opacity-50"
              >
                <Pencil className="h-3 w-3" /> Rename
              </button>
            )}
            {node.nodeType === 'question' && onToggle && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onToggle(node)}
                className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] font-medium text-text-muted hover:bg-surface-card disabled:opacity-50"
              >
                <EyeOff className="h-3 w-3" /> {node.enabled === false ? 'Enable' : 'Disable'}
              </button>
            )}
            {node.nodeType === 'question' && onEditEntities && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onEditEntities(node)}
                className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] font-medium text-text-muted hover:bg-surface-card disabled:opacity-50"
              >
                Entities
              </button>
            )}
          </div>
          {node.requiredEntities.length > 0 && (
            <p className="mt-2 line-clamp-2 text-[11px] text-text-muted">
              Required: {requiredEntitiesToText(node.requiredEntities)}
            </p>
          )}
          {node.components.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {node.components.map((component) => (
                <span key={component.componentId} className="inline-flex items-center gap-1 rounded-full bg-border px-2 py-0.5 text-[11px] text-text-muted">
                  {component.componentType}
                  {component.slotIds.length ? ` · ${component.slotIds.length} slot${component.slotIds.length > 1 ? 's' : ''}` : ''}
                  {component.formulaSpec && Object.keys(component.formulaSpec).length > 0 ? ' · formula' : ''}
                  {onEditFormula && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onEditFormula(node, component)}
                      className="ml-1 font-semibold text-primary hover:underline disabled:opacity-50"
                    >
                      Spec
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}
          {node.children.length > 0 && (
            <div className="mt-2">
              <ReviewedPlanTree nodes={node.children} depth={depth + 1} onRename={onRename} onToggle={onToggle} onEditEntities={onEditEntities} onEditFormula={onEditFormula} busy={busy} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function BindingWorkflowPage() {
  const [step, setStep] = useState(0);

  // step 0
  const [templateId, setTemplateId] = useState('tpl_plfs_annual_v1');
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [componentDefinitions, setComponentDefinitions] = useState<ComponentDefinition[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [datasetFile, setDatasetFile] = useState<File | null>(null);
  const [blueprintFile, setBlueprintFile] = useState<File | null>(null);
  const [starting, setStarting] = useState(false);

  // session
  const [session, setSession] = useState<BindingStartResult | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busyEntity, setBusyEntity] = useState<string | null>(null);
  const [addingEntity, setAddingEntity] = useState(false);
  const [newEntityColumn, setNewEntityColumn] = useState('');
  const [newEntityName, setNewEntityName] = useState('');
  const [newEntityType, setNewEntityType] = useState<'dimension' | 'measure' | 'time' | 'filter' | 'metadata'>('dimension');

  // step 2
  const [finalizing, setFinalizing] = useState(false);
  const [result, setResult] = useState<BindingFinalizeResult | null>(null);
  const [checkingReady, setCheckingReady] = useState(false);
  const [executionReady, setExecutionReady] = useState<BindingExecutionReadyResult | null>(null);
  const [planSaving, setPlanSaving] = useState(false);
  const [newPlanQuestionTopic, setNewPlanQuestionTopic] = useState('');
  const [newPlanQuestionTitle, setNewPlanQuestionTitle] = useState('');
  const [newComponentNode, setNewComponentNode] = useState('');
  const [newComponentType, setNewComponentType] = useState('narrative');
  const [promotingPlan, setPromotingPlan] = useState(false);
  const [promotionName, setPromotionName] = useState('');
  const [promotionResult, setPromotionResult] = useState<{ derivedTemplateId: string; templateId?: number | null; learnedEntityCount: number; path: string; dbWarning?: string } | null>(null);
  const [learnedEntities, setLearnedEntities] = useState<LearnedEntityRecord[]>([]);
  const [editTitleNode, setEditTitleNode] = useState<ReviewedPlanNode | null>(null);
  const [editTitleValue, setEditTitleValue] = useState('');
  const [editEntitiesNode, setEditEntitiesNode] = useState<ReviewedPlanNode | null>(null);
  const [editEntitiesValue, setEditEntitiesValue] = useState('');
  const [editFormulaTarget, setEditFormulaTarget] = useState<{ node: ReviewedPlanNode; component: ReviewedPlanComponent } | null>(null);
  const [formulaType, setFormulaType] = useState('DIRECT');
  const [formulaNumerator, setFormulaNumerator] = useState('');
  const [formulaDenominator, setFormulaDenominator] = useState('');

  const [error, setError] = useState<string | null>(null);

  const proposals = useMemo(() => session?.proposals ?? [], [session]);
  const ownershipStats = useMemo(() => {
    const entries = Object.values(session?.column_ownership?.columns ?? {});
    return {
      assigned: entries.filter((entry) => entry.owners.length > 0).length,
      locked: entries.filter((entry) => entry.locked).length,
      shared: entries.filter((entry) => entry.owners.some((owner) => owner.sharePolicy === 'shared')).length,
      conflicts: session?.column_ownership?.conflicts?.length ?? 0,
    };
  }, [session?.column_ownership]);
  const decidedCount = Object.keys(decisions).length;
  const allDecided = proposals.length > 0 && decidedCount >= proposals.length;

  const remaining = useMemo(
    () => proposals.filter((p) => !decisions[p.entityId]).length,
    [proposals, decisions]
  );
  const planContainers = useMemo(
    () => collectPlanContainers(result?.reviewed_plan?.planTree ?? []),
    [result?.reviewed_plan?.planTree]
  );
  const planNodes = useMemo(
    () => {
      const flatten = (nodes: ReviewedPlanNode[]): ReviewedPlanNode[] => nodes.flatMap((node) => [node, ...flatten(node.children)]);
      return flatten(result?.reviewed_plan?.planTree ?? []);
    },
    [result?.reviewed_plan?.planTree]
  );

  const refreshFromRecord = (record: BindingRecordResult) => {
    setSession((prev) => prev ? {
      ...prev,
      proposals: record.proposals,
      confirmations: record.confirmations,
      column_ownership: record.column_ownership,
    } : prev);
    setDecisions(decisionsFromConfirmations(record.confirmations));
    setResult(null);
    setExecutionReady(null);
  };

  const entityTypeForColumn = (columnName: string): 'dimension' | 'measure' | 'time' | 'filter' | 'metadata' => {
    const role = session?.dataset_ast.columns.find((column) => column.name === columnName)?.role;
    if (role === 'measure' || role === 'time') return role;
    if (role === 'metadata' || role === 'id') return 'metadata';
    return 'dimension';
  };

  const onStart = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!datasetFile) return;
    setStarting(true);
    setError(null);
    try {
      const res = await bindingPhaseApi.start(datasetFile, templateId.trim() || 'tpl_plfs_annual_v1', blueprintFile ?? undefined);
      setSession(res);
      setDecisions(decisionsFromConfirmations(res.confirmations));
      setResult(null);
      setExecutionReady(null);
      setStep(1);
    } catch (err) {
      setError(errMessage(err, 'Could not start the binding session'));
    } finally {
      setStarting(false);
    }
  };

  const onDecide = async (entityId: string, decision: Decision) => {
    if (!session) return;
    setBusyEntity(entityId);
    setError(null);
    try {
      const record: BindingRecordResult = await bindingPhaseApi.confirm(session.template_id, session.signature, {
        entity_id: entityId,
        ...decision,
      });
      refreshFromRecord(record);
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
        const record = await bindingPhaseApi.confirm(session.template_id, session.signature, {
          entity_id: p.entityId,
          action: 'confirm',
        });
        refreshFromRecord(record);
      } catch (err) {
        setError(errMessage(err, 'Could not confirm all bindings'));
        break;
      }
    }
    setBusyEntity(null);
  };

  const onAddEntity = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !newEntityColumn || !newEntityName.trim()) return;
    setAddingEntity(true);
    setError(null);
    try {
      const record = await bindingPhaseApi.addEntity(session.template_id, session.signature, {
        entity_name: newEntityName.trim(),
        entity_type: newEntityType,
        columns: [newEntityColumn],
        cardinality: 'oneToOne',
        note: 'officer-created entity from binder sidebar',
      });
      refreshFromRecord(record);
      setNewEntityColumn('');
      setNewEntityName('');
      setNewEntityType('dimension');
    } catch (err) {
      setError(errMessage(err, 'Could not add that entity'));
    } finally {
      setAddingEntity(false);
    }
  };

  const onFinalize = async () => {
    if (!session) return;
    setFinalizing(true);
    setError(null);
    try {
      const res = await bindingPhaseApi.finalize(session.template_id, session.signature);
      setResult(res);
      setExecutionReady(null);
      setStep(2);
    } catch (err) {
      setError(errMessage(err, 'Could not finalize the bindings'));
    } finally {
      setFinalizing(false);
    }
  };

  const onExecutionReady = async () => {
    if (!session) return;
    setCheckingReady(true);
    setError(null);
    try {
      const res = await bindingPhaseApi.executionReady(session.template_id, session.signature);
      setExecutionReady(res);
    } catch (err) {
      setError(errMessage(err, 'Could not prepare the S4 execution bundle'));
    } finally {
      setCheckingReady(false);
    }
  };

  const setReviewedPlan = (reviewedPlan: ReviewedPlanSummary) => {
    setResult((prev) => prev ? { ...prev, reviewed_plan: reviewedPlan } : prev);
    setExecutionReady(null);
  };

  const onRenamePlanNode = async (node: ReviewedPlanNode) => {
    setEditTitleNode(node);
    setEditTitleValue(node.title);
  };

  const submitRenamePlanNode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !editTitleNode || !editTitleValue.trim()) return;
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.patchReviewedPlanNode(session.template_id, session.signature, editTitleNode.nodeId, {
        title: editTitleValue.trim(),
      });
      setReviewedPlan(reviewedPlan);
      setEditTitleNode(null);
      setEditTitleValue('');
    } catch (err) {
      setError(errMessage(err, 'Could not rename that plan item'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onTogglePlanNode = async (node: ReviewedPlanNode) => {
    if (!session) return;
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.patchReviewedPlanNode(session.template_id, session.signature, node.nodeId, {
        enabled: node.enabled === false,
      });
      setReviewedPlan(reviewedPlan);
    } catch (err) {
      setError(errMessage(err, 'Could not update that question'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onEditRequiredEntities = async (node: ReviewedPlanNode) => {
    setEditEntitiesNode(node);
    setEditEntitiesValue(requiredEntitiesToText(node.requiredEntities));
  };

  const submitRequiredEntities = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !editEntitiesNode) return;
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.patchReviewedPlanNode(session.template_id, session.signature, editEntitiesNode.nodeId, {
        required_entities: parseRequiredEntities(editEntitiesValue),
      });
      setReviewedPlan(reviewedPlan);
      setEditEntitiesNode(null);
      setEditEntitiesValue('');
    } catch (err) {
      setError(errMessage(err, 'Could not update required entities'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onEditFormulaSpec = async (node: ReviewedPlanNode, component: ReviewedPlanComponent) => {
    setEditFormulaTarget({ node, component });
    setFormulaType(String(component.formulaSpec?.type || 'DIRECT'));
    setFormulaNumerator(String(component.formulaSpec?.numeratorColumn || ''));
    setFormulaDenominator(String(component.formulaSpec?.denominatorColumn || ''));
  };

  const submitFormulaSpec = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !editFormulaTarget) return;
    const formulaSpec: Record<string, unknown> = { type: formulaType.trim().toUpperCase() };
    if (formulaNumerator.trim()) formulaSpec.numeratorColumn = formulaNumerator.trim();
    if (formulaDenominator.trim()) formulaSpec.denominatorColumn = formulaDenominator.trim();
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.patchReviewedPlanComponent(
        session.template_id,
        session.signature,
        editFormulaTarget.node.nodeId,
        editFormulaTarget.component.componentId,
        { formula_spec: formulaSpec }
      );
      setReviewedPlan(reviewedPlan);
      setEditFormulaTarget(null);
    } catch (err) {
      setError(errMessage(err, 'Could not update formula spec'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onAddPlanQuestion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !newPlanQuestionTopic || !newPlanQuestionTitle.trim()) return;
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.addReviewedPlanQuestion(session.template_id, session.signature, {
        parent_node_id: newPlanQuestionTopic,
        title: newPlanQuestionTitle.trim(),
      });
      setReviewedPlan(reviewedPlan);
      setNewPlanQuestionTitle('');
    } catch (err) {
      setError(errMessage(err, 'Could not add that question'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onAddPlanComponent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !newComponentNode || !newComponentType) return;
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.addReviewedPlanComponent(session.template_id, session.signature, newComponentNode, {
        component_type: newComponentType,
        payload: {},
      });
      setReviewedPlan(reviewedPlan);
    } catch (err) {
      setError(errMessage(err, 'Could not add that component'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onPromoteReviewedPlan = async () => {
    if (!session || !result?.reviewed_plan) return;
    setPromotingPlan(true);
    setError(null);
    try {
      const promoted = await bindingPhaseApi.promoteReviewedPlan(session.template_id, session.signature, {
        name: promotionName.trim() || `${result.reviewed_plan.planId} derived`,
      });
      setPromotionResult({
        derivedTemplateId: promoted.derivedTemplateId,
        templateId: promoted.templateId,
        learnedEntityCount: promoted.learnedEntityCount,
        path: promoted.path,
        dbWarning: promoted.dbWarning,
      });
      const learned = await bindingPhaseApi.listLearnedEntities(session.template_id);
      setLearnedEntities(learned);
    } catch (err) {
      setError(errMessage(err, 'Could not promote this reviewed plan'));
    } finally {
      setPromotingPlan(false);
    }
  };

  const resetAll = () => {
    setSession(null);
    setDecisions({});
    setResult(null);
    setDatasetFile(null);
    setBlueprintFile(null);
    setExecutionReady(null);
    setStep(0);
    setError(null);
  };

  const generationHref = executionReady
    ? `/report-builder?template_id=${encodeURIComponent(executionReady.template_id)}&signature=${encodeURIComponent(session?.signature ?? '')}&binding_ast_id=${encodeURIComponent(executionReady.binding_ast_id)}&execution_status=${encodeURIComponent(executionReady.status)}`
    : '/report-builder/binding';

  useEffect(() => {
    let cancelled = false;
    setTemplatesLoading(true);
    reportBuilderApi.listTemplates()
      .then((items) => {
        if (!cancelled) setTemplates(items);
      })
      .catch(() => {
        if (!cancelled) setTemplates([]);
      })
      .finally(() => {
        if (!cancelled) setTemplatesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    bindingPhaseApi.listComponentRegistry()
      .then((items) => {
        if (!cancelled) setComponentDefinitions(items);
      })
      .catch(() => {
        if (!cancelled) setComponentDefinitions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
                  <label className="mb-1 block text-xs font-medium text-text-muted">Extracted template package</label>
                  <select
                    value={/^\d+$/.test(templateId) ? templateId : ''}
                    onChange={(e) => {
                      if (e.target.value) setTemplateId(e.target.value);
                    }}
                    className="mb-3 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                  >
                    <option value="">{templatesLoading ? 'Loading templates…' : 'Use built-in/manual template id'}</option>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name} ({template.block_count} blocks)
                      </option>
                    ))}
                  </select>
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
                    columnOwnership={session.column_ownership}
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

            <aside className="order-1 space-y-4 lg:order-2 lg:sticky lg:top-6">
              <Card title="Column allocation" description="Live ownership state from officer decisions.">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div className="rounded-lg border border-border bg-surface px-3 py-2">
                    <p className="text-[11px] uppercase text-text-muted">Assigned</p>
                    <p className="mt-1 font-semibold text-text">{ownershipStats.assigned}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-2">
                    <p className="flex items-center gap-1 text-[11px] uppercase text-text-muted">
                      <Lock className="h-3 w-3" /> Locked
                    </p>
                    <p className="mt-1 font-semibold text-text">{ownershipStats.locked}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-2">
                    <p className="flex items-center gap-1 text-[11px] uppercase text-text-muted">
                      <Share2 className="h-3 w-3" /> Shared
                    </p>
                    <p className="mt-1 font-semibold text-text">{ownershipStats.shared}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-2">
                    <p className="flex items-center gap-1 text-[11px] uppercase text-text-muted">
                      <AlertTriangle className="h-3 w-3" /> Conflicts
                    </p>
                    <p className="mt-1 font-semibold text-text">{ownershipStats.conflicts}</p>
                  </div>
                </div>
                {ownershipStats.conflicts > 0 && (
                  <p className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-text-muted">
                    Resolve duplicate exclusive columns before freezing this binding.
                  </p>
                )}
              </Card>
              <Card title="Add entity" description="Create a missing template entity from a dataset column.">
                <form onSubmit={onAddEntity} className="space-y-3">
                  <div>
                    <label className="mb-1 block text-[11px] font-medium uppercase text-text-muted">Column</label>
                    <select
                      value={newEntityColumn}
                      onChange={(e) => {
                        const column = e.target.value;
                        setNewEntityColumn(column);
                        setNewEntityType(entityTypeForColumn(column));
                        if (!newEntityName.trim()) setNewEntityName(column.replace(/_/g, ' '));
                      }}
                      className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-accent/30"
                    >
                      <option value="">Select column</option>
                      {session.dataset_ast.columns.map((column) => (
                        <option key={column.name} value={column.name}>{column.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] font-medium uppercase text-text-muted">Entity name</label>
                    <input
                      value={newEntityName}
                      onChange={(e) => setNewEntityName(e.target.value)}
                      placeholder="e.g. Worker Population Ratio"
                      className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-accent/30"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] font-medium uppercase text-text-muted">Entity type</label>
                    <select
                      value={newEntityType}
                      onChange={(e) => setNewEntityType(e.target.value as typeof newEntityType)}
                      className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-accent/30"
                    >
                      <option value="dimension">Dimension</option>
                      <option value="measure">Measure</option>
                      <option value="time">Time</option>
                      <option value="filter">Filter</option>
                      <option value="metadata">Metadata</option>
                    </select>
                  </div>
                  <Button type="submit" size="sm" className="w-full" disabled={addingEntity || !newEntityColumn || !newEntityName.trim()}>
                    {addingEntity ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                    Add and bind entity
                  </Button>
                </form>
              </Card>
              <DatasetProfileCard dataset={session.dataset_ast} />
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
            {result.reviewed_plan && (
              <Card title="Reviewed plan" description="Officer-reviewed planning layer prepared from these bindings.">
                <div className="grid gap-3 rounded-xl border border-border bg-surface p-4 text-sm sm:grid-cols-4">
                  <div className="sm:col-span-2">
                    <p className="text-[11px] uppercase text-text-muted">Plan id</p>
                    <p className="mt-1 truncate font-mono text-xs font-semibold text-text">{result.reviewed_plan.planId}</p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase text-text-muted">Status</p>
                    <p className="mt-1 font-semibold text-text">{result.reviewed_plan.status}</p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase text-text-muted">Tree</p>
                    <p className="mt-1 font-semibold text-text">
                      {result.reviewed_plan.topicCount} topics · {result.reviewed_plan.questionCount} questions
                    </p>
                  </div>
                  <div className="sm:col-span-2">
                    <p className="text-[11px] uppercase text-text-muted">Slots</p>
                    <p className="mt-1 font-semibold text-text">
                      {result.reviewed_plan.semanticSlotCount} semantic · {result.reviewed_plan.virtualSlotCount} virtual
                    </p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface p-3">
                  <div>
                    <p className="text-xs font-semibold text-text">Derived template promotion</p>
                    <p className="mt-0.5 text-xs text-text-muted">Save this reviewed plan and learned entities as a reusable sidecar.</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={promotionName}
                      onChange={(e) => setPromotionName(e.target.value)}
                      placeholder="Derived template name"
                      className="w-52 rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                    />
                    <Button size="sm" variant="outline" disabled={promotingPlan} onClick={onPromoteReviewedPlan}>
                      {promotingPlan ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                      Promote
                    </Button>
                  </div>
                </div>
                {promotionResult && (
                  <div className="mt-2 rounded-lg border border-success/30 bg-success/5 px-3 py-2 text-xs text-text-muted">
                    <p>
                      Promoted <span className="font-mono text-text">{promotionResult.derivedTemplateId}</span>
                      {promotionResult.templateId ? <> · DB template <span className="font-mono text-text">{promotionResult.templateId}</span></> : null}
                      {' '}· {promotionResult.learnedEntityCount} learned entities
                    </p>
                    {promotionResult.dbWarning && <p className="mt-1 text-warning">DB promotion warning: {promotionResult.dbWarning}</p>}
                    {learnedEntities.length > 0 && (
                      <p className="mt-1">
                        Learned: {learnedEntities.slice(0, 4).map((entity) => entity.entityName).join(', ')}
                        {learnedEntities.length > 4 ? ` +${learnedEntities.length - 4}` : ''}
                      </p>
                    )}
                  </div>
                )}
                {result.reviewed_plan.virtualSlots?.length > 0 && (
                  <div className="mt-3 rounded-xl border border-border bg-surface p-3">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Virtual slots</p>
                    <div className="space-y-1.5">
                      {result.reviewed_plan.virtualSlots.slice(0, 8).map((slot, index) => (
                        <p key={`${String(slot.slotId || index)}`} className="truncate font-mono text-[11px] text-text-muted">
                          {String(slot.slotId || 'slot')} → {String(slot.componentId || 'component')} · {String(slot.layoutIntent || 'layout')}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
                {result.reviewed_plan.planTree?.length > 0 && (
                  <div className="mt-4 rounded-xl border border-border bg-surface-card p-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Question plan bundle</p>
                      <p className="text-xs text-text-muted">
                        {planSaving ? 'Saving…' : `${result.reviewed_plan.componentCount} components`}
                      </p>
                    </div>
                    {editTitleNode && (
                      <form onSubmit={submitRenamePlanNode} className="mb-3 grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_auto_auto]">
                        <input
                          value={editTitleValue}
                          onChange={(e) => setEditTitleValue(e.target.value)}
                          className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                        />
                        <Button type="submit" size="sm" disabled={planSaving || !editTitleValue.trim()}>Save rename</Button>
                        <Button type="button" variant="ghost" size="sm" onClick={() => setEditTitleNode(null)}>Cancel</Button>
                      </form>
                    )}
                    {editEntitiesNode && (
                      <form onSubmit={submitRequiredEntities} className="mb-3 grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_auto_auto]">
                        <input
                          value={editEntitiesValue}
                          onChange={(e) => setEditEntitiesValue(e.target.value)}
                          placeholder="ent_wpr:measure, ent_sector:grouping"
                          className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                        />
                        <Button type="submit" size="sm" disabled={planSaving}>Save entities</Button>
                        <Button type="button" variant="ghost" size="sm" onClick={() => setEditEntitiesNode(null)}>Cancel</Button>
                      </form>
                    )}
                    {editFormulaTarget && (
                      <form onSubmit={submitFormulaSpec} className="mb-3 grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[0.8fr_1fr_1fr_auto_auto]">
                        <select
                          value={formulaType}
                          onChange={(e) => setFormulaType(e.target.value)}
                          className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                        >
                          <option value="DIRECT">DIRECT</option>
                          <option value="SHARE">SHARE</option>
                          <option value="RATE">RATE</option>
                          <option value="RATIO">RATIO</option>
                          <option value="GROWTH">GROWTH</option>
                          <option value="INDEX">INDEX</option>
                        </select>
                        <input
                          value={formulaNumerator}
                          onChange={(e) => setFormulaNumerator(e.target.value)}
                          placeholder="Numerator/source column"
                          className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                        />
                        <input
                          value={formulaDenominator}
                          onChange={(e) => setFormulaDenominator(e.target.value)}
                          placeholder="Denominator column"
                          className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                        />
                        <Button type="submit" size="sm" disabled={planSaving}>Save spec</Button>
                        <Button type="button" variant="ghost" size="sm" onClick={() => setEditFormulaTarget(null)}>Cancel</Button>
                      </form>
                    )}
                    <ReviewedPlanTree
                      nodes={result.reviewed_plan.planTree}
                      onRename={onRenamePlanNode}
                      onToggle={onTogglePlanNode}
                      onEditEntities={onEditRequiredEntities}
                      onEditFormula={onEditFormulaSpec}
                      busy={planSaving}
                    />
                    <form onSubmit={onAddPlanQuestion} className="mt-4 grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_1.5fr_auto]">
                      <select
                        value={newPlanQuestionTopic}
                        onChange={(e) => setNewPlanQuestionTopic(e.target.value)}
                        className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                      >
                        <option value="">Choose topic</option>
                        {planContainers.map((node) => (
                          <option key={node.nodeId} value={node.nodeId}>{node.title}</option>
                        ))}
                      </select>
                      <input
                        value={newPlanQuestionTitle}
                        onChange={(e) => setNewPlanQuestionTitle(e.target.value)}
                        placeholder="Add manual question"
                        className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                      />
                      <Button type="submit" size="sm" disabled={planSaving || !newPlanQuestionTopic || !newPlanQuestionTitle.trim()}>
                        <Plus className="h-4 w-4" /> Add question
                      </Button>
                    </form>
                    <form onSubmit={onAddPlanComponent} className="mt-3 grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_1fr_auto]">
                      <select
                        value={newComponentNode}
                        onChange={(e) => setNewComponentNode(e.target.value)}
                        className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                      >
                        <option value="">Attach to item</option>
                        {planNodes.map((node) => (
                          <option key={node.nodeId} value={node.nodeId}>{node.title}</option>
                        ))}
                      </select>
                      <select
                        value={newComponentType}
                        onChange={(e) => setNewComponentType(e.target.value)}
                        className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                      >
                        {(componentDefinitions.length ? componentDefinitions : [{ componentType: 'narrative', label: 'Narrative paragraph' } as ComponentDefinition]).map((definition) => (
                          <option key={definition.componentType} value={definition.componentType}>{definition.label}</option>
                        ))}
                      </select>
                      <Button type="submit" size="sm" disabled={planSaving || !newComponentNode || !newComponentType}>
                        <Plus className="h-4 w-4" /> Add component
                      </Button>
                    </form>
                  </div>
                )}
              </Card>
            )}
            {executionReady && (() => {
              const meta = EXECUTION_READY_META[executionReady.status] ?? EXECUTION_READY_META.NOT_READY;
              const Icon = meta.icon;
              const readyToOpen = executionReady.status === 'READY' || executionReady.status === 'DEGRADED';
              return (
                <Card title="S4 execution handoff" description="Canonical runtime bundle prepared from this reviewed binding.">
                  <div className={`rounded-xl border p-4 ${meta.wrap}`}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex min-w-0 gap-3">
                        <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-semibold text-text">{meta.label}</p>
                            <Badge variant={meta.badge}>{executionReady.status}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-text-muted">
                            Contract {executionReady.contract_version} · Binding AST{' '}
                            <span className="font-mono text-text">{executionReady.binding_ast_id}</span>
                          </p>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-right text-xs sm:grid-cols-3">
                        <div>
                          <p className="font-semibold text-text">{executionReady.plans.length}</p>
                          <p className="text-text-muted">plans</p>
                        </div>
                        <div>
                          <p className="font-semibold text-text">{executionReady.blocked_questions.length}</p>
                          <p className="text-text-muted">blocked</p>
                        </div>
                        <div>
                          <p className="font-semibold text-text">{Object.keys(executionReady.lineage_index ?? {}).length}</p>
                          <p className="text-text-muted">lineage</p>
                        </div>
                      </div>
                    </div>
                    {executionReady.status === 'NOT_READY' && (
                      <p className="mt-3 rounded-lg border border-danger/20 bg-surface px-3 py-2 text-xs text-text-muted">
                        This binding can be saved for review, but S4 should not generate from it until blocked questions and readiness errors are resolved.
                      </p>
                    )}
                    {readyToOpen && (
                      <p className="mt-3 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-muted">
                        The execution bundle is prepared. The next screen will receive the template id, dataset signature, binding AST id, and readiness status as handoff parameters.
                      </p>
                    )}
                  </div>
                </Card>
              );
            })()}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <Button variant="outline" size="sm" onClick={() => setStep(1)}>
                <ArrowLeft className="h-4 w-4" /> Back to bindings
              </Button>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={resetAll} className="text-text-muted">
                  Bind another dataset
                </Button>
                {!executionReady ? (
                  <Button onClick={onExecutionReady} disabled={checkingReady}>
                    {checkingReady ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" /> Preparing S4 bundle…
                      </>
                    ) : (
                      <>
                        Prepare S4 bundle <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>
                ) : executionReady.status === 'NOT_READY' ? (
                  <Button disabled>
                    Not ready for generation <ArrowRight className="h-4 w-4" />
                  </Button>
                ) : (
                  <Link href={generationHref}>
                    <Button>
                      Open generation workspace <ArrowRight className="h-4 w-4" />
                    </Button>
                  </Link>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
