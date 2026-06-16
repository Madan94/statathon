'use client';

import { useEffect, useMemo, useState } from 'react';
import { BarChart3, EyeOff, FileText, FunctionSquare, ListTree, Pencil, Plus, Table2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
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

function NodeCard({
  node,
  depth,
  selected,
  dependencyGraph,
  issues,
  onSelect,
}: {
  node: ReviewedPlanNode;
  depth: number;
  selected: boolean;
  dependencyGraph?: BindingDependencyGraph;
  issues: BindingWorkspaceIssue[];
  onSelect: (node: ReviewedPlanNode) => void;
}) {
  const nodeIssues = issues.filter((issue) => issueMatchesNode(issue, node, dependencyGraph));
  const resolvedColumns = node.questionId ? dependencyGraph?.questionToColumns[node.questionId] || [] : [];
  return (
    <button
      type="button"
      onClick={() => onSelect(node)}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${selected ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border bg-surface hover:border-accent/50'}`}
      style={{ marginLeft: depth * 14, width: `calc(100% - ${depth * 14}px)` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{node.nodeType}</span>
            {node.enabled === false && <Badge variant="muted">disabled</Badge>}
            {nodeIssues.length > 0 && <Badge variant="warning">{nodeIssues.length} issue{nodeIssues.length > 1 ? 's' : ''}</Badge>}
          </div>
          <p className="mt-1 line-clamp-2 text-sm font-semibold text-text">{node.title}</p>
          {node.questionId && <p className="mt-1 font-mono text-[11px] text-text-muted">{node.questionId}</p>}
        </div>
        <Badge variant={readinessVariant(node.readiness)}>{node.readiness}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-text-muted">
        {node.requiredEntities.length > 0 && <span className="rounded bg-border px-2 py-0.5">{node.requiredEntities.length} entities</span>}
        {resolvedColumns.length > 0 && <span className="rounded bg-border px-2 py-0.5">{resolvedColumns.length} columns</span>}
        {node.components.length > 0 && <span className="rounded bg-border px-2 py-0.5">{node.components.length} components</span>}
      </div>
    </button>
  );
}

function renderCanvasNodes({
  nodes,
  depth,
  selectedNodeId,
  dependencyGraph,
  issues,
  onSelect,
}: {
  nodes: ReviewedPlanNode[];
  depth: number;
  selectedNodeId: string;
  dependencyGraph?: BindingDependencyGraph;
  issues: BindingWorkspaceIssue[];
  onSelect: (node: ReviewedPlanNode) => void;
}) {
  return nodes.map((node) => (
    <div key={node.nodeId} className="space-y-2">
      <NodeCard
        node={node}
        depth={depth}
        selected={selectedNodeId === node.nodeId}
        dependencyGraph={dependencyGraph}
        issues={issues}
        onSelect={onSelect}
      />
      {node.children.length > 0 && renderCanvasNodes({ nodes: node.children, depth: depth + 1, selectedNodeId, dependencyGraph, issues, onSelect })}
    </div>
  ));
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

      <div className="grid gap-4 xl:grid-cols-[13rem_1fr_20rem]">
        <Card className="p-4" title="Outline" description="Report sections and questions.">
          <div className="max-h-[34rem] space-y-1 overflow-auto pr-1">
            {nodes.map((node) => (
              <button
                key={node.nodeId}
                type="button"
                onClick={() => setSelectedNodeId(node.nodeId)}
                className={`w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors ${selectedNodeId === node.nodeId ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface'}`}
              >
                <span className="block truncate font-semibold">{node.title}</span>
                <span className="block truncate uppercase">{node.nodeType}</span>
              </button>
            ))}
          </div>
        </Card>

        <Card className="p-4" title="Structure canvas" description="Select a report item to inspect bindings, components, and slots.">
          <div className="max-h-[42rem] space-y-2 overflow-auto pr-1">
            {renderCanvasNodes({
              nodes: plan.planTree,
              depth: 0,
              selectedNodeId: selectedNode?.nodeId || '',
              dependencyGraph,
              issues,
              onSelect: (node) => setSelectedNodeId(node.nodeId),
            })}
          </div>
        </Card>

        <Card className="p-4" title="Inspector" description="Selected item controls.">
          {selectedNode ? (
            <div className="space-y-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="muted">{selectedNode.nodeType}</Badge>
                  <Badge variant={readinessVariant(selectedNode.readiness)}>{selectedNode.readiness}</Badge>
                </div>
                <p className="mt-2 text-sm font-semibold text-text">{selectedNode.title}</p>
                {selectedNode.questionId && <p className="mt-1 font-mono text-[11px] text-text-muted">{selectedNode.questionId}</p>}
              </div>

              <div className="flex flex-wrap gap-2">
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

              <div className="space-y-2 text-xs">
                <p className="font-semibold uppercase tracking-wide text-text-muted">Required entities</p>
                <p className="rounded-lg border border-border bg-surface px-3 py-2 text-text-muted">
                  {selectedNode.requiredEntities.length ? requiredEntitiesToText(selectedNode.requiredEntities) : 'No required entities recorded.'}
                </p>
              </div>

              <div className="space-y-2 text-xs">
                <p className="font-semibold uppercase tracking-wide text-text-muted">Resolved columns</p>
                <div className="flex flex-wrap gap-1.5">
                  {selectedColumns.length ? selectedColumns.map((column) => (
                    <span key={column} className="rounded bg-border px-2 py-0.5 text-text-muted">{column}</span>
                  )) : <span className="text-text-muted">No columns resolved yet.</span>}
                </div>
              </div>

              <div className="space-y-2 text-xs">
                <p className="font-semibold uppercase tracking-wide text-text-muted">Entity links</p>
                <div className="flex flex-wrap gap-1.5">
                  {selectedEntities.length ? selectedEntities.map((entityId) => (
                    <span key={entityId} className="rounded bg-border px-2 py-0.5 font-mono text-text-muted">{entityId}</span>
                  )) : <span className="text-text-muted">No linked entities found.</span>}
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Components</p>
                {selectedNode.components.length ? selectedNode.components.map((component) => {
                  const focused = initialComponentId === component.componentId;
                  return (
                  <div key={component.componentId} className={`rounded-lg border px-3 py-2 text-xs ${focused ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border bg-surface'}`}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-semibold text-text">{componentLabel(component.componentType, componentDefinitions)}</p>
                      {component.slotIds.length > 0 && <Badge variant="muted">{component.slotIds.length} slot{component.slotIds.length > 1 ? 's' : ''}</Badge>}
                    </div>
                    <button type="button" disabled={busy} onClick={() => onEditComponentEntities(selectedNode, component)} className="mt-1 font-semibold text-primary hover:underline disabled:opacity-50">
                      Component entities
                    </button>
                    {component.formulaSpec && Object.keys(component.formulaSpec).length > 0 && (
                      <button type="button" disabled={busy} onClick={() => onEditFormula(selectedNode, component)} className="ml-2 mt-1 font-semibold text-primary hover:underline disabled:opacity-50">
                        Edit formula spec
                      </button>
                    )}
                    {component.componentType === 'formula_metric' && Object.keys(component.formulaSpec || {}).length === 0 && (
                      <button type="button" disabled={busy} onClick={() => onEditFormula(selectedNode, component)} className="ml-2 mt-1 font-semibold text-primary hover:underline disabled:opacity-50">
                        Configure formula
                      </button>
                    )}
                    {['chart', 'table', 'formula_metric'].includes(component.componentType) && (
                      <button type="button" disabled={busy} onClick={() => onEditAnalytics(selectedNode, component)} className="ml-2 mt-1 font-semibold text-primary hover:underline disabled:opacity-50">
                        Analytics
                      </button>
                    )}
                  </div>
                  );
                }) : <p className="text-xs text-text-muted">No components attached yet.</p>}
              </div>

              {recommendations.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Recommended components</p>
                    {selectedNode.nodeId !== serverRecommendationState.nodeId && loadRecommendations && <span className="text-[11px] text-text-muted">Loading</span>}
                  </div>
                  <div className="grid gap-2">
                    {recommendations.map((recommendation) => {
                      const componentType = recommendation.componentType;
                      const Icon = componentIcon(componentType);
                      return (
                        <button
                          key={componentType}
                          type="button"
                          disabled={busy}
                          onClick={() => onAddRecommendedComponent(selectedNode.nodeId, componentType, recommendation.payload)}
                          className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs hover:border-accent/60 disabled:opacity-50"
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="flex min-w-0 items-center gap-2">
                              <Icon className="h-4 w-4 shrink-0 text-text-muted" />
                              <span className="truncate font-semibold text-text">{recommendation.label}</span>
                            </span>
                            <span className="flex shrink-0 items-center gap-2">
                              {recommendation.score > 0 && <Badge variant="muted">{Math.round(recommendation.score * 100)}%</Badge>}
                              <Plus className="h-4 w-4 text-primary" />
                            </span>
                          </span>
                          <span className="mt-1 block text-text-muted">{recommendation.reason}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {selectedIssues.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Issues on this item</p>
                  {selectedIssues.map((issue, index) => (
                    <div key={issue.issueId || `${issue.code || 'issue'}-${index}`} className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-text-muted">
                      <p className="font-semibold text-text">{issue.code || issue.severity || 'Issue'}</p>
                      <p className="mt-1">{issue.message}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-text-muted">Select a report item to inspect it.</p>
          )}
        </Card>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        {addQuestionSlot}
        {addComponentSlot}
      </div>
    </div>
  );
}

export default StructureCanvas;
