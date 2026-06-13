'use client';

import { useEffect, useMemo, useState } from 'react';
import { BarChart3, ChevronDown, ChevronRight, EyeOff, FileText, FunctionSquare, Image, ListTree, MessageSquare, Pencil, Plus, Table2 } from 'lucide-react';

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
  if (componentType === 'source_note' || componentType === 'footnote' || componentType === 'methodology_note' || componentType === 'data_caveat' || componentType === 'glossary_term') return MessageSquare;
  return Plus;
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
  if (nodeType === 'subtopic') return 'Chapter';
  if (nodeType === 'subsubtopic') return 'Section';
  if (nodeType === 'question') return 'Question';
  return nodeType;
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
    questions += sub.questions;
    components += sub.components;
    charts += sub.charts;
    tables += sub.tables;
    narratives += sub.narratives;
  }
  return { questions, components, charts, tables, narratives };
}

function recommendedComponentTypes(node: ReviewedPlanNode, definitions: ComponentDefinition[]): string[] {
  if (node.nodeType !== 'question') return [];
  const available = new Set(definitions.map((d) => d.componentType));
  const text = `${node.title} ${JSON.stringify(node.requiredEntities)}`.toLowerCase();
  const recs = ['key_finding', 'narrative'];
  if (text.includes('trend') || text.includes('time') || text.includes('year')) recs.push('chart');
  if (text.includes('compare') || text.includes('across') || text.includes('sector')) recs.push('chart', 'table');
  if (text.includes('rate') || text.includes('ratio') || text.includes('share')) recs.push('formula_metric');
  recs.push('source_note');
  return Array.from(new Set(recs)).filter((t) => available.size === 0 || available.has(t));
}

// ─── Tree Node Component ────────────────────────────────────────────────────

function TreeNode({
  node,
  depth,
  selectedId,
  expandedIds,
  issues,
  dependencyGraph,
  onSelect,
  onToggleExpand,
}: {
  node: ReviewedPlanNode;
  depth: number;
  selectedId: string;
  expandedIds: Set<string>;
  issues: BindingWorkspaceIssue[];
  dependencyGraph?: BindingDependencyGraph;
  onSelect: (id: string) => void;
  onToggleExpand: (id: string) => void;
}) {
  const isSelected = selectedId === node.nodeId;
  const isExpanded = expandedIds.has(node.nodeId);
  const hasChildren = node.children.length > 0;
  const counts = useMemo(() => countDescendants(node), [node]);
  const nodeIssues = issues.filter((i) => issueMatchesNode(i, node, dependencyGraph));

  return (
    <div>
      <div
        className={`group flex items-center gap-1 rounded-md px-1 py-1 text-xs transition-colors cursor-pointer ${isSelected ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface hover:text-text'}`}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        onClick={() => onSelect(node.nodeId)}
      >
        {hasChildren ? (
          <button
            type="button"
            className="flex h-4 w-4 shrink-0 items-center justify-center rounded hover:bg-border/60"
            onClick={(e) => { e.stopPropagation(); onToggleExpand(node.nodeId); }}
          >
            {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        ) : (
          <span className="h-4 w-4 shrink-0" />
        )}
        <span className={`h-2 w-2 shrink-0 rounded-full ${node.nodeType === 'topic' ? 'bg-primary' : node.nodeType === 'subtopic' ? 'bg-accent' : node.nodeType === 'question' ? 'bg-success' : 'bg-border'}`} />
        <span className="min-w-0 flex-1 truncate font-medium">{node.title}</span>
        <span className="flex shrink-0 items-center gap-1">
          {node.enabled === false && <Badge variant="muted" className="px-1 py-0 text-[8px]">off</Badge>}
          {nodeIssues.length > 0 && <Badge variant="warning" className="px-1 py-0 text-[8px]">{nodeIssues.length}</Badge>}
          {node.nodeType !== 'question' && counts.questions > 0 && (
            <span className="text-[9px] tabular-nums text-text-muted">{counts.questions}Q</span>
          )}
          {counts.charts > 0 && <BarChart3 className="h-2.5 w-2.5 text-text-muted" />}
          {counts.tables > 0 && <Table2 className="h-2.5 w-2.5 text-text-muted" />}
        </span>
      </div>
      {hasChildren && isExpanded && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.nodeId}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              expandedIds={expandedIds}
              issues={issues}
              dependencyGraph={dependencyGraph}
              onSelect={onSelect}
              onToggleExpand={onToggleExpand}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

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
  const allNodes = useMemo(() => flatten(plan.planTree), [plan.planTree]);
  const [selectedNodeId, setSelectedNodeId] = useState(() => (
    allNodes.find((n) => initialComponentId && n.components.some((c) => c.componentId === initialComponentId))?.nodeId
    || allNodes.find((n) => n.questionId === initialQuestionId)?.nodeId
    || plan.planTree[0]?.nodeId
    || ''
  ));
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    const ids = new Set<string>();
    for (const topic of plan.planTree) {
      ids.add(topic.nodeId);
      for (const chapter of topic.children) {
        ids.add(chapter.nodeId);
      }
    }
    return ids;
  });
  const [serverRecs, setServerRecs] = useState<{ nodeId: string; items: ComponentRecommendation[] }>({ nodeId: '', items: [] });
  const [showAddPopup, setShowAddPopup] = useState(false);

  const selectedNode = allNodes.find((n) => n.nodeId === selectedNodeId) || plan.planTree[0];
  const selectedIssues = selectedNode ? issues.filter((i) => issueMatchesNode(i, selectedNode, dependencyGraph)) : [];
  const selectedColumns = selectedNode?.questionId ? dependencyGraph?.questionToColumns[selectedNode.questionId] || [] : [];
  const selectedEntities = selectedNode?.questionId ? dependencyGraph?.questionToEntities[selectedNode.questionId] || [] : [];
  const selectedCounts = useMemo(() => selectedNode ? countDescendants(selectedNode) : { questions: 0, components: 0, charts: 0, tables: 0, narratives: 0 }, [selectedNode]);

  const heuristicRecs = selectedNode ? recommendedComponentTypes(selectedNode, componentDefinitions) : [];
  const serverRecsForNode = selectedNode?.nodeId === serverRecs.nodeId ? serverRecs.items : [];
  const recommendations = serverRecsForNode.length
    ? serverRecsForNode.map((r) => ({ componentType: r.component_type, label: r.label, score: r.score, reason: r.reason, payload: r.payload }))
    : heuristicRecs.map((t) => ({ componentType: t, label: componentLabel(t, componentDefinitions), score: 0, reason: 'Suggested from question context.', payload: {} }));

  useEffect(() => {
    let cancelled = false;
    if (!selectedNode?.nodeId || !loadRecommendations || selectedNode.nodeType !== 'question') return;
    loadRecommendations(selectedNode.nodeId)
      .then((items) => { if (!cancelled) setServerRecs({ nodeId: selectedNode.nodeId, items }); })
      .catch(() => { if (!cancelled) setServerRecs({ nodeId: selectedNode.nodeId, items: [] }); });
    return () => { cancelled = true; };
  }, [loadRecommendations, selectedNode?.nodeId, selectedNode?.nodeType]);

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
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
    const chapters = selectedNode.children;
    return (
      <div className="space-y-4">
        {chapters.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {chapters.map((chapter) => {
              const c = countDescendants(chapter);
              return (
                <button
                  key={chapter.nodeId}
                  type="button"
                  onClick={() => { setSelectedNodeId(chapter.nodeId); setExpandedIds((p) => new Set([...p, chapter.nodeId])); }}
                  className="rounded-xl border border-border bg-surface p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-text">{chapter.title}</p>
                      <p className="mt-0.5 text-[11px] uppercase text-text-muted">{nodeTypeLabel(chapter.nodeType)}</p>
                    </div>
                    <Badge variant={readinessVariant(chapter.readiness)} className="shrink-0 text-[9px]">{chapter.readiness}</Badge>
                  </div>
                  <div className="mt-3 grid grid-cols-4 gap-2 text-center text-[10px]">
                    <div className="rounded-md bg-border/40 px-1.5 py-1">
                      <p className="font-semibold text-text">{chapter.children.length}</p>
                      <p className="text-text-muted">sections</p>
                    </div>
                    <div className="rounded-md bg-border/40 px-1.5 py-1">
                      <p className="font-semibold text-text">{c.questions}</p>
                      <p className="text-text-muted">questions</p>
                    </div>
                    <div className="rounded-md bg-border/40 px-1.5 py-1">
                      <p className="font-semibold text-text">{c.charts}</p>
                      <p className="text-text-muted">charts</p>
                    </div>
                    <div className="rounded-md bg-border/40 px-1.5 py-1">
                      <p className="font-semibold text-text">{c.tables}</p>
                      <p className="text-text-muted">tables</p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-text-muted">No chapters under this topic yet.</p>
        )}
        {selectedNode.components.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Topic components</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderChapterDetail = () => {
    if (!selectedNode) return null;
    const sections = selectedNode.children;
    return (
      <div className="space-y-4">
        {sections.length > 0 ? sections.map((section) => (
          <div key={section.nodeId} className="rounded-xl border border-border bg-surface">
            <button
              type="button"
              onClick={() => setSelectedNodeId(section.nodeId)}
              className={`w-full rounded-t-xl border-b border-border px-4 py-3 text-left transition-colors ${selectedNodeId === section.nodeId ? 'bg-primary/5' : 'hover:bg-surface-card'}`}
            >
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
                <div
                  key={item.nodeId}
                  className={`cursor-pointer px-4 py-3 transition-colors ${selectedNodeId === item.nodeId ? 'bg-primary/5' : 'hover:bg-surface-card/50'}`}
                  onClick={() => setSelectedNodeId(item.nodeId)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 rounded-full ${item.nodeType === 'question' ? 'bg-success' : 'bg-border'}`} />
                        <span className="text-xs font-medium text-text">{item.title}</span>
                      </div>
                      {item.questionId && <p className="ml-4 mt-0.5 font-mono text-[10px] text-text-muted">{item.questionId}</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {item.enabled === false && <Badge variant="muted" className="text-[8px]">off</Badge>}
                      <Badge variant={readinessVariant(item.readiness)} className="text-[8px]">{item.readiness}</Badge>
                    </div>
                  </div>
                  {item.components.length > 0 && (
                    <div className="ml-4 mt-2 flex flex-wrap gap-1.5">
                      {item.components.map((comp) => {
                        const Icon = componentIcon(comp.componentType);
                        return (
                          <span key={comp.componentId} className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-card px-2 py-0.5 text-[10px] text-text-muted">
                            <Icon className="h-3 w-3" />
                            {componentLabel(comp.componentType, componentDefinitions)}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )) : (
          <p className="text-sm text-text-muted">No sections in this chapter yet.</p>
        )}
        {selectedNode.components.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Chapter components</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderSectionDetail = () => {
    if (!selectedNode) return null;
    const questions = selectedNode.children;
    return (
      <div className="space-y-4">
        {/* Questions with their components */}
        {questions.length > 0 ? (
          <div className="space-y-3">
            {questions.map((q) => (
              <div
                key={q.nodeId}
                className={`cursor-pointer rounded-xl border p-4 transition-colors ${selectedNodeId === q.nodeId ? 'border-primary/30 bg-primary/5' : 'border-border bg-surface hover:border-primary/20'}`}
                onClick={() => setSelectedNodeId(q.nodeId)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full bg-success" />
                      <span className="text-sm font-medium text-text">{q.title}</span>
                    </div>
                    {q.questionId && <p className="ml-4 mt-0.5 font-mono text-[10px] text-text-muted">{q.questionId}</p>}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {q.enabled === false && <Badge variant="muted" className="text-[8px]">off</Badge>}
                    <Badge variant={readinessVariant(q.readiness)} className="text-[9px]">{q.readiness}</Badge>
                  </div>
                </div>
                {/* Required entities for the question */}
                {q.requiredEntities.length > 0 && (
                  <div className="ml-4 mt-2 flex flex-wrap gap-1">
                    {q.requiredEntities.map((e, i) => (
                      <span key={i} className="rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-medium text-primary">
                        {String(e.entityId || e.entityRef || '')}
                      </span>
                    ))}
                  </div>
                )}
                {/* Components inline */}
                {q.components.length > 0 && (
                  <div className="ml-4 mt-2 space-y-1.5">
                    {q.components.map((comp) => {
                      const Icon = componentIcon(comp.componentType);
                      return (
                        <div key={comp.componentId} className="flex items-center justify-between rounded-lg border border-border bg-surface-card px-3 py-2">
                          <span className="flex items-center gap-2 text-xs">
                            <Icon className="h-3.5 w-3.5 text-text-muted" />
                            <span className="font-medium text-text">{componentLabel(comp.componentType, componentDefinitions)}</span>
                            {comp.slotIds.length > 0 && <Badge variant="muted" className="text-[8px]">{comp.slotIds.length}s</Badge>}
                          </span>
                          <div className="flex gap-2">
                            <button type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); onEditComponentEntities(q, comp); }} className="text-[9px] font-semibold text-primary hover:underline disabled:opacity-50">Entities</button>
                            {['chart', 'table', 'formula_metric'].includes(comp.componentType) && (
                              <button type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); onEditAnalytics(q, comp); }} className="text-[9px] font-semibold text-primary hover:underline disabled:opacity-50">Config</button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-text-muted">No questions in this section yet.</p>
        )}
        {/* Section-level components */}
        {selectedNode.components.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Section components</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}
            </div>
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
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Required entities</p>
            <div className="rounded-lg border border-border bg-surface px-3 py-2">
              {selectedNode.requiredEntities.length ? (
                <div className="flex flex-wrap gap-1">
                  {selectedNode.requiredEntities.map((e, i) => (
                    <span key={i} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      {String(e.entityId || e.entityRef || '')}:{String(e.role || '')}
                    </span>
                  ))}
                </div>
              ) : <span className="text-[10px] text-text-muted">None</span>}
            </div>
          </div>
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Columns</p>
            <div className="rounded-lg border border-border bg-surface px-3 py-2">
              {selectedColumns.length ? (
                <div className="flex flex-wrap gap-1">
                  {selectedColumns.map((c) => <span key={c} className="rounded bg-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted">{c}</span>)}
                </div>
              ) : <span className="text-[10px] text-text-muted">No columns</span>}
            </div>
          </div>
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Entity links</p>
            <div className="rounded-lg border border-border bg-surface px-3 py-2">
              {selectedEntities.length ? (
                <div className="flex flex-wrap gap-1">
                  {selectedEntities.map((eid) => <span key={eid} className="rounded bg-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted">{eid}</span>)}
                </div>
              ) : <span className="text-[10px] text-text-muted">None</span>}
            </div>
          </div>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Components</p>
          {selectedNode.components.length ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {selectedNode.components.map((comp) => renderComponentCard(selectedNode, comp))}
            </div>
          ) : <p className="text-xs text-text-muted">No components yet. Use the toolbar below to add one.</p>}
        </div>
        {recommendations.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Suggested components</p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {recommendations.map((rec) => {
                const Icon = componentIcon(rec.componentType);
                return (
                  <button
                    key={rec.componentType}
                    type="button"
                    disabled={busy}
                    onClick={() => onAddRecommendedComponent(selectedNode.nodeId, rec.componentType, rec.payload)}
                    className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs transition-colors hover:border-accent/60 disabled:opacity-50"
                  >
                    <span className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5 text-text-muted" />
                      <span className="font-semibold text-text">{rec.label}</span>
                      {rec.score > 0 && <Badge variant="muted" className="ml-auto text-[8px]">{Math.round(rec.score * 100)}%</Badge>}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {selectedIssues.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Issues</p>
            {selectedIssues.map((issue, i) => (
              <div key={issue.issueId || `issue-${i}`} className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs">
                <p className="font-semibold text-text">{issue.code || 'Issue'}</p>
                <p className="mt-0.5 text-text-muted">{issue.message}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderDetail = () => {
    if (!selectedNode) return <p className="py-8 text-center text-sm text-text-muted">Select an item from the tree.</p>;
    if (selectedNode.nodeType === 'topic') return renderTopicDetail();
    // Chapter (subtopic) → show section cards with questions inside
    if (selectedNode.nodeType === 'subtopic') return renderChapterDetail();
    // Section (subsubtopic) OR a question-container → show questions inline
    if (selectedNode.nodeType === 'subsubtopic') return renderSectionDetail();
    return renderQuestionDetail();
  };

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Summary stats */}
      <div className="grid gap-3 rounded-xl border border-border bg-surface p-3 text-sm sm:grid-cols-5">
        <div className="text-center">
          <p className="text-[10px] uppercase text-text-muted">Topics</p>
          <p className="font-semibold text-text">{plan.topicCount}</p>
        </div>
        <div className="text-center">
          <p className="text-[10px] uppercase text-text-muted">Chapters</p>
          <p className="font-semibold text-text">{plan.planTree.reduce((sum, t) => sum + t.children.length, 0)}</p>
        </div>
        <div className="text-center">
          <p className="text-[10px] uppercase text-text-muted">Questions</p>
          <p className="font-semibold text-text">{plan.questionCount}</p>
        </div>
        <div className="text-center">
          <p className="text-[10px] uppercase text-text-muted">Components</p>
          <p className="font-semibold text-text">{plan.componentCount}</p>
        </div>
        <div className="text-center">
          <p className="text-[10px] uppercase text-text-muted">Slots</p>
          <p className="font-semibold text-text">{plan.semanticSlotCount}</p>
        </div>
      </div>

      {editorSlot}

      {/* Main 2-panel layout */}
      <div className="grid gap-4 xl:grid-cols-[18rem_1fr]">
        {/* Left: file-tree style navigator */}
        <div className="rounded-xl border border-border bg-surface-card">
          <div className="border-b border-border px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Report structure</p>
          </div>
          <div className="max-h-[52rem] overflow-auto p-2">
            {plan.planTree.map((topic) => (
              <TreeNode
                key={topic.nodeId}
                node={topic}
                depth={0}
                selectedId={selectedNodeId}
                expandedIds={expandedIds}
                issues={issues}
                dependencyGraph={dependencyGraph}
                onSelect={setSelectedNodeId}
                onToggleExpand={toggleExpand}
              />
            ))}
          </div>
        </div>

        {/* Right: detail panel */}
        <div className="rounded-xl border border-border bg-surface-card">
          {selectedNode && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
              <div className="flex items-center gap-2">
                <Badge variant="muted" className="text-[9px]">{nodeTypeLabel(selectedNode.nodeType)}</Badge>
                <h3 className="text-sm font-semibold text-text">{selectedNode.title}</h3>
                <Badge variant={readinessVariant(selectedNode.readiness)} className="text-[9px]">{selectedNode.readiness}</Badge>
              </div>
              <div className="flex items-center gap-1.5">
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => onRename(selectedNode)} className="h-7 px-2 text-[10px]">
                  <Pencil className="h-3 w-3" /> Rename
                </Button>
                {selectedNode.nodeType === 'question' && (
                  <>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => onToggle(selectedNode)} className="h-7 px-2 text-[10px]">
                      <EyeOff className="h-3 w-3" /> {selectedNode.enabled === false ? 'Enable' : 'Disable'}
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => onEditEntities(selectedNode)} className="h-7 px-2 text-[10px]">
                      <ListTree className="h-3 w-3" /> Entities
                    </Button>
                  </>
                )}
                {/* Add child / component button */}
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => setShowAddPopup(true)} className="h-7 w-7 px-0 text-primary">
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
          {selectedNode && selectedNode.nodeType !== 'question' && (
            <div className="flex items-center gap-3 border-b border-border bg-surface px-5 py-2 text-[10px] text-text-muted">
              <span>{selectedCounts.questions} questions</span>
              <span className="text-border">|</span>
              <span>{selectedCounts.charts} charts</span>
              <span className="text-border">|</span>
              <span>{selectedCounts.tables} tables</span>
              <span className="text-border">|</span>
              <span>{selectedCounts.narratives} narratives</span>
              <span className="text-border">|</span>
              <span>{selectedCounts.components} total</span>
            </div>
          )}
          <div className="p-5">
            {renderDetail()}
          </div>
        </div>
      </div>

      {/* Add popup (triggered by + icon in header) */}
      {showAddPopup && selectedNode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowAddPopup(false)}>
          <div className="w-[min(92vw,28rem)] rounded-2xl border border-border bg-surface-card p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-text">Add to "{selectedNode.title}"</h3>
                <p className="mt-0.5 text-[11px] text-text-muted">{nodeTypeLabel(selectedNode.nodeType)} · Choose what to add</p>
              </div>
              <button type="button" onClick={() => setShowAddPopup(false)} className="rounded-md p-1 text-text-muted hover:bg-border/60 hover:text-text">
                <Plus className="h-4 w-4 rotate-45" />
              </button>
            </div>

            {/* Structural items (for non-question nodes) */}
            {selectedNode.nodeType !== 'question' && (
              <div className="mb-4 space-y-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Structure</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {selectedNode.nodeType === 'topic' && (
                    <button type="button" className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs hover:border-accent/60" onClick={() => setShowAddPopup(false)}>
                      <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-accent" /><span className="font-semibold text-text">New Chapter</span></span>
                      <span className="mt-0.5 block text-text-muted">Add a sub-section under this topic</span>
                    </button>
                  )}
                  {(selectedNode.nodeType === 'subtopic' || selectedNode.nodeType === 'subsubtopic') && (
                    <button type="button" className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs hover:border-accent/60" onClick={() => setShowAddPopup(false)}>
                      <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-border" /><span className="font-semibold text-text">New Section</span></span>
                      <span className="mt-0.5 block text-text-muted">Add a section with questions</span>
                    </button>
                  )}
                  <button type="button" className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-xs hover:border-accent/60" onClick={() => setShowAddPopup(false)}>
                    <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-success" /><span className="font-semibold text-text">New Question</span></span>
                    <span className="mt-0.5 block text-text-muted">Add a question node</span>
                  </button>
                </div>
              </div>
            )}

            {/* Component types */}
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Components</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {[
                  { type: 'chart', label: 'Chart', desc: 'Bar, line, pie, or area visualization', icon: BarChart3 },
                  { type: 'table', label: 'Table', desc: 'Structured data table with rows and columns', icon: Table2 },
                  { type: 'formula_metric', label: 'Formula Metric', desc: 'SHARE, RATE, RATIO, or GROWTH calculation', icon: FunctionSquare },
                  { type: 'narrative', label: 'Narrative', desc: 'Explanatory paragraph with insights', icon: FileText },
                  { type: 'key_finding', label: 'Key Finding', desc: 'Highlighted summary finding', icon: FileText },
                  { type: 'source_note', label: 'Source Note', desc: 'Data source attribution', icon: MessageSquare },
                ].map(({ type, label, desc, icon: Icon }) => (
                  <button
                    key={type}
                    type="button"
                    disabled={busy}
                    onClick={() => { onAddRecommendedComponent(selectedNode.nodeId, type, {}); setShowAddPopup(false); }}
                    className="rounded-lg border border-border bg-surface px-3 py-2.5 text-left text-xs transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:opacity-50"
                  >
                    <span className="flex items-center gap-2">
                      <Icon className="h-4 w-4 text-text-muted" />
                      <span className="font-semibold text-text">{label}</span>
                    </span>
                    <span className="mt-0.5 block text-[10px] text-text-muted">{desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Entity selection hint */}
            {selectedNode.requiredEntities.length > 0 && (
              <div className="mt-4 rounded-lg border border-border bg-surface px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Available entities from this {nodeTypeLabel(selectedNode.nodeType).toLowerCase()}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {selectedNode.requiredEntities.map((e, i) => (
                    <span key={i} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      {String(e.entityId || e.entityRef || '')}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default StructureCanvas;
