'use client';

import { useEffect, useMemo, useState } from 'react';
import { BarChart3, EyeOff, FileText, FunctionSquare, ListTree, Pencil, Plus, Table2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import type {
  BindingDependencyGraph,
  BindingWorkspaceIssue,
  ComponentRecommendation,
  ComponentDefinition,
  ReviewedPlanComponent,
  ReviewedPlanNode,
  ReviewedPlanSummary,
} from '@/lib/api';

type ComponentAction = (nodeId: string, componentType: string, payload?: Record<string, unknown>) => void | Promise<void>;

interface StructureCanvasProps {
  plan: ReviewedPlanSummary;
  dependencyGraph?: BindingDependencyGraph;
  issues?: BindingWorkspaceIssue[];
  componentDefinitions: ComponentDefinition[];
  busy?: boolean;
  initialQuestionId?: string | null;
  initialComponentId?: string | null;
  editorSlot?: React.ReactNode;
  addQuestionSlot?: React.ReactNode;
  addComponentSlot?: React.ReactNode;
  onRename: (node: ReviewedPlanNode) => void;
  onToggle: (node: ReviewedPlanNode) => void;
  onEditEntities: (node: ReviewedPlanNode) => void;
  onEditComponentEntities: (node: ReviewedPlanNode, component: ReviewedPlanComponent) => void;
  onEditFormula: (node: ReviewedPlanNode, component: ReviewedPlanComponent) => void;
  onEditAnalytics: (node: ReviewedPlanNode, component: ReviewedPlanComponent) => void;
  loadRecommendations?: (nodeId: string) => Promise<ComponentRecommendation[]>;
  onAddRecommendedComponent: ComponentAction;
}

function readinessVariant(readiness: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (readiness === 'READY' || readiness === 'executable') return 'success';
  if (readiness === 'DEGRADED' || readiness === 'degraded') return 'warning';
  if (readiness === 'BLOCKED' || readiness === 'blocked') return 'danger';
  return 'muted';
}

function requiredEntitiesToText(requiredEntities: Array<Record<string, unknown>>): string {
  return requiredEntities
    .map((entity) => `${String(entity.entityId || entity.entityRef || '')}:${String(entity.role || 'measure')}`)
    .filter((item) => !item.startsWith(':'))
    .join(', ');
}

function flatten(nodes: ReviewedPlanNode[]): ReviewedPlanNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children)]);
}

function componentLabel(componentType: string, definitions: ComponentDefinition[]): string {
  return definitions.find((definition) => definition.componentType === componentType)?.label || componentType.replace(/_/g, ' ');
}

function recommendedComponentTypes(node: ReviewedPlanNode, definitions: ComponentDefinition[]): string[] {
  if (node.nodeType !== 'question') return [];
  const available = new Set(definitions.map((definition) => definition.componentType));
  const text = `${node.title} ${JSON.stringify(node.requiredEntities)}`.toLowerCase();
  const recommendations = ['key_finding', 'narrative'];

  if (text.includes('trend') || text.includes('time') || text.includes('year') || text.includes('monthly')) {
    recommendations.push('chart');
  }
  if (text.includes('compare') || text.includes('across') || text.includes('sector') || text.includes('gender') || text.includes('rural') || text.includes('urban')) {
    recommendations.push('chart', 'table');
  }
  if (text.includes('rate') || text.includes('ratio') || text.includes('share') || text.includes('average')) {
    recommendations.push('formula_metric');
  }
  recommendations.push('source_note');

  return Array.from(new Set(recommendations)).filter((componentType) => available.size === 0 || available.has(componentType));
}

function componentIcon(componentType: string) {
  if (componentType === 'chart') return BarChart3;
  if (componentType === 'table') return Table2;
  if (componentType === 'formula_metric') return FunctionSquare;
  if (componentType === 'key_finding' || componentType === 'narrative') return FileText;
  return Plus;
}

function issueMatchesNode(issue: BindingWorkspaceIssue, node: ReviewedPlanNode, graph?: BindingDependencyGraph): boolean {
  if (issue.nodeId && node.nodeId === issue.nodeId) return true;
  if (issue.questionId && node.questionId === issue.questionId) return true;
  if (issue.componentId && node.components.some((component) => component.componentId === issue.componentId)) return true;
  if (issue.entityId && node.questionId) {
    return (graph?.questionToEntities[node.questionId] || []).includes(issue.entityId);
  }
  return false;
}

export function StructureCanvas({
  plan,
  dependencyGraph,
  issues = [],
  componentDefinitions,
  busy,
  initialQuestionId,
  initialComponentId,
  editorSlot,
  addQuestionSlot,
  addComponentSlot,
  onRename,
  onToggle,
  onEditEntities,
  onEditComponentEntities,
  onEditFormula,
  onEditAnalytics,
  loadRecommendations,
  onAddRecommendedComponent,
}: StructureCanvasProps) {
  const nodes = useMemo(() => flatten(plan.planTree), [plan.planTree]);
  const [selectedNodeId, setSelectedNodeId] = useState(() => (
    nodes.find((node) => initialComponentId && node.components.some((component) => component.componentId === initialComponentId))?.nodeId
    || nodes.find((node) => node.questionId === initialQuestionId)?.nodeId
    || nodes[0]?.nodeId
    || ''
  ));
  const [serverRecommendationState, setServerRecommendationState] = useState<{ nodeId: string; items: ComponentRecommendation[] }>({ nodeId: '', items: [] });
  const selectedNode = nodes.find((node) => node.nodeId === selectedNodeId) || nodes[0];
  const selectedIssues = selectedNode ? issues.filter((issue) => issueMatchesNode(issue, selectedNode, dependencyGraph)) : [];
  const selectedColumns = selectedNode?.questionId ? dependencyGraph?.questionToColumns[selectedNode.questionId] || [] : [];
  const selectedEntities = selectedNode?.questionId ? dependencyGraph?.questionToEntities[selectedNode.questionId] || [] : [];
  const heuristicRecommendations = selectedNode ? recommendedComponentTypes(selectedNode, componentDefinitions) : [];
  const serverRecommendations = selectedNode?.nodeId === serverRecommendationState.nodeId ? serverRecommendationState.items : [];
  const recommendations = serverRecommendations.length
    ? serverRecommendations.map((recommendation) => ({
      componentType: recommendation.component_type,
      label: recommendation.label,
      score: recommendation.score,
      reason: recommendation.reason,
      payload: recommendation.payload,
    }))
    : heuristicRecommendations.map((componentType) => ({
      componentType,
      label: componentLabel(componentType, componentDefinitions),
      score: 0,
      reason: 'Suggested from the selected question text and required entities.',
      payload: {},
    }));

  useEffect(() => {
    let cancelled = false;
    if (!selectedNode?.nodeId || !loadRecommendations || selectedNode.nodeType !== 'question') {
      return;
    }
    loadRecommendations(selectedNode.nodeId)
      .then((items) => {
        if (!cancelled) setServerRecommendationState({ nodeId: selectedNode.nodeId, items });
      })
      .catch(() => {
        if (!cancelled) setServerRecommendationState({ nodeId: selectedNode.nodeId, items: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [loadRecommendations, selectedNode?.nodeId, selectedNode?.nodeType]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-xl border border-border bg-surface p-4 text-sm sm:grid-cols-4">
        <div>
          <p className="text-[11px] uppercase text-text-muted">Topics</p>
          <p className="mt-1 font-semibold text-text">{plan.topicCount}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase text-text-muted">Questions</p>
          <p className="mt-1 font-semibold text-text">{plan.questionCount}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase text-text-muted">Components</p>
          <p className="mt-1 font-semibold text-text">{plan.componentCount}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase text-text-muted">Slots</p>
          <p className="mt-1 font-semibold text-text">{plan.semanticSlotCount} semantic / {plan.virtualSlotCount} virtual</p>
        </div>
      </div>

      {editorSlot}

      <div className="grid gap-4 xl:grid-cols-[20rem_1fr]">
        {/* Left panel: tree navigator */}
        <div className="rounded-xl border border-border bg-surface-card p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">Report structure</p>
          <div className="max-h-[50rem] space-y-1 overflow-auto pr-1">
            {plan.planTree.map((topNode) => (
              <div key={topNode.nodeId} className="space-y-0.5">
                <button
                  type="button"
                  onClick={() => setSelectedNodeId(topNode.nodeId)}
                  className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${selectedNodeId === topNode.nodeId ? 'border border-primary/30 bg-primary/5 text-primary' : 'border border-transparent text-text hover:bg-surface'}`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-semibold">{topNode.title}</span>
                    <Badge variant={readinessVariant(topNode.readiness)} className="text-[10px] shrink-0">{topNode.readiness}</Badge>
                  </span>
                  <span className="mt-0.5 block text-[11px] uppercase text-text-muted">{topNode.nodeType}</span>
                </button>
                {topNode.children.length > 0 && (
                  <div className="ml-3 space-y-0.5 border-l border-border pl-2">
                    {topNode.children.map((child) => (
                      <button
                        key={child.nodeId}
                        type="button"
                        onClick={() => setSelectedNodeId(child.nodeId)}
                        className={`w-full rounded-md px-2.5 py-1.5 text-left text-xs transition-colors ${selectedNodeId === child.nodeId ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface hover:text-text'}`}
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate font-medium">{child.title}</span>
                          {child.enabled === false && <Badge variant="muted" className="text-[9px]">off</Badge>}
                          {issues.filter((issue) => issueMatchesNode(issue, child, dependencyGraph)).length > 0 && (
                            <Badge variant="warning" className="text-[9px]">{issues.filter((issue) => issueMatchesNode(issue, child, dependencyGraph)).length}</Badge>
                          )}
                        </span>
                        <span className="mt-0.5 flex items-center gap-2 text-[10px] text-text-muted">
                          <span className="uppercase">{child.nodeType}</span>
                          {child.components.length > 0 && <span>{child.components.length} comp</span>}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Right panel: detail inspector */}
        <div className="rounded-xl border border-border bg-surface-card p-5">
          {selectedNode ? (
            <div className="space-y-5">
              {/* Header */}
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="muted">{selectedNode.nodeType}</Badge>
                    <Badge variant={readinessVariant(selectedNode.readiness)}>{selectedNode.readiness}</Badge>
                    {selectedNode.enabled === false && <Badge variant="muted">Disabled</Badge>}
                  </div>
                  <h3 className="mt-2 text-lg font-semibold text-text">{selectedNode.title}</h3>
                  {selectedNode.questionId && <p className="mt-1 font-mono text-xs text-text-muted">{selectedNode.questionId}</p>}
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => onRename(selectedNode)}>
                    <Pencil className="h-4 w-4" /> Rename
                  </Button>
                  {selectedNode.nodeType === 'question' && (
                    <>
                      <Button size="sm" variant="outline" disabled={busy} onClick={() => onToggle(selectedNode)}>
                        <EyeOff className="h-4 w-4" /> {selectedNode.enabled === false ? 'Enable' : 'Disable'}
                      </Button>
                      <Button size="sm" variant="outline" disabled={busy} onClick={() => onEditEntities(selectedNode)}>
                        <ListTree className="h-4 w-4" /> Entities
                      </Button>
                    </>
                  )}
                </div>
              </div>

              {/* Metadata grid */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <div className="space-y-1.5">
                  <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Required entities</p>
                  <div className="rounded-lg border border-border bg-surface px-3 py-2">
                    {selectedNode.requiredEntities.length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {selectedNode.requiredEntities.map((entity, i) => (
                          <span key={i} className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                            {String(entity.entityId || entity.entityRef || '')}
                            <span className="ml-1 text-primary/60">{String(entity.role || '')}</span>
                          </span>
                        ))}
                      </div>
                    ) : <span className="text-xs text-text-muted">None recorded</span>}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Resolved columns</p>
                  <div className="rounded-lg border border-border bg-surface px-3 py-2">
                    {selectedColumns.length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {selectedColumns.map((column) => (
                          <span key={column} className="rounded bg-border px-2 py-0.5 font-mono text-xs text-text-muted">{column}</span>
                        ))}
                      </div>
                    ) : <span className="text-xs text-text-muted">No columns resolved</span>}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Entity links</p>
                  <div className="rounded-lg border border-border bg-surface px-3 py-2">
                    {selectedEntities.length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {selectedEntities.map((entityId) => (
                          <span key={entityId} className="rounded bg-border px-2 py-0.5 font-mono text-xs text-text-muted">{entityId}</span>
                        ))}
                      </div>
                    ) : <span className="text-xs text-text-muted">No linked entities</span>}
                  </div>
                </div>
              </div>

              {/* Components section */}
              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Components</p>
                {selectedNode.components.length ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {selectedNode.components.map((component) => {
                      const focused = initialComponentId === component.componentId;
                      return (
                        <div key={component.componentId} className={`rounded-xl border p-4 ${focused ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border bg-surface'}`}>
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-sm font-semibold text-text">{componentLabel(component.componentType, componentDefinitions)}</p>
                            {component.slotIds.length > 0 && <Badge variant="muted">{component.slotIds.length} slot{component.slotIds.length > 1 ? 's' : ''}</Badge>}
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <button type="button" disabled={busy} onClick={() => onEditComponentEntities(selectedNode, component)} className="text-xs font-semibold text-primary hover:underline disabled:opacity-50">
                              Entities
                            </button>
                            {(component.formulaSpec && Object.keys(component.formulaSpec).length > 0) || component.componentType === 'formula_metric' ? (
                              <button type="button" disabled={busy} onClick={() => onEditFormula(selectedNode, component)} className="text-xs font-semibold text-primary hover:underline disabled:opacity-50">
                                {component.formulaSpec && Object.keys(component.formulaSpec).length > 0 ? 'Edit formula' : 'Configure formula'}
                              </button>
                            ) : null}
                            {['chart', 'table', 'formula_metric'].includes(component.componentType) && (
                              <button type="button" disabled={busy} onClick={() => onEditAnalytics(selectedNode, component)} className="text-xs font-semibold text-primary hover:underline disabled:opacity-50">
                                Analytics
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : <p className="text-sm text-text-muted">No components attached yet.</p>}
              </div>

              {/* Recommended components */}
              {recommendations.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Add component</p>
                    {selectedNode.nodeId !== serverRecommendationState.nodeId && loadRecommendations && <span className="text-[11px] text-text-muted">Loading…</span>}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {recommendations.map((recommendation) => {
                      const componentType = recommendation.componentType;
                      const Icon = componentIcon(componentType);
                      return (
                        <button
                          key={componentType}
                          type="button"
                          disabled={busy}
                          onClick={() => onAddRecommendedComponent(selectedNode.nodeId, componentType, recommendation.payload)}
                          className="rounded-xl border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-accent/60 disabled:opacity-50"
                        >
                          <span className="flex items-center gap-2">
                            <Icon className="h-4 w-4 shrink-0 text-text-muted" />
                            <span className="text-sm font-semibold text-text">{recommendation.label}</span>
                            {recommendation.score > 0 && <Badge variant="muted" className="ml-auto">{Math.round(recommendation.score * 100)}%</Badge>}
                          </span>
                          <span className="mt-1 block text-xs text-text-muted">{recommendation.reason}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Issues */}
              {selectedIssues.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Issues</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {selectedIssues.map((issue, index) => (
                      <div key={issue.issueId || `${issue.code || 'issue'}-${index}`} className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-text-muted">
                        <p className="font-semibold text-text">{issue.code || issue.severity || 'Issue'}</p>
                        <p className="mt-1">{issue.message}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-text-muted">Select an item from the tree to inspect it.</p>
          )}
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        {addQuestionSlot}
        {addComponentSlot}
      </div>
    </div>
  );
}

export default StructureCanvas;
