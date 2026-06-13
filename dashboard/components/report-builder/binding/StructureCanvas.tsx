'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, BarChart3, ChevronDown, ChevronRight, EyeOff, FileText, FunctionSquare, Image, ListTree, MessageSquare, Move, Pencil, Plus, Table2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ComponentFormFields, type ComponentFormData, type ComponentType } from './ComponentFormFields';
import { type EntityOption } from './EntitySelector';
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

export interface EntityPropagationRequest {
  nodeId: string;
  entityIds: string[];
  /** The chain of ancestor nodeIds that should receive these entities */
  ancestorNodeIds: string[];
}

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
  /** Called after component creation to propagate entities up the hierarchy */
  onPropagateEntities?: (request: EntityPropagationRequest) => void | Promise<void>;
  /** Called when a node is reordered (drag-dropped) */
  onReorderNode?: (sourceId: string, targetId: string) => void | Promise<void>;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function readinessVariant(readiness: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (readiness === 'READY' || readiness === 'executable') return 'success';
  if (readiness === 'DEGRADED' || readiness === 'degraded') return 'warning';
  if (readiness === 'BLOCKED' || readiness === 'blocked') return 'danger';
  return 'muted';
}

function flatten(nodes: ReviewedPlanNode[]): ReviewedPlanNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children)]);
}

function componentLabel(componentType: string, definitions: ComponentDefinition[]): string {
  return definitions.find((d) => d.componentType === componentType)?.label || componentType.replace(/_/g, ' ');
}

function componentIcon(componentType: string) {
  if (componentType === 'chart') return BarChart3;
  if (componentType === 'table') return Table2;
  if (componentType === 'formula_metric') return FunctionSquare;
  if (componentType === 'image' || componentType === 'infographic') return Image;
  if (componentType === 'key_finding' || componentType === 'narrative') return FileText;
  return MessageSquare;
}

function issueMatchesNode(issue: BindingWorkspaceIssue, node: ReviewedPlanNode, graph?: BindingDependencyGraph): boolean {
  if (issue.nodeId && node.nodeId === issue.nodeId) return true;
  if (issue.questionId && node.questionId === issue.questionId) return true;
  if (issue.componentId && node.components.some((c) => c.componentId === issue.componentId)) return true;
  if (issue.entityId && node.questionId) {
    return (graph?.questionToEntities[node.questionId] || []).includes(issue.entityId);
  }
  return false;
}

function nodeTypeLabel(nodeType: string): string {
  if (nodeType === 'topic') return 'Topic';
  if (nodeType === 'subtopic' || nodeType === 'chapter') return 'Chapter';
  if (nodeType === 'subsubtopic' || nodeType === 'section') return 'Section';
  if (nodeType === 'question') return 'Question';
  return nodeType;
}

function isChapterType(nodeType: string): boolean {
  return nodeType === 'subtopic' || nodeType === 'chapter';
}

function isSectionType(nodeType: string): boolean {
  return nodeType === 'subsubtopic' || nodeType === 'section';
}

function countDescendants(node: ReviewedPlanNode): { questions: number; components: number; charts: number; tables: number; narratives: number } {
  let questions = 0, components = 0, charts = 0, tables = 0, narratives = 0;
  if (node.nodeType === 'question') questions++;
  for (const comp of node.components) {
    components++;
    if (comp.componentType === 'chart') charts++;
    else if (comp.componentType === 'table') tables++;
    else if (comp.componentType === 'narrative' || comp.componentType === 'key_finding') narratives++;
  }
  for (const child of node.children) {
    const sub = countDescendants(child);
    questions += sub.questions; components += sub.components; charts += sub.charts; tables += sub.tables; narratives += sub.narratives;
  }
  return { questions, components, charts, tables, narratives };
}

/** Collect entities available from node + its ancestors */
function collectHierarchyEntities(node: ReviewedPlanNode, allNodes: ReviewedPlanNode[]): EntityOption[] {
  const result: EntityOption[] = [];
  const seen = new Set<string>();

  // From this node
  for (const e of node.requiredEntities) {
    const id = String(e.entityId || e.entityRef || '');
    if (id && !seen.has(id)) {
      seen.add(id);
      result.push({ entityId: id, entityName: id, role: String(e.role || 'measure'), source: node.nodeType, sourceLabel: node.title });
    }
  }

  // Walk up parents
  let parentId = node.parentId;
  while (parentId) {
    const parent = allNodes.find((n) => n.nodeId === parentId);
    if (!parent) break;
    for (const e of parent.requiredEntities) {
      const id = String(e.entityId || e.entityRef || '');
      if (id && !seen.has(id)) {
        seen.add(id);
        result.push({ entityId: id, entityName: id, role: String(e.role || 'measure'), source: parent.nodeType, sourceLabel: parent.title });
      }
    }
    parentId = parent.parentId;
  }

  // All other entities from the full tree
  for (const n of allNodes) {
    for (const e of n.requiredEntities) {
      const id = String(e.entityId || e.entityRef || '');
      if (id && !seen.has(id)) {
        seen.add(id);
        result.push({ entityId: id, entityName: id, role: String(e.role || 'measure'), source: 'all', sourceLabel: 'All confirmed entities' });
      }
    }
  }

  return result;
}

const INITIAL_FORM_DATA: ComponentFormData = {
  componentType: 'chart',
  title: '',
  analyticalQuestion: '',
  selectedEntities: [],
};

// ─── Tree Node (with drag-drop) ─────────────────────────────────────────────

function TreeNode({
  node, depth, selectedId, expandedIds, issues, dependencyGraph, dragOverId,
  onSelect, onToggleExpand, onDragStart, onDragOver, onDrop,
}: {
  node: ReviewedPlanNode;
  depth: number;
  selectedId: string;
  expandedIds: Set<string>;
  issues: BindingWorkspaceIssue[];
  dependencyGraph?: BindingDependencyGraph;
  dragOverId: string | null;
  onSelect: (id: string) => void;
  onToggleExpand: (id: string) => void;
  onDragStart: (nodeId: string) => void;
  onDragOver: (nodeId: string) => void;
  onDrop: (targetId: string) => void;
}) {
  const isSelected = selectedId === node.nodeId;
  const isExpanded = expandedIds.has(node.nodeId);
  const hasChildren = node.children.length > 0;
  const counts = useMemo(() => countDescendants(node), [node]);
  const nodeIssues = issues.filter((i) => issueMatchesNode(i, node, dependencyGraph));
  const isDragOver = dragOverId === node.nodeId;

  // Count issues from ALL descendants (for hierarchy propagation)
  const descendantIssueCount = useMemo(() => {
    let count = nodeIssues.length;
    const walkChildren = (children: ReviewedPlanNode[]) => {
      for (const child of children) {
        count += issues.filter((i) => issueMatchesNode(i, child, dependencyGraph)).length;
        walkChildren(child.children);
      }
    };
    walkChildren(node.children);
    return count;
  }, [node, issues, dependencyGraph, nodeIssues.length]);

  // Check if any descendant is blocked
  const hasBlockedDescendant = useMemo(() => {
    const checkBlocked = (n: ReviewedPlanNode): boolean => {
      if (n.readiness === 'BLOCKED' || n.readiness === 'blocked') return true;
      return n.children.some(checkBlocked);
    };
    return checkBlocked(node);
  }, [node]);

  // Node's own readiness or inherited danger
  const effectiveReadiness = node.readiness === 'unknown' && hasBlockedDescendant ? 'blocked' : node.readiness;

  return (
    <div>
      <div
        draggable
        onDragStart={(e) => { e.stopPropagation(); onDragStart(node.nodeId); }}
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); onDragOver(node.nodeId); }}
        onDrop={(e) => { e.preventDefault(); e.stopPropagation(); onDrop(node.nodeId); }}
        className={`group flex items-center gap-1 rounded-md px-1 py-1 text-xs transition-colors cursor-pointer ${isSelected ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface hover:text-text'} ${isDragOver ? 'ring-2 ring-primary/40 bg-primary/5' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        onClick={() => onSelect(node.nodeId)}
      >
        {hasChildren ? (
          <button type="button" className="flex h-4 w-4 shrink-0 items-center justify-center rounded hover:bg-border/60" onClick={(e) => { e.stopPropagation(); onToggleExpand(node.nodeId); }}>
            {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        ) : <span className="h-4 w-4 shrink-0" />}
        <span className={`h-2 w-2 shrink-0 rounded-full ${node.nodeType === 'topic' ? 'bg-primary' : isChapterType(node.nodeType) ? 'bg-accent' : node.nodeType === 'question' ? (effectiveReadiness === 'blocked' ? 'bg-danger' : 'bg-success') : 'bg-border'}`} />
        <span className="min-w-0 flex-1 truncate font-medium">{node.title}</span>
        <span className="flex shrink-0 items-center gap-1">
          {node.enabled === false && <Badge variant="muted" className="px-1 py-0 text-[8px]">off</Badge>}
          {hasBlockedDescendant && node.nodeType !== 'question' && <Badge variant="danger" className="px-1 py-0 text-[8px]">!</Badge>}
          {descendantIssueCount > 0 && <Badge variant="warning" className="px-1 py-0 text-[8px]">{descendantIssueCount}</Badge>}
          {node.nodeType !== 'question' && counts.questions > 0 && <span className="text-[9px] tabular-nums text-text-muted">{counts.questions}Q</span>}
          {counts.charts > 0 && <BarChart3 className="h-2.5 w-2.5 text-text-muted" />}
          {counts.tables > 0 && <Table2 className="h-2.5 w-2.5 text-text-muted" />}
        </span>
      </div>
      {hasChildren && isExpanded && node.children.map((child) => (
        <TreeNode key={child.nodeId} node={child} depth={depth + 1} selectedId={selectedId} expandedIds={expandedIds} issues={issues} dependencyGraph={dependencyGraph} dragOverId={dragOverId} onSelect={onSelect} onToggleExpand={onToggleExpand} onDragStart={onDragStart} onDragOver={onDragOver} onDrop={onDrop} />
      ))}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function StructureCanvas({
  plan, dependencyGraph, issues = [], componentDefinitions, busy,
  initialQuestionId, initialComponentId, editorSlot, addQuestionSlot, addComponentSlot,
  onRename, onToggle, onEditEntities, onEditComponentEntities, onEditFormula, onEditAnalytics,
  loadRecommendations, onAddRecommendedComponent, onPropagateEntities, onReorderNode,
}: StructureCanvasProps) {
  const allNodes = useMemo(() => flatten(plan.planTree), [plan.planTree]);
  const [selectedNodeId, setSelectedNodeId] = useState(() => (
    allNodes.find((n) => initialComponentId && n.components.some((c) => c.componentId === initialComponentId))?.nodeId
    || allNodes.find((n) => n.questionId === initialQuestionId)?.nodeId
    || plan.planTree[0]?.nodeId || ''
  ));
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    const ids = new Set<string>();
    for (const t of plan.planTree) { ids.add(t.nodeId); for (const c of t.children) ids.add(c.nodeId); }
    return ids;
  });

  // Add popup state
  const [showAddPopup, setShowAddPopup] = useState(false);
  const [addStep, setAddStep] = useState<'pick' | 'form'>('pick');
  const [addComponentType, setAddComponentType] = useState<ComponentType>('chart');
  const [addFormData, setAddFormData] = useState<ComponentFormData>(INITIAL_FORM_DATA);

  // Drag-drop reorder state
  const [dragSourceId, setDragSourceId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const [moveConfirm, setMoveConfirm] = useState<{ sourceId: string; targetId: string } | null>(null);

  const selectedNode = allNodes.find((n) => n.nodeId === selectedNodeId) || plan.planTree[0];
  const selectedCounts = useMemo(() => selectedNode ? countDescendants(selectedNode) : { questions: 0, components: 0, charts: 0, tables: 0, narratives: 0 }, [selectedNode]);
  const selectedIssues = selectedNode ? issues.filter((i) => issueMatchesNode(i, selectedNode, dependencyGraph)) : [];
  const selectedColumns = selectedNode?.questionId ? dependencyGraph?.questionToColumns[selectedNode.questionId] || [] : [];
  const selectedEntities = selectedNode?.questionId ? dependencyGraph?.questionToEntities[selectedNode.questionId] || [] : [];

  // Entity options for the form
  const formEntities = useMemo(() => selectedNode ? collectHierarchyEntities(selectedNode, allNodes) : [], [selectedNode, allNodes]);
  const formDimensions = useMemo(() => formEntities.filter((e) => e.role === 'dimension' || e.role === 'time'), [formEntities]);
  const formMeasures = useMemo(() => formEntities.filter((e) => e.role === 'measure'), [formEntities]);

  const toggleExpand = (id: string) => setExpandedIds((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const openAddPopup = () => { setAddStep('pick'); setAddFormData(INITIAL_FORM_DATA); setShowAddPopup(true); };
  const pickComponent = (type: ComponentType) => { setAddComponentType(type); setAddFormData({ ...INITIAL_FORM_DATA, componentType: type }); setAddStep('form'); };
  const submitComponent = () => {
    if (!selectedNode) return;
    const payload: Record<string, unknown> = { ...addFormData };
    onAddRecommendedComponent(selectedNode.nodeId, addComponentType, payload);

    // Propagate selected entities up the hierarchy
    if (onPropagateEntities && addFormData.selectedEntities.length > 0) {
      const ancestorIds: string[] = [];
      let parentId = selectedNode.parentId;
      while (parentId) {
        ancestorIds.push(parentId);
        const parent = allNodes.find((n) => n.nodeId === parentId);
        parentId = parent?.parentId;
      }
      if (ancestorIds.length > 0) {
        onPropagateEntities({
          nodeId: selectedNode.nodeId,
          entityIds: addFormData.selectedEntities,
          ancestorNodeIds: ancestorIds,
        });
      }
    }

    setShowAddPopup(false);
  };

  // Drag-drop handlers
  const handleDragStart = (nodeId: string) => setDragSourceId(nodeId);
  const handleDragOver = (nodeId: string) => { if (nodeId !== dragSourceId) setDragOverId(nodeId); };
  const handleDrop = (targetId: string) => {
    if (dragSourceId && dragSourceId !== targetId) {
      setMoveConfirm({ sourceId: dragSourceId, targetId });
    }
    setDragSourceId(null);
    setDragOverId(null);
  };
  const confirmMove = () => {
    if (!moveConfirm) return;
    if (onReorderNode) {
      onReorderNode(moveConfirm.sourceId, moveConfirm.targetId);
    }
    setMoveConfirm(null);
  };

  // ─── Component card renderer ──────────────────────────────────────────────

  const renderComponentCard = (node: ReviewedPlanNode, comp: ReviewedPlanComponent) => {
    const Icon = componentIcon(comp.componentType);
    const focused = initialComponentId === comp.componentId;
    return (
      <div key={comp.componentId} className={`rounded-lg border p-3 ${focused ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border bg-surface-card'}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Icon className="h-4 w-4 text-text-muted" />
            <span className="text-xs font-semibold text-text">{componentLabel(comp.componentType, componentDefinitions)}</span>
          </span>
          {comp.slotIds.length > 0 && <Badge variant="muted" className="text-[9px]">{comp.slotIds.length} slot{comp.slotIds.length > 1 ? 's' : ''}</Badge>}
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => onEditComponentEntities(node, comp)} className="text-[10px] font-semibold text-primary hover:underline disabled:opacity-50">Entities</button>
          {(comp.formulaSpec && Object.keys(comp.formulaSpec).length > 0) || comp.componentType === 'formula_metric' ? (
            <button type="button" disabled={busy} onClick={() => onEditFormula(node, comp)} className="text-[10px] font-semibold text-primary hover:underline disabled:opacity-50">
              {Object.keys(comp.formulaSpec || {}).length > 0 ? 'Edit formula' : 'Configure formula'}
            </button>
          ) : null}
          {['chart', 'table', 'formula_metric'].includes(comp.componentType) && (
            <button type="button" disabled={busy} onClick={() => onEditAnalytics(node, comp)} className="text-[10px] font-semibold text-primary hover:underline disabled:opacity-50">Analytics</button>
          )}
        </div>
      </div>
    );
  };

  // ─── Detail panel renderers ───────────────────────────────────────────────

  const renderTopicDetail = () => {
    if (!selectedNode) return null;
    return (
      <div className="space-y-4">
        {selectedNode.children.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {selectedNode.children.map((chapter) => {
              const c = countDescendants(chapter);
              return (
                <button key={chapter.nodeId} type="button" onClick={() => { setSelectedNodeId(chapter.nodeId); setExpandedIds((p) => new Set([...p, chapter.nodeId])); }} className="rounded-xl border border-border bg-surface p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5">
                  <div className="flex items-start justify-between gap-2">
                    <div><p className="truncate text-sm font-semibold text-text">{chapter.title}</p><p className="mt-0.5 text-[11px] uppercase text-text-muted">{nodeTypeLabel(chapter.nodeType)}</p></div>
                    <Badge variant={readinessVariant(chapter.readiness)} className="shrink-0 text-[9px]">{chapter.readiness}</Badge>
                  </div>
                  <div className="mt-3 grid grid-cols-4 gap-2 text-center text-[10px]">
                    <div className="rounded-md bg-border/40 px-1.5 py-1"><p className="font-semibold text-text">{chapter.children.length}</p><p className="text-text-muted">sections</p></div>
                    <div className="rounded-md bg-border/40 px-1.5 py-1"><p className="font-semibold text-text">{c.questions}</p><p className="text-text-muted">questions</p></div>
                    <div className="rounded-md bg-border/40 px-1.5 py-1"><p className="font-semibold text-text">{c.charts}</p><p className="text-text-muted">charts</p></div>
                    <div className="rounded-md bg-border/40 px-1.5 py-1"><p className="font-semibold text-text">{c.tables}</p><p className="text-text-muted">tables</p></div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : <p className="text-sm text-text-muted">No chapters yet. Click + to add one.</p>}
        {selectedNode.components.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Topic components</p>
            <div className="space-y-2">{selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}</div>
          </div>
        )}
      </div>
    );
  };

  const renderChapterDetail = () => {
    if (!selectedNode) return null;
    return (
      <div className="space-y-4">
        {selectedNode.children.length > 0 ? selectedNode.children.map((section) => (
          <div key={section.nodeId} className="rounded-xl border border-border bg-surface">
            <button type="button" onClick={() => setSelectedNodeId(section.nodeId)} className={`w-full rounded-t-xl border-b border-border px-4 py-3 text-left transition-colors ${selectedNodeId === section.nodeId ? 'bg-primary/5' : 'hover:bg-surface-card'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-accent" />
                  <span className="text-sm font-semibold text-text">{section.title}</span>
                  <Badge variant="muted" className="text-[9px]">{nodeTypeLabel(section.nodeType)}</Badge>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-text-muted">
                  {section.children.length > 0 && <span>{section.children.filter((c) => c.nodeType === 'question').length}Q</span>}
                  {section.components.length > 0 && <span>{section.components.length} comp</span>}
                  <Badge variant={readinessVariant(section.readiness)} className="text-[9px]">{section.readiness}</Badge>
                </div>
              </div>
            </button>
            <div className="divide-y divide-border">
              {(section.nodeType === 'question' ? [section] : section.children).map((item) => (
                <div key={item.nodeId} className={`cursor-pointer px-4 py-3 transition-colors ${selectedNodeId === item.nodeId ? 'bg-primary/5' : 'hover:bg-surface-card/50'}`} onClick={() => setSelectedNodeId(item.nodeId)}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 rounded-full ${item.nodeType === 'question' ? 'bg-success' : 'bg-border'}`} />
                      <span className="text-xs font-medium text-text">{item.title}</span>
                    </div>
                    <Badge variant={readinessVariant(item.readiness)} className="text-[8px]">{item.readiness}</Badge>
                  </div>
                  {item.components.length > 0 && (
                    <div className="ml-4 mt-2 flex flex-wrap gap-1.5">
                      {item.components.map((comp) => { const Icon = componentIcon(comp.componentType); return (<span key={comp.componentId} className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-card px-2 py-0.5 text-[10px] text-text-muted"><Icon className="h-3 w-3" />{componentLabel(comp.componentType, componentDefinitions)}</span>); })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )) : <p className="text-sm text-text-muted">No sections yet. Click + to add one.</p>}
        {selectedNode.components.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Chapter components</p>
            <div className="space-y-2">{selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}</div>
          </div>
        )}
      </div>
    );
  };

  const renderSectionDetail = () => {
    if (!selectedNode) return null;
    return (
      <div className="space-y-4">
        {selectedNode.children.length > 0 ? (
          <div className="space-y-3">
            {selectedNode.children.map((q) => (
              <div key={q.nodeId} className={`rounded-xl border p-4 transition-colors ${selectedNodeId === q.nodeId ? 'border-primary/30 bg-primary/5' : 'border-border bg-surface hover:border-primary/20'}`} onClick={() => setSelectedNodeId(q.nodeId)}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-success" />
                    <span className="text-sm font-medium text-text">{q.title}</span>
                  </div>
                  <Badge variant={readinessVariant(q.readiness)} className="text-[9px]">{q.readiness}</Badge>
                </div>
                {q.requiredEntities.length > 0 && (
                  <div className="ml-4 mt-2 flex flex-wrap gap-1">
                    {q.requiredEntities.map((e, i) => <span key={i} className="rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-medium text-primary">{String(e.entityId || e.entityRef || '')}</span>)}
                  </div>
                )}
                {q.components.length > 0 && (
                  <div className="ml-4 mt-2 space-y-1.5">
                    {q.components.map((comp) => {
                      const Icon = componentIcon(comp.componentType);
                      return (
                        <div key={comp.componentId} className="flex items-center justify-between rounded-lg border border-border bg-surface-card px-3 py-2">
                          <span className="flex items-center gap-2 text-xs"><Icon className="h-3.5 w-3.5 text-text-muted" /><span className="font-medium text-text">{componentLabel(comp.componentType, componentDefinitions)}</span></span>
                          <div className="flex gap-2">
                            <button type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); onEditComponentEntities(q, comp); }} className="text-[9px] font-semibold text-primary hover:underline">Entities</button>
                            {['chart', 'table', 'formula_metric'].includes(comp.componentType) && <button type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); onEditAnalytics(q, comp); }} className="text-[9px] font-semibold text-primary hover:underline">Config</button>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : <p className="text-sm text-text-muted">No questions yet. Click + to add one.</p>}
        {selectedNode.components.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Section components</p>
            <div className="space-y-2">{selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}</div>
          </div>
        )}
      </div>
    );
  };

  const renderQuestionDetail = () => {
    if (!selectedNode) return null;
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1"><p className="text-[10px] font-semibold uppercase text-text-muted">Entities</p><div className="rounded-lg border border-border bg-surface px-3 py-2">{selectedNode.requiredEntities.length ? <div className="flex flex-wrap gap-1">{selectedNode.requiredEntities.map((e, i) => <span key={i} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">{String(e.entityId || e.entityRef || '')}:{String(e.role || '')}</span>)}</div> : <span className="text-[10px] text-text-muted">None</span>}</div></div>
          <div className="space-y-1"><p className="text-[10px] font-semibold uppercase text-text-muted">Columns</p><div className="rounded-lg border border-border bg-surface px-3 py-2">{selectedColumns.length ? <div className="flex flex-wrap gap-1">{selectedColumns.map((c) => <span key={c} className="rounded bg-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted">{c}</span>)}</div> : <span className="text-[10px] text-text-muted">None</span>}</div></div>
          <div className="space-y-1"><p className="text-[10px] font-semibold uppercase text-text-muted">Entity links</p><div className="rounded-lg border border-border bg-surface px-3 py-2">{selectedEntities.length ? <div className="flex flex-wrap gap-1">{selectedEntities.map((eid) => <span key={eid} className="rounded bg-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted">{eid}</span>)}</div> : <span className="text-[10px] text-text-muted">None</span>}</div></div>
        </div>
        {/* Components listed vertically */}
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Components</p>
          {selectedNode.components.length ? (
            <div className="space-y-2">{selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}</div>
          ) : <p className="text-xs text-text-muted">No components yet. Click + to add one.</p>}
        </div>
        {selectedIssues.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase text-text-muted">Issues</p>
            {selectedIssues.map((issue, i) => <div key={issue.issueId || `i-${i}`} className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs"><p className="font-semibold text-text">{issue.code || 'Issue'}</p><p className="mt-0.5 text-text-muted">{issue.message}</p></div>)}
          </div>
        )}
      </div>
    );
  };

  const renderDetail = () => {
    if (!selectedNode) return <p className="py-8 text-center text-sm text-text-muted">Select an item from the tree.</p>;
    if (selectedNode.nodeType === 'topic') return renderTopicDetail();
    if (isChapterType(selectedNode.nodeType)) return renderChapterDetail();
    if (isSectionType(selectedNode.nodeType)) return renderSectionDetail();
    return renderQuestionDetail();
  };

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Summary stats */}
      <div className="grid gap-3 rounded-xl border border-border bg-surface p-3 text-sm sm:grid-cols-5">
        <div className="text-center"><p className="text-[10px] uppercase text-text-muted">Topics</p><p className="font-semibold text-text">{plan.topicCount}</p></div>
        <div className="text-center"><p className="text-[10px] uppercase text-text-muted">Chapters</p><p className="font-semibold text-text">{plan.planTree.reduce((s, t) => s + t.children.length, 0)}</p></div>
        <div className="text-center"><p className="text-[10px] uppercase text-text-muted">Questions</p><p className="font-semibold text-text">{plan.questionCount}</p></div>
        <div className="text-center"><p className="text-[10px] uppercase text-text-muted">Components</p><p className="font-semibold text-text">{plan.componentCount}</p></div>
        <div className="text-center"><p className="text-[10px] uppercase text-text-muted">Slots</p><p className="font-semibold text-text">{plan.semanticSlotCount}</p></div>
      </div>

      {editorSlot}

      <div className="grid gap-4 xl:grid-cols-[18rem_1fr]">
        {/* Left: tree with + for new topic */}
        <div className="rounded-xl border border-border bg-surface-card">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Report structure</p>
            <button type="button" onClick={() => { setAddStep('pick'); setShowAddPopup(true); }} className="flex h-5 w-5 items-center justify-center rounded hover:bg-border/60 text-text-muted hover:text-primary" title="Add new topic">
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="max-h-[52rem] overflow-auto p-2">
            {plan.planTree.map((topic) => (
              <TreeNode key={topic.nodeId} node={topic} depth={0} selectedId={selectedNodeId} expandedIds={expandedIds} issues={issues} dependencyGraph={dependencyGraph} dragOverId={dragOverId} onSelect={setSelectedNodeId} onToggleExpand={toggleExpand} onDragStart={handleDragStart} onDragOver={handleDragOver} onDrop={handleDrop} />
            ))}
          </div>
        </div>

        {/* Right: detail */}
        <div className="rounded-xl border border-border bg-surface-card">
          {selectedNode && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
              <div className="flex items-center gap-2">
                <Badge variant="muted" className="text-[9px]">{nodeTypeLabel(selectedNode.nodeType)}</Badge>
                <h3 className="text-sm font-semibold text-text">{selectedNode.title}</h3>
                <Badge variant={readinessVariant(selectedNode.readiness)} className="text-[9px]">{selectedNode.readiness}</Badge>
              </div>
              <div className="flex items-center gap-1.5">
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => onRename(selectedNode)} className="h-7 px-2 text-[10px]"><Pencil className="h-3 w-3" /> Rename</Button>
                {selectedNode.nodeType === 'question' && (
                  <>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => onToggle(selectedNode)} className="h-7 px-2 text-[10px]"><EyeOff className="h-3 w-3" /> {selectedNode.enabled === false ? 'Enable' : 'Disable'}</Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => onEditEntities(selectedNode)} className="h-7 px-2 text-[10px]"><ListTree className="h-3 w-3" /> Entities</Button>
                  </>
                )}
                <Button size="sm" variant="ghost" disabled={busy} onClick={openAddPopup} className="h-7 w-7 px-0 text-primary"><Plus className="h-4 w-4" /></Button>
              </div>
            </div>
          )}
          {selectedNode && selectedNode.nodeType !== 'question' && (
            <div className="flex items-center gap-3 border-b border-border bg-surface px-5 py-2 text-[10px] text-text-muted">
              <span>{selectedCounts.questions} questions</span><span className="text-border">|</span>
              <span>{selectedCounts.charts} charts</span><span className="text-border">|</span>
              <span>{selectedCounts.tables} tables</span><span className="text-border">|</span>
              <span>{selectedCounts.narratives} narratives</span><span className="text-border">|</span>
              <span>{selectedCounts.components} total</span>
            </div>
          )}
          <div className="p-5">{renderDetail()}</div>
        </div>
      </div>

      {/* ─── Multi-step Add Popup ─── */}
      {showAddPopup && selectedNode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowAddPopup(false)}>
          <div className="max-h-[85vh] w-[min(92vw,36rem)] overflow-auto rounded-2xl border border-border bg-surface-card p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-text">{addStep === 'pick' ? `Add to "${selectedNode.title}"` : `New ${addComponentType.replace(/_/g, ' ')}`}</h3>
                <p className="mt-0.5 text-[11px] text-text-muted">{addStep === 'pick' ? `${nodeTypeLabel(selectedNode.nodeType)} · Choose what to add` : 'Fill in the details below'}</p>
              </div>
              <div className="flex gap-1">
                {addStep === 'form' && <button type="button" onClick={() => setAddStep('pick')} className="rounded-md px-2 py-1 text-xs text-text-muted hover:bg-border/60">← Back</button>}
                <button type="button" onClick={() => setShowAddPopup(false)} className="rounded-md p-1 text-text-muted hover:bg-border/60 hover:text-text"><Plus className="h-4 w-4 rotate-45" /></button>
              </div>
            </div>

            {/* Step 1: Pick what to add */}
            {addStep === 'pick' && (
              <div className="space-y-4">
                {/* Structural */}
                {selectedNode.nodeType !== 'question' && (
                  <div className="space-y-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Structure</p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {selectedNode.nodeType === 'topic' && (
                        <button type="button" onClick={() => pickComponent('narrative' as ComponentType)} className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs hover:border-accent/60">
                          <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-accent" /><span className="font-semibold text-text">New Chapter</span></span>
                          <span className="mt-0.5 block text-text-muted">Add sub-section with heading + entities</span>
                        </button>
                      )}
                      {(isChapterType(selectedNode.nodeType) || isSectionType(selectedNode.nodeType)) && (
                        <button type="button" onClick={() => pickComponent('narrative' as ComponentType)} className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs hover:border-accent/60">
                          <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-border" /><span className="font-semibold text-text">New Section</span></span>
                          <span className="mt-0.5 block text-text-muted">Add section with heading + entities</span>
                        </button>
                      )}
                      <button type="button" onClick={() => pickComponent('narrative' as ComponentType)} className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs hover:border-accent/60">
                        <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-success" /><span className="font-semibold text-text">New Question</span></span>
                        <span className="mt-0.5 block text-text-muted">Analytical question + entities</span>
                      </button>
                    </div>
                  </div>
                )}
                {/* Components */}
                <div className="space-y-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Components</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {([
                      { type: 'chart' as ComponentType, label: 'Chart', desc: 'Bar, line, pie, area + config', icon: BarChart3 },
                      { type: 'table' as ComponentType, label: 'Table', desc: 'Row/column structured data', icon: Table2 },
                      { type: 'formula_metric' as ComponentType, label: 'Formula Metric', desc: 'SHARE, RATE, RATIO, GROWTH', icon: FunctionSquare },
                      { type: 'narrative' as ComponentType, label: 'Narrative', desc: 'Analytical paragraph', icon: FileText },
                      { type: 'key_finding' as ComponentType, label: 'Key Finding', desc: 'Highlighted insight', icon: FileText },
                      { type: 'source_note' as ComponentType, label: 'Source Note', desc: 'Data attribution', icon: MessageSquare },
                      { type: 'methodology_note' as ComponentType, label: 'Methodology', desc: 'Calculation method', icon: MessageSquare },
                      { type: 'data_caveat' as ComponentType, label: 'Data Caveat', desc: 'Missing/estimated warning', icon: MessageSquare },
                      { type: 'footnote' as ComponentType, label: 'Footnote', desc: 'Reference note', icon: MessageSquare },
                      { type: 'glossary_term' as ComponentType, label: 'Glossary Term', desc: 'Definition of a term', icon: MessageSquare },
                    ]).map(({ type, label, desc, icon: Icon }) => (
                      <button key={type} type="button" onClick={() => pickComponent(type)} className="rounded-lg border border-border bg-surface px-3 py-2.5 text-left text-xs transition-colors hover:border-primary/40 hover:bg-primary/5">
                        <span className="flex items-center gap-2"><Icon className="h-4 w-4 text-text-muted" /><span className="font-semibold text-text">{label}</span></span>
                        <span className="mt-0.5 block text-[10px] text-text-muted">{desc}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Step 2: Component form */}
            {addStep === 'form' && (
              <div className="space-y-4">
                <ComponentFormFields
                  componentType={addComponentType}
                  formData={addFormData}
                  onChange={(partial) => setAddFormData((prev) => ({ ...prev, ...partial }))}
                  entities={formEntities}
                  dimensions={formDimensions}
                  measures={formMeasures}
                />
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" size="sm" onClick={() => setShowAddPopup(false)}>Cancel</Button>
                  <Button size="sm" disabled={busy || !addFormData.title.trim()} onClick={submitComponent}>
                    <Plus className="h-3.5 w-3.5" /> Create {addComponentType.replace(/_/g, ' ')}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ─── Move Confirmation Dialog ─── */}
      {moveConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setMoveConfirm(null)}>
          <div className="w-[min(92vw,28rem)] rounded-2xl border border-border bg-surface-card p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10"><Move className="h-5 w-5 text-primary" /></div>
              <div>
                <h3 className="text-sm font-semibold text-text">Confirm move</h3>
                <p className="mt-0.5 text-[11px] text-text-muted">This will reorder the report structure.</p>
              </div>
            </div>
            <div className="mb-4 rounded-lg border border-border bg-surface p-3 text-xs">
              <p className="text-text-muted">Moving:</p>
              <p className="mt-1 font-semibold text-text">{allNodes.find((n) => n.nodeId === moveConfirm.sourceId)?.title || moveConfirm.sourceId}</p>
              <p className="mt-2 text-text-muted">To position of:</p>
              <p className="mt-1 font-semibold text-text">{allNodes.find((n) => n.nodeId === moveConfirm.targetId)?.title || moveConfirm.targetId}</p>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setMoveConfirm(null)}>Cancel</Button>
              <Button size="sm" onClick={confirmMove}><Move className="h-3.5 w-3.5" /> Confirm move</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default StructureCanvas;
