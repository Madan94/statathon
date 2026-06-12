'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Loader2, Lock, Plus, Share2, Sparkles, Upload as UploadIcon, type LucideIcon } from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { BindingStepper } from '@/components/report-builder/binding/BindingStepper';
import { DatasetProfileCard } from '@/components/report-builder/binding/DatasetProfileCard';
import { CoveragePanel } from '@/components/report-builder/binding/CoveragePanel';
import { StructureCanvas } from '@/components/report-builder/binding/StructureCanvas';
import { EntityMatrixPanel, type EntityDecision } from '@/components/report-builder/binding/EntityMatrixPanel';
import { TemplatePackagePicker } from '@/components/report-builder/binding/TemplatePackagePicker';
import {
  bindingPhaseApi,
  type BindingAction,
  type BindingExecutionReadyResult,
  type BindingFinalizeResult,
  type BindingRecordResult,
  type BindingStartResult,
  type BindingTemplatePackage,
  type BindingWorkspace,
  type BindingWorkspaceIssue,
  type ComponentDefinition,
  type ExecutionReadyStatus,
  type LearnedEntityRecord,
  type ReviewedPlanComponent,
  type ReviewedPlanNode,
  type ReviewedPlanSummary,
} from '@/lib/api';

type Decision = EntityDecision;
type WorkbenchMode = 'overview' | 'entities' | 'questions' | 'columns' | 'issues' | 'handoff';

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

function defaultComponentPayload(node: ReviewedPlanNode | undefined, componentType: string): Record<string, unknown> {
  const requiredEntities = node?.requiredEntities ?? [];
  if (componentType === 'chart' || componentType === 'table') {
    return {
      requiredEntities,
      analyticsSpec: {
        operation: 'group_aggregate',
        recommendedBy: 'binder_workbench_manual_add',
      },
    };
  }
  if (componentType === 'formula_metric') {
    return {
      requiredEntities,
      analyticsSpec: {
        recommendedBy: 'binder_workbench_manual_add',
      },
      formulaSpec: { type: 'DIRECT' },
    };
  }
  return requiredEntities.length ? { requiredEntities } : {};
}

export default function BindingWorkflowPage() {
  const [step, setStep] = useState(0);

  // step 0
  const [templateId, setTemplateId] = useState('tpl_plfs_annual_v1');
  const [templatePackages, setTemplatePackages] = useState<BindingTemplatePackage[]>([]);
  const [componentDefinitions, setComponentDefinitions] = useState<ComponentDefinition[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [datasetFile, setDatasetFile] = useState<File | null>(null);
  const [blueprintFile, setBlueprintFile] = useState<File | null>(null);
  const [starting, setStarting] = useState(false);

  // session
  const [session, setSession] = useState<BindingStartResult | null>(null);
  const [workspace, setWorkspace] = useState<BindingWorkspace | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workbenchMode, setWorkbenchMode] = useState<WorkbenchMode>('overview');
  const [focusedEntityId, setFocusedEntityId] = useState<string | null>(null);
  const [focusedQuestionId, setFocusedQuestionId] = useState<string | null>(null);
  const [focusedComponentId, setFocusedComponentId] = useState<string | null>(null);
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
  const [editComponentEntitiesTarget, setEditComponentEntitiesTarget] = useState<{ node: ReviewedPlanNode; component: ReviewedPlanComponent } | null>(null);
  const [editComponentEntitiesValue, setEditComponentEntitiesValue] = useState('');
  const [editFormulaTarget, setEditFormulaTarget] = useState<{ node: ReviewedPlanNode; component: ReviewedPlanComponent } | null>(null);
  const [formulaType, setFormulaType] = useState('DIRECT');
  const [formulaNumerator, setFormulaNumerator] = useState('');
  const [formulaDenominator, setFormulaDenominator] = useState('');
  const [editAnalyticsTarget, setEditAnalyticsTarget] = useState<{ node: ReviewedPlanNode; component: ReviewedPlanComponent } | null>(null);
  const [analyticsSpecValue, setAnalyticsSpecValue] = useState('');

  const [error, setError] = useState<string | null>(null);

  const proposals = useMemo(() => session?.proposals ?? [], [session]);
  const workspaceIssues = workspace?.issues ?? [];
  const selectedPackage = useMemo(
    () => templatePackages.find((pkg) => pkg.template_id === templateId) ?? null,
    [templatePackages, templateId]
  );
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
  const currentReviewedPlan = result?.reviewed_plan ?? workspace?.reviewed_plan ?? null;
  const planContainers = useMemo(
    () => collectPlanContainers(currentReviewedPlan?.planTree ?? []),
    [currentReviewedPlan?.planTree]
  );
  const planNodes = useMemo(
    () => {
      const flatten = (nodes: ReviewedPlanNode[]): ReviewedPlanNode[] => nodes.flatMap((node) => [node, ...flatten(node.children)]);
      return flatten(currentReviewedPlan?.planTree ?? []);
    },
    [currentReviewedPlan?.planTree]
  );

  const loadWorkspace = async (template: string, signature: string) => {
    setWorkspaceLoading(true);
    try {
      const next = await bindingPhaseApi.getWorkspace(template, signature);
      setWorkspace(next);
    } finally {
      setWorkspaceLoading(false);
    }
  };

  const refreshFromRecord = async (record: BindingRecordResult) => {
    setSession((prev) => prev ? {
      ...prev,
      proposals: record.proposals,
      confirmations: record.confirmations,
      column_ownership: record.column_ownership,
    } : prev);
    setDecisions(decisionsFromConfirmations(record.confirmations));
    setResult(null);
    setExecutionReady(null);
    await loadWorkspace(record.template_id, record.signature);
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
      setWorkbenchMode('overview');
      await loadWorkspace(res.template_id, res.signature);
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
      await refreshFromRecord(record);
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
        await refreshFromRecord(record);
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
      await refreshFromRecord(record);
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
      await loadWorkspace(session.template_id, session.signature);
      setWorkbenchMode('questions');
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
      await loadWorkspace(session.template_id, session.signature);
      setWorkbenchMode('handoff');
    } catch (err) {
      setError(errMessage(err, 'Could not prepare the S3.5 handoff bundle'));
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
      await loadWorkspace(session.template_id, session.signature);
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
      await loadWorkspace(session.template_id, session.signature);
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
      await loadWorkspace(session.template_id, session.signature);
      setEditEntitiesNode(null);
      setEditEntitiesValue('');
    } catch (err) {
      setError(errMessage(err, 'Could not update required entities'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onEditComponentRequiredEntities = async (node: ReviewedPlanNode, component: ReviewedPlanComponent) => {
    setEditComponentEntitiesTarget({ node, component });
    setEditComponentEntitiesValue(requiredEntitiesToText(component.requiredEntities));
  };

  const submitComponentRequiredEntities = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !editComponentEntitiesTarget) return;
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.patchReviewedPlanComponent(
        session.template_id,
        session.signature,
        editComponentEntitiesTarget.node.nodeId,
        editComponentEntitiesTarget.component.componentId,
        { required_entities: parseRequiredEntities(editComponentEntitiesValue) }
      );
      setReviewedPlan(reviewedPlan);
      await loadWorkspace(session.template_id, session.signature);
      setEditComponentEntitiesTarget(null);
      setEditComponentEntitiesValue('');
    } catch (err) {
      setError(errMessage(err, 'Could not update component entities'));
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

  const onEditAnalyticsSpec = async (node: ReviewedPlanNode, component: ReviewedPlanComponent) => {
    setEditAnalyticsTarget({ node, component });
    setAnalyticsSpecValue(JSON.stringify(component.analyticsSpec || {}, null, 2));
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
      await loadWorkspace(session.template_id, session.signature);
      setEditFormulaTarget(null);
    } catch (err) {
      setError(errMessage(err, 'Could not update formula spec'));
    } finally {
      setPlanSaving(false);
    }
  };

  const submitAnalyticsSpec = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !editAnalyticsTarget) return;
    let analyticsSpec: Record<string, unknown>;
    try {
      analyticsSpec = analyticsSpecValue.trim() ? JSON.parse(analyticsSpecValue) : {};
    } catch {
      setError('Analytics spec must be valid JSON');
      return;
    }
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.patchReviewedPlanComponent(
        session.template_id,
        session.signature,
        editAnalyticsTarget.node.nodeId,
        editAnalyticsTarget.component.componentId,
        { analytics_spec: analyticsSpec }
      );
      setReviewedPlan(reviewedPlan);
      await loadWorkspace(session.template_id, session.signature);
      setEditAnalyticsTarget(null);
      setAnalyticsSpecValue('');
    } catch (err) {
      setError(errMessage(err, 'Could not update analytics spec'));
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
      await loadWorkspace(session.template_id, session.signature);
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
    const targetNode = planNodes.find((node) => node.nodeId === newComponentNode);
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.addReviewedPlanComponent(session.template_id, session.signature, newComponentNode, {
        component_type: newComponentType,
        payload: defaultComponentPayload(targetNode, newComponentType),
      });
      setReviewedPlan(reviewedPlan);
      await loadWorkspace(session.template_id, session.signature);
    } catch (err) {
      setError(errMessage(err, 'Could not add that component'));
    } finally {
      setPlanSaving(false);
    }
  };

  const onAddRecommendedComponent = async (nodeId: string, componentType: string, payload: Record<string, unknown> = {}) => {
    if (!session || !nodeId || !componentType) return;
    setPlanSaving(true);
    setError(null);
    try {
      const reviewedPlan = await bindingPhaseApi.addReviewedPlanComponent(session.template_id, session.signature, nodeId, {
        component_type: componentType,
        payload,
      });
      setReviewedPlan(reviewedPlan);
      setNewComponentNode(nodeId);
      setNewComponentType(componentType);
      await loadWorkspace(session.template_id, session.signature);
    } catch (err) {
      setError(errMessage(err, 'Could not add that recommended component'));
    } finally {
      setPlanSaving(false);
    }
  };

  const loadComponentRecommendations = useCallback(async (nodeId: string) => {
    if (!session) return [];
    return bindingPhaseApi.listComponentRecommendations(session.template_id, session.signature, nodeId);
  }, [session]);

  const onPromoteReviewedPlan = async () => {
    if (!session || !currentReviewedPlan) return;
    setPromotingPlan(true);
    setError(null);
    try {
      const promoted = await bindingPhaseApi.promoteReviewedPlan(session.template_id, session.signature, {
        name: promotionName.trim() || `${currentReviewedPlan.planId} derived`,
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
    setWorkspace(null);
    setWorkbenchMode('overview');
    setFocusedEntityId(null);
    setFocusedQuestionId(null);
    setFocusedComponentId(null);
    setEditComponentEntitiesTarget(null);
    setEditComponentEntitiesValue('');
    setStep(0);
    setError(null);
  };

  const focusIssue = (issue: BindingWorkspaceIssue) => {
    setFocusedEntityId(issue.entityId || null);
    setFocusedQuestionId(issue.questionId || null);
    setFocusedComponentId(issue.componentId || null);
    if (issue.targetMode && ['overview', 'entities', 'questions', 'columns', 'issues', 'handoff'].includes(issue.targetMode)) {
      setWorkbenchMode(issue.targetMode as WorkbenchMode);
      return;
    }
    if (issue.questionId) {
      setWorkbenchMode('questions');
      return;
    }
    if (issue.entityId) {
      setWorkbenchMode('entities');
      return;
    }
    if (issue.column) {
      setWorkbenchMode('columns');
      return;
    }
    setWorkbenchMode('issues');
  };

  const generationHref = executionReady
    ? `/report-builder?template_id=${encodeURIComponent(executionReady.template_id)}&signature=${encodeURIComponent(session?.signature ?? '')}&binding_ast_id=${encodeURIComponent(executionReady.binding_ast_id)}&execution_status=${encodeURIComponent(executionReady.status)}`
    : '/report-builder/binding';

  useEffect(() => {
    let cancelled = false;
    setTemplatesLoading(true);
    bindingPhaseApi.listTemplatePackages()
      .then((items) => {
        if (!cancelled) setTemplatePackages(items);
      })
      .catch(() => {
        if (!cancelled) setTemplatePackages([]);
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

  const phase = workspace?.phase_statuses ?? {};
  const phaseStatus = (key: string, fallback: 'Ready' | 'Review' | 'Blocked' | 'Open') =>
    (phase[key]?.status as 'Ready' | 'Review' | 'Blocked' | 'Open' | undefined) ?? fallback;
  const phaseHint = (key: string, fallback: string) => phase[key]?.message || fallback;

  const handoffStatus: 'Ready' | 'Review' | 'Blocked' | 'Open' = executionReady?.status === 'READY'
    ? 'Ready'
    : executionReady?.status === 'DEGRADED'
      ? 'Review'
      : phaseStatus('handoff', currentReviewedPlan ? 'Review' : 'Blocked');
  const handoffHint = executionReady
    ? `Bundle ${executionReady.status}: ${executionReady.plans.length} plans, ${executionReady.blocked_questions.length} blocked`
    : phaseHint('handoff', 'Not prepared');

  const workbenchModes: Array<{ id: WorkbenchMode; label: string; hint: string; status: 'Ready' | 'Review' | 'Blocked' | 'Open' }> = [
    { id: 'overview', label: 'Overview', hint: phaseHint('overview', 'Session health'), status: phaseStatus('overview', 'Open') },
    { id: 'entities', label: 'Entity matching', hint: phaseHint('entities', `${remaining} pending`), status: phaseStatus('entities', remaining === 0 ? 'Ready' : 'Review') },
    { id: 'questions', label: 'Question plan', hint: phaseHint('questions', currentReviewedPlan ? `${currentReviewedPlan.questionCount} questions` : 'Finalize first'), status: phaseStatus('questions', currentReviewedPlan ? 'Ready' : allDecided ? 'Review' : 'Blocked') },
    { id: 'columns', label: 'Dataset columns', hint: phaseHint('columns', `${session?.dataset_ast.columns.length ?? 0} columns`), status: phaseStatus('columns', ownershipStats.conflicts > 0 ? 'Blocked' : 'Ready') },
    { id: 'issues', label: 'Issues', hint: phaseHint('issues', `${workspaceIssues.length} open`), status: phaseStatus('issues', workspaceIssues.length ? 'Review' : 'Ready') },
    { id: 'handoff', label: 'S3.5 handoff', hint: handoffHint, status: handoffStatus },
  ];

  const packageForWorkbench = workspace?.template_package ?? selectedPackage;
  const datasetForWorkbench = workspace?.dataset_ast ?? session?.dataset_ast;

  const renderPlanEditors = () => (
    <>
      {editTitleNode && (
        <form onSubmit={submitRenamePlanNode} className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_auto_auto]">
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
        <form onSubmit={submitRequiredEntities} className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_auto_auto]">
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
      {editComponentEntitiesTarget && (
        <form onSubmit={submitComponentRequiredEntities} className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_auto_auto]">
          <input
            value={editComponentEntitiesValue}
            onChange={(e) => setEditComponentEntitiesValue(e.target.value)}
            placeholder="ent_wpr:measure, ent_sector:grouping"
            className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
          />
          <Button type="submit" size="sm" disabled={planSaving}>Save component entities</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setEditComponentEntitiesTarget(null)}>Cancel</Button>
        </form>
      )}
      {editFormulaTarget && (
        <form onSubmit={submitFormulaSpec} className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[0.8fr_1fr_1fr_auto_auto]">
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
      {editAnalyticsTarget && (
        <form onSubmit={submitAnalyticsSpec} className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_auto_auto]">
          <textarea
            value={analyticsSpecValue}
            onChange={(e) => setAnalyticsSpecValue(e.target.value)}
            rows={4}
            className="rounded-md border border-border bg-surface-card px-2.5 py-2 font-mono text-xs text-text outline-none"
          />
          <Button type="submit" size="sm" disabled={planSaving}>Save analytics</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setEditAnalyticsTarget(null)}>Cancel</Button>
        </form>
      )}
    </>
  );

  const renderWorkbenchPanel = () => {
    if (!session) return null;
    if (workbenchMode === 'entities') {
      return (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-text">Entity matching</h2>
              <p className="text-sm text-text-muted">
                {remaining > 0 ? `${remaining} of ${proposals.length} entities still need officer review.` : 'All entity bindings have decisions.'}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={confirmAllRemaining} disabled={!!busyEntity || remaining === 0}>
              <Sparkles className="h-4 w-4" /> Confirm all proposed
            </Button>
          </div>
          <EntityMatrixPanel
            key={`entity-matrix-${focusedEntityId || 'default'}`}
            bindings={proposals}
            columns={session.dataset_ast.columns}
            columnOwnership={session.column_ownership}
            decisions={decisions}
            dependencyGraph={workspace?.dependency_graph}
            issues={workspaceIssues}
            initialEntityId={focusedEntityId}
            busyEntity={busyEntity}
            onDecide={onDecide}
            onConfirmAll={confirmAllRemaining}
          />
        </div>
      );
    }

    if (workbenchMode === 'questions') {
      return (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-text">Question plan</h2>
              <p className="text-sm text-text-muted">
                {currentReviewedPlan ? 'Edit the officer-reviewed plan, required entities, formulas, and components.' : 'Finalize entity matching to build the reviewed plan.'}
              </p>
            </div>
            {!currentReviewedPlan && (
              <Button onClick={onFinalize} disabled={finalizing || !allDecided}>
                {finalizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                Build reviewed plan
              </Button>
            )}
          </div>
          {currentReviewedPlan ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface p-3">
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
                <div className="rounded-lg border border-success/30 bg-success/5 px-3 py-2 text-xs text-text-muted">
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
              <StructureCanvas
                key={`structure-canvas-${focusedQuestionId || focusedComponentId || 'default'}`}
                plan={currentReviewedPlan}
                dependencyGraph={workspace?.dependency_graph}
                issues={workspaceIssues}
                componentDefinitions={componentDefinitions}
                busy={planSaving}
                initialQuestionId={focusedQuestionId}
                initialComponentId={focusedComponentId}
                editorSlot={renderPlanEditors()}
                addQuestionSlot={(
                  <form onSubmit={onAddPlanQuestion} className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_1.5fr_auto]">
                    <select
                      value={newPlanQuestionTopic}
                      onChange={(e) => setNewPlanQuestionTopic(e.target.value)}
                      className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                    >
                      <option value="">Choose topic</option>
                      {planContainers.map((node) => <option key={node.nodeId} value={node.nodeId}>{node.title}</option>)}
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
                )}
                addComponentSlot={(
                  <form onSubmit={onAddPlanComponent} className="space-y-2 rounded-lg border border-border bg-surface p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Manual component</p>
                    <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                    <select
                      value={newComponentNode}
                      onChange={(e) => setNewComponentNode(e.target.value)}
                      className="rounded-md border border-border bg-surface-card px-2.5 py-2 text-xs text-text outline-none"
                    >
                      <option value="">Attach to item</option>
                      {planNodes.map((node) => <option key={node.nodeId} value={node.nodeId}>{node.title}</option>)}
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
                    </div>
                    <p className="text-[11px] text-text-muted">Chart, table, and formula components start with the selected question&apos;s entities and a draft analytics spec.</p>
                  </form>
                )}
                onRename={onRenamePlanNode}
                onToggle={onTogglePlanNode}
                onEditEntities={onEditRequiredEntities}
                onEditComponentEntities={onEditComponentRequiredEntities}
                onEditFormula={onEditFormulaSpec}
                onEditAnalytics={onEditAnalyticsSpec}
                loadRecommendations={loadComponentRecommendations}
                onAddRecommendedComponent={onAddRecommendedComponent}
              />
            </div>
          ) : (
            <Alert variant="warning">Finish entity decisions first; the question plan is created at the coverage gate.</Alert>
          )}
        </div>
      );
    }

    if (workbenchMode === 'columns') {
      const ownershipEntries = Object.entries(session.column_ownership.columns ?? {});
      return (
        <div className="grid gap-4 xl:grid-cols-[1fr_1.1fr]">
          <DatasetProfileCard dataset={session.dataset_ast} />
          <Card title="Column ownership" description="Which report entities claim each dataset column.">
            <div className="max-h-[34rem] space-y-2 overflow-auto pr-1">
              {ownershipEntries.map(([columnName, entry]) => (
                <div key={columnName} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate font-medium text-text">{columnName}</p>
                    {entry.locked ? <Badge variant="warning">locked</Badge> : entry.owners.length > 1 ? <Badge variant="muted">shared</Badge> : <Badge variant="muted">open</Badge>}
                  </div>
                  <p className="mt-1 text-xs text-text-muted">
                    {entry.owners.length ? entry.owners.map((owner) => `${owner.entityName || owner.entityId} (${owner.sharePolicy})`).join(', ') : 'No entity has claimed this column yet.'}
                  </p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      );
    }

    if (workbenchMode === 'issues') {
      return (
        <div className="space-y-4">
          {result && (
            <CoveragePanel coverage={result.coverage} questionBindings={result.question_bindings} hasErrors={result.has_errors} />
          )}
          <Card title="Workspace issues" description="Open blockers, unresolved entities, and ownership risks.">
            <div className="space-y-2">
              {workspaceIssues.length === 0 ? (
                <div className="rounded-lg border border-success/25 bg-success/5 px-3 py-2 text-sm text-text-muted">No workspace issues are currently reported.</div>
              ) : workspaceIssues.map((issue: BindingWorkspaceIssue, index) => (
                <div key={issue.issueId || `${issue.code || 'issue'}-${issue.entityId || issue.column || index}`} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={issue.severity === 'error' || issue.severity === 'danger' ? 'danger' : issue.severity === 'warn' || issue.severity === 'warning' ? 'warning' : 'muted'}>
                        {issue.code || issue.severity || 'ISSUE'}
                      </Badge>
                      {issue.entityId && <span className="font-mono text-xs text-text-muted">{issue.entityId}</span>}
                      {issue.questionId && <span className="font-mono text-xs text-text-muted">{issue.questionId}</span>}
                      {issue.column && <span className="font-mono text-xs text-text-muted">{issue.column}</span>}
                    </div>
                    <Button type="button" variant="outline" size="sm" onClick={() => focusIssue(issue)}>
                      Go fix
                    </Button>
                  </div>
                  <p className="mt-1 text-text-muted">{issue.message}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      );
    }

    if (workbenchMode === 'handoff') {
      const meta = executionReady ? EXECUTION_READY_META[executionReady.status] : null;
      const Icon = meta?.icon ?? AlertCircle;
      const readyToOpen = executionReady?.status === 'READY' || executionReady?.status === 'DEGRADED';
      return (
        <div className="space-y-4">
          <Card title="S3.5 handoff" description="Prepare the canonical execution bundle for the downstream runtime team.">
            {executionReady && meta ? (
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
                        Contract {executionReady.contract_version} · Binding AST <span className="font-mono text-text">{executionReady.binding_ast_id}</span>
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-right text-xs">
                    <div><p className="font-semibold text-text">{executionReady.plans.length}</p><p className="text-text-muted">plans</p></div>
                    <div><p className="font-semibold text-text">{executionReady.blocked_questions.length}</p><p className="text-text-muted">blocked</p></div>
                    <div><p className="font-semibold text-text">{Object.keys(executionReady.lineage_index ?? {}).length}</p><p className="text-text-muted">lineage</p></div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-border bg-surface p-4 text-sm text-text-muted">No handoff bundle has been prepared for this session yet.</div>
            )}
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              {!executionReady ? (
                <Button onClick={onExecutionReady} disabled={checkingReady || !currentReviewedPlan}>
                  {checkingReady ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                  Prepare S3.5 bundle
                </Button>
              ) : readyToOpen ? (
                <Link href={generationHref}><Button>Open generation workspace <ArrowRight className="h-4 w-4" /></Button></Link>
              ) : (
                <Button disabled>Not ready for generation <ArrowRight className="h-4 w-4" /></Button>
              )}
            </div>
          </Card>
        </div>
      );
    }

    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-border bg-surface p-4">
            <p className="text-[11px] uppercase text-text-muted">Template</p>
            <p className="mt-1 truncate text-sm font-semibold text-text">{packageForWorkbench?.name ?? session.template_id}</p>
            <p className="mt-1 text-xs text-text-muted">{packageForWorkbench?.questions_count ?? currentReviewedPlan?.questionCount ?? 0} questions · {packageForWorkbench?.chart_slots_count ?? 0} charts</p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4">
            <p className="text-[11px] uppercase text-text-muted">Dataset</p>
            <p className="mt-1 truncate text-sm font-semibold text-text">{session.dataset_id}</p>
            <p className="mt-1 text-xs text-text-muted">{datasetForWorkbench?.columns.length ?? 0} profiled columns</p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4">
            <p className="text-[11px] uppercase text-text-muted">Entity decisions</p>
            <p className="mt-1 text-sm font-semibold text-text">{decidedCount}/{proposals.length}</p>
            <p className="mt-1 text-xs text-text-muted">{remaining} pending</p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4">
            <p className="text-[11px] uppercase text-text-muted">Readiness</p>
            <p className="mt-1 text-sm font-semibold text-text">{executionReady?.status ?? (currentReviewedPlan ? 'Plan ready' : 'Matching')}</p>
            <p className="mt-1 text-xs text-text-muted">{workspaceIssues.length} workspace issues</p>
          </div>
        </div>
        <Card title="Phase readiness" description="Backend-governed transition state for the current binding session.">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {workbenchModes.filter((mode) => mode.id !== 'overview').map((mode) => (
              <button
                key={mode.id}
                type="button"
                onClick={() => setWorkbenchMode(mode.id)}
                className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-sm hover:border-accent/60"
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-text">{mode.label}</span>
                  <Badge variant={mode.status === 'Ready' ? 'success' : mode.status === 'Blocked' ? 'danger' : mode.status === 'Review' ? 'warning' : 'muted'}>
                    {mode.status}
                  </Badge>
                </span>
                <span className="mt-1 block text-xs text-text-muted">{mode.hint}</span>
              </button>
            ))}
          </div>
        </Card>
        <div className="grid gap-4 xl:grid-cols-[1fr_20rem]">
          <Card title="Dependency graph" description="How entities connect to questions, components, and dataset columns.">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                <p className="text-[11px] uppercase text-text-muted">Entity → Questions</p>
                <p className="mt-1 font-semibold text-text">{Object.keys(workspace?.dependency_graph.entityToQuestions ?? {}).length}</p>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                <p className="text-[11px] uppercase text-text-muted">Entity → Components</p>
                <p className="mt-1 font-semibold text-text">{Object.keys(workspace?.dependency_graph.entityToComponents ?? {}).length}</p>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                <p className="text-[11px] uppercase text-text-muted">Columns claimed</p>
                <p className="mt-1 font-semibold text-text">{Object.keys(workspace?.dependency_graph.columnToEntities ?? {}).length}</p>
              </div>
            </div>
          </Card>
          <Card title="Next action" description="Recommended step from current session state.">
            {remaining > 0 ? (
              <Button className="w-full" onClick={() => setWorkbenchMode('entities')}>Review {remaining} entities</Button>
            ) : !currentReviewedPlan ? (
              <Button className="w-full" onClick={onFinalize} disabled={finalizing}>Build reviewed plan</Button>
            ) : !executionReady ? (
              <Button className="w-full" onClick={() => setWorkbenchMode('handoff')}>Prepare handoff</Button>
            ) : (
              <Button className="w-full" onClick={() => setWorkbenchMode('issues')}>Inspect readiness</Button>
            )}
          </Card>
        </div>
      </div>
    );
  };

  const bindingWorkbench = session ? (
    <div className="space-y-4">
      <div className="rounded-2xl border border-border bg-surface-card p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Binder workbench</p>
            <h2 className="mt-1 text-xl font-semibold text-text">{packageForWorkbench?.name ?? session.template_id}</h2>
            <p className="mt-1 text-sm text-text-muted">Dataset {session.dataset_id} · signature {session.signature}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {workspaceLoading && <Badge variant="muted">Refreshing…</Badge>}
            <Badge variant={remaining === 0 ? 'success' : 'warning'}>{remaining === 0 ? 'Bindings reviewed' : `${remaining} pending`}</Badge>
            {currentReviewedPlan && <Badge variant="success">Plan ready</Badge>}
            {executionReady && <Badge variant={EXECUTION_READY_META[executionReady.status].badge}>{executionReady.status}</Badge>}
          </div>
        </div>
        <div className="grid gap-4 pt-4 lg:grid-cols-[13rem_1fr_18rem]">
          <nav className="space-y-1">
            {workbenchModes.map((mode) => (
              <button
                key={mode.id}
                type="button"
                onClick={() => setWorkbenchMode(mode.id)}
                className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${workbenchMode === mode.id ? 'border-primary bg-primary/5 text-text' : 'border-transparent text-text-muted hover:border-border hover:bg-surface'}`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{mode.label}</span>
                  <Badge variant={mode.status === 'Ready' ? 'success' : mode.status === 'Blocked' ? 'danger' : mode.status === 'Review' ? 'warning' : 'muted'} className="px-1.5 py-0 text-[10px]">
                    {mode.status}
                  </Badge>
                </span>
                <span className="block text-xs">{mode.hint}</span>
              </button>
            ))}
          </nav>
          <main className="min-w-0">{renderWorkbenchPanel()}</main>
          <aside className="space-y-4">
            <Card title="Column allocation" description="Live ownership state.">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-lg border border-border bg-surface px-3 py-2"><p className="text-[11px] uppercase text-text-muted">Assigned</p><p className="mt-1 font-semibold text-text">{ownershipStats.assigned}</p></div>
                <div className="rounded-lg border border-border bg-surface px-3 py-2"><p className="flex items-center gap-1 text-[11px] uppercase text-text-muted"><Lock className="h-3 w-3" /> Locked</p><p className="mt-1 font-semibold text-text">{ownershipStats.locked}</p></div>
                <div className="rounded-lg border border-border bg-surface px-3 py-2"><p className="flex items-center gap-1 text-[11px] uppercase text-text-muted"><Share2 className="h-3 w-3" /> Shared</p><p className="mt-1 font-semibold text-text">{ownershipStats.shared}</p></div>
                <div className="rounded-lg border border-border bg-surface px-3 py-2"><p className="flex items-center gap-1 text-[11px] uppercase text-text-muted"><AlertTriangle className="h-3 w-3" /> Conflicts</p><p className="mt-1 font-semibold text-text">{ownershipStats.conflicts}</p></div>
              </div>
            </Card>
            <Card title="Add entity" description="Create a missing template entity.">
              <form onSubmit={onAddEntity} className="space-y-3">
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
                  {session.dataset_ast.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                </select>
                <input
                  value={newEntityName}
                  onChange={(e) => setNewEntityName(e.target.value)}
                  placeholder="Entity name"
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:ring-2 focus:ring-accent/30"
                />
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
                <Button type="submit" size="sm" className="w-full" disabled={addingEntity || !newEntityColumn || !newEntityName.trim()}>
                  {addingEntity ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  Add and bind
                </Button>
              </form>
            </Card>
            <div className="flex flex-col gap-2">
              <Button variant="outline" size="sm" onClick={resetAll}><ArrowLeft className="h-4 w-4" /> Start over</Button>
              <Button size="sm" onClick={onFinalize} disabled={finalizing || !allDecided}>
                {finalizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                Coverage gate
              </Button>
            </div>
          </aside>
        </div>
      </div>
    </div>
  ) : null;

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
          <div className="mx-auto max-w-6xl space-y-5">
            <section className="rounded-2xl border border-border bg-surface-card p-4 shadow-sm sm:p-6">
              <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-wide text-primary">1. Template package</p>
                  <h2 className="mt-1 text-xl font-semibold text-text">Pick the binder brain first</h2>
                  <p className="mt-1 max-w-3xl text-sm text-text-muted">
                    Search templates by domain, readiness, richness, and question coverage. The selected package controls entity binding, ReviewedPlan generation, slot lineage, and S3.5 handoff quality.
                  </p>
                </div>
                {selectedPackage && (
                  <Badge variant={selectedPackage.status === 'VALID' ? 'success' : 'warning'} className="shrink-0">
                    {selectedPackage.status}
                  </Badge>
                )}
              </div>

              <TemplatePackagePicker
                packages={templatePackages}
                selectedTemplateId={templateId}
                loading={templatesLoading}
                onSelect={setTemplateId}
              />
            </section>

            <form onSubmit={onStart} className="space-y-5">
              <section className="rounded-2xl border border-border bg-surface-card p-4 shadow-sm sm:p-6">
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-wide text-primary">2. Dataset upload</p>
                    <h2 className="mt-1 text-xl font-semibold text-text">Create the binding session</h2>
                    <p className="mt-1 max-w-3xl text-sm text-text-muted">
                      Upload a CSV after selecting the template. The binder profiles columns, infers roles, tracks ownership, and opens the review workspace.
                    </p>
                  </div>
                  <div className="rounded-xl border border-primary/15 bg-primary/5 px-3 py-2 text-xs">
                    <p className="font-semibold uppercase tracking-wide text-primary">Selected ID</p>
                    <p className="mt-1 max-w-[18rem] break-words font-mono text-text">{templateId || 'tpl_plfs_annual_v1'}</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <label
                    htmlFor="binding-dataset"
                    className="block cursor-pointer rounded-2xl border-2 border-dashed border-border bg-surface p-8 text-center transition-colors hover:border-primary/50 hover:bg-primary/5"
                  >
                    <UploadIcon className="mx-auto mb-3 h-8 w-8 text-primary" />
                    <p className="break-words text-base font-semibold text-text">
                      {datasetFile ? datasetFile.name : 'Choose CSV dataset'}
                    </p>
                    <p className="mx-auto mt-2 max-w-2xl text-sm text-text-muted">
                      Measures, dimensions, time columns, samples, column ownership, conflicts, and binder proposals are computed from this file.
                    </p>
                  </label>
                  <input
                    id="binding-dataset"
                    type="file"
                    accept=".csv,text/csv"
                    className="hidden"
                    onChange={(e) => setDatasetFile(e.target.files?.[0] ?? null)}
                  />

                  <section className="rounded-xl border border-border bg-surface p-4">
                    <button
                      type="button"
                      onClick={() => setAdvancedOpen((v) => !v)}
                      className="flex w-full items-center justify-between gap-3 text-left text-sm font-semibold text-text"
                    >
                      <span>Advanced template controls</span>
                      <span className="shrink-0 text-xs font-medium text-primary">{advancedOpen ? 'Hide' : 'Show'}</span>
                    </button>
                    {advancedOpen && (
                      <div className="mt-4 grid gap-3 md:grid-cols-2">
                        <div>
                          <label className="mb-1 block text-xs font-medium text-text-muted">Manual template id</label>
                          <input
                            type="text"
                            value={templateId}
                            onChange={(e) => setTemplateId(e.target.value)}
                            placeholder="tpl_plfs_annual_v1"
                            className="w-full rounded-lg border border-border bg-surface-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                          />
                          <p className="mt-1 text-xs text-text-muted">Use only for a known built-in or DB template id.</p>
                        </div>
                        <div>
                          <label
                            htmlFor="binding-blueprint"
                            className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-border bg-surface-card px-3 py-2 text-sm transition-colors hover:border-accent/50"
                          >
                            <span className="min-w-0 truncate text-text-muted">
                              {blueprintFile ? blueprintFile.name : 'Override blueprint.json'}
                            </span>
                            <span className="shrink-0 text-xs font-medium text-primary">Browse</span>
                          </label>
                          <input
                            id="binding-blueprint"
                            type="file"
                            accept="application/json,.json"
                            className="hidden"
                            onChange={(e) => setBlueprintFile(e.target.files?.[0] ?? null)}
                          />
                          <p className="mt-1 text-xs text-text-muted">Optional override for debugging or officer-supplied packages.</p>
                        </div>
                      </div>
                    )}
                  </section>

                  <Button type="submit" disabled={starting || !datasetFile || !templateId.trim()} className="w-full py-3">
                    {starting ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" /> Creating binding session
                      </>
                    ) : (
                      <>
                        Create binding session <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
              </section>
            </form>
          </div>
        )}

        {(step === 1 || step === 2) && session && bindingWorkbench}

      </div>
    </>
  );
}
