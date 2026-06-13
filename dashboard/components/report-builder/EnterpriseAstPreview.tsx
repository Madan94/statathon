'use client';

import { useState } from 'react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import type { EnterpriseDocumentAST } from '@/lib/enterpriseAstTypes';
import { buildEntityNameMap, resolveEntityLabel } from '@/lib/entityDisplayUtils';

const TABS = [
  'Metadata',
  'Layout',
  'Content',
  'Tables',
  'Figures',
  'Semantic',
  'Graphs',
  'Blueprint',
  'Retrieval',
  'Quality',
] as const;

type Tab = (typeof TABS)[number];

function countNodes(ast: Record<string, unknown>): number {
  const sem = ast.semanticAST as { hierarchy?: unknown[]; nodes?: unknown[] } | undefined;
  return Array.isArray(sem?.hierarchy) ? sem.hierarchy.length : Array.isArray(sem?.nodes) ? sem.nodes.length : 0;
}

export default function EnterpriseAstPreview({ ast }: { ast: Record<string, unknown> }) {
  const [tab, setTab] = useState<Tab>('Metadata');
  const meta = (ast.metadata as Record<string, unknown>) || {};
  const quality = (ast.quality_report as Record<string, unknown>) || {};
  const isV2 = meta.version === '2.0' || 'layoutAST' in ast;

  // Structured data
  const layoutAST = (ast.layoutAST as Record<string, unknown>) || {};
  const pages = Array.isArray(layoutAST.pages) ? (layoutAST.pages as Array<Record<string, unknown>>) : [];
  const contentAST = (ast.contentAST as Record<string, unknown>) || {};
  // v3 pipeline produces contentAST.paragraphs; fall back to .blocks for legacy
  const blocks = Array.isArray(contentAST.paragraphs)
    ? (contentAST.paragraphs as Array<Record<string, unknown>>)
    : Array.isArray(contentAST.blocks)
    ? (contentAST.blocks as Array<Record<string, unknown>>)
    : [];
  const tableAST = (ast.tableAST as Record<string, unknown>) || {};
  const tables = Array.isArray(tableAST.tables) ? (tableAST.tables as Array<Record<string, unknown>>) : [];
  const figureAST = (ast.figureAST as Record<string, unknown>) || {};
  const figures = Array.isArray(figureAST.figures) ? (figureAST.figures as Array<Record<string, unknown>>) : [];
  const semanticAST = (ast.semanticAST as Record<string, unknown>) || {};
  const hierarchy = Array.isArray(semanticAST.hierarchy) ? (semanticAST.hierarchy as Array<Record<string, unknown>>) : [];
  const entityGraph = (ast.entityGraph as Record<string, unknown>) || {};
  const entities = Array.isArray(entityGraph.entities) ? (entityGraph.entities as Array<Record<string, unknown>>) :
    // Fallback: read from semanticAST.entities or blueprint.entities
    Array.isArray((ast.semanticAST as Record<string, unknown>)?.entities) ? ((ast.semanticAST as Record<string, unknown>).entities as Array<Record<string, unknown>>) :
    Array.isArray((ast.blueprint as Record<string, unknown>)?.entities) ? ((ast.blueprint as Record<string, unknown>).entities as Array<Record<string, unknown>>) : [];
  const factGraph = (ast.factGraph as Record<string, unknown>) || {};
  const facts = Array.isArray(factGraph.facts) ? (factGraph.facts as Array<Record<string, unknown>>) : [];
  const retrievalAST = (ast.retrievalAST as Record<string, unknown>) || {};
  const chunks = Array.isArray(retrievalAST.chunks) ? (retrievalAST.chunks as Array<Record<string, unknown>>) : [];

  if (!isV2) {
    return (
      <Alert variant="warning">
        Template is legacy v1 format. Re-extract PDF or re-import to upgrade to enterprise AST v2.0.
      </Alert>
    );
  }

  const kindColors: Record<string, string> = {
    heading: 'bg-purple-100 text-purple-700',
    narrative: 'bg-blue-100 text-blue-700',
    table: 'bg-green-100 text-green-700',
    figure: 'bg-orange-100 text-orange-700',
    chart: 'bg-amber-100 text-amber-700',
    metric: 'bg-pink-100 text-pink-700',
  };

  const entityTypeColors: Record<string, string> = {
    org: 'bg-indigo-100 text-indigo-700',
    metric: 'bg-emerald-100 text-emerald-700',
    time: 'bg-amber-100 text-amber-700',
    demographic: 'bg-cyan-100 text-cyan-700',
    location: 'bg-rose-100 text-rose-700',
    resource: 'bg-teal-100 text-teal-700',
  };

  const renderBody = () => {
    switch (tab) {
      case 'Metadata':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
              {Object.entries(meta).slice(0, 12).map(([key, val]) => (
                <div key={key} className="rounded border border-border bg-surface p-2">
                  <p className="text-[10px] text-text-muted uppercase tracking-wider">{key}</p>
                  <p className="text-xs text-text font-mono truncate">{typeof val === 'object' ? JSON.stringify(val) : String(val ?? '—')}</p>
                </div>
              ))}
            </div>
            <details className="rounded border border-border">
              <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw JSON</summary>
              <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(meta, null, 2)}</pre>
            </details>
          </div>
        );

      case 'Layout':
        return (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{pages.length} pages with layout regions</p>
            {pages.slice(0, 8).map((page, idx) => {
              const regions = Array.isArray(page.regions) ? (page.regions as Array<Record<string, unknown>>) : [];
              return (
                <div key={`lp-${page.page_index ?? idx}`} className="rounded-lg border border-border bg-surface p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant="muted">Page {Number(page.page_index ?? idx) + 1}</Badge>
                    <span className="text-[10px] text-text-muted">{regions.length} regions</span>
                  </div>
                  {regions.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {regions.slice(0, 10).map((r, ri) => (
                        <span key={ri} className={`text-[10px] rounded px-1.5 py-0.5 ${kindColors[String(r.type || r.label)] || 'bg-gray-100 text-gray-600'}`}>
                          {String(r.type || r.label || 'region')}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            <details className="rounded border border-border">
              <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw JSON</summary>
              <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(ast.layoutAST, null, 2)}</pre>
            </details>
          </div>
        );

      case 'Content':
        return (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{blocks.length} content paragraphs</p>
            {blocks.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-xs">
                  <thead className="bg-surface">
                    <tr className="border-b border-border">
                      <th className="py-2 px-3 text-left text-text-muted font-medium">ID</th>
                      <th className="py-2 px-3 text-left text-text-muted font-medium">Type</th>
                      <th className="py-2 px-3 text-left text-text-muted font-medium">Page</th>
                      <th className="py-2 px-3 text-left text-text-muted font-medium">Text</th>
                    </tr>
                  </thead>
                  <tbody>
                    {blocks.slice(0, 20).map((b, idx) => (
                      <tr key={`cb-${b.blockId || idx}`} className="border-b border-border/30">
                        <td className="py-1.5 px-3 font-mono text-[10px] text-text-muted">{String(b.blockId || idx)}</td>
                        <td className="py-1.5 px-3">
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${kindColors[String(b.type || b.kind)] || 'bg-gray-100 text-gray-600'}`}>
                            {String(b.type || b.kind || '—')}
                          </span>
                        </td>
                        <td className="py-1.5 px-3 text-text-muted">{String(b.page ?? '—')}</td>
                        <td className="py-1.5 px-3 text-text max-w-[300px] truncate">{String(b.text || b.content || '—').slice(0, 80)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <details className="rounded border border-border">
              <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw JSON</summary>
              <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(ast.contentAST, null, 2)}</pre>
            </details>
          </div>
        );

      case 'Tables':
        return (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{tables.length} tables extracted</p>
            {tables.slice(0, 8).map((t, idx) => (
              <div key={`tbl-${t.tableId || idx}`} className="rounded-lg border border-border bg-surface p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="success">table</Badge>
                  <span className="text-sm font-medium text-text">{String(t.title || `Table ${idx + 1}`)}</span>
                  {Boolean(t.source) && <Badge variant="muted">{String(t.source)}</Badge>}
                </div>
                {/* dimensions, measures, breakdowns — v3 pipeline fields */}
                {Array.isArray(t.dimensions) && (t.dimensions as unknown[]).length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    <span className="text-[10px] text-blue-500 font-medium mr-1">dims:</span>
                    {(t.dimensions as unknown[]).slice(0, 8).map((col, ci) => (
                      <span key={ci} className="text-[10px] bg-blue-50 text-blue-700 rounded px-1.5 py-0.5 border border-blue-200">
                        {typeof col === 'string' ? col : typeof col === 'object' && col !== null ? String((col as Record<string, unknown>).header || (col as Record<string, unknown>).columnId || JSON.stringify(col)) : String(col)}
                      </span>
                    ))}
                  </div>
                )}
                {Array.isArray(t.measures) && (t.measures as unknown[]).length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    <span className="text-[10px] text-green-500 font-medium mr-1">measures:</span>
                    {(t.measures as unknown[]).slice(0, 8).map((col, ci) => (
                      <span key={ci} className="text-[10px] bg-green-50 text-green-700 rounded px-1.5 py-0.5 border border-green-200">
                        {typeof col === 'string' ? col : typeof col === 'object' && col !== null ? String((col as Record<string, unknown>).header || (col as Record<string, unknown>).measure || JSON.stringify(col)) : String(col)}
                      </span>
                    ))}
                  </div>
                )}
                {Array.isArray(t.breakdowns) && (t.breakdowns as unknown[]).length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    <span className="text-[10px] text-purple-500 font-medium mr-1">breakdowns:</span>
                    {(t.breakdowns as unknown[]).slice(0, 6).map((col, ci) => (
                      <span key={ci} className="text-[10px] bg-purple-50 text-purple-700 rounded px-1.5 py-0.5 border border-purple-200">
                        {typeof col === 'string' ? col : typeof col === 'object' && col !== null ? String((col as Record<string, unknown>).measure || (col as Record<string, unknown>).header || JSON.stringify(col)) : String(col)}
                      </span>
                    ))}
                  </div>
                )}
                {/* fallback: legacy columns array */}
                {!Array.isArray(t.dimensions) && Array.isArray(t.columns) && (t.columns as unknown[]).length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2">
                    {(t.columns as unknown[]).slice(0, 12).map((col, ci) => (
                      <span key={ci} className="text-[10px] bg-green-50 text-green-700 rounded px-1.5 py-0.5 border border-green-200">
                        {typeof col === 'string' ? col : typeof col === 'object' && col !== null ? String((col as Record<string, unknown>).header || (col as Record<string, unknown>).columnId || JSON.stringify(col)) : String(col)}
                      </span>
                    ))}
                  </div>
                )}
                {Array.isArray(t.sampleRows) && (t.sampleRows as unknown[]).length > 0 && (
                  <pre className="text-[10px] text-text-muted bg-gray-50 rounded p-2 overflow-auto max-h-24 border border-border/50">
                    {JSON.stringify(t.sampleRows, null, 2)}
                  </pre>
                )}
                <p className="text-[10px] text-text-muted mt-1">Rows: {String(t.rowCount || '—')} · Page: {String(t.pageRef || t.page || '—')}</p>
              </div>
            ))}
            <details className="rounded border border-border">
              <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw JSON</summary>
              <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(ast.tableAST, null, 2)}</pre>
            </details>
          </div>
        );

      case 'Figures':
        return (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{figures.length} figures/charts detected</p>
            {figures.slice(0, 8).map((f, idx) => (
              <div key={`fig-${f.figureId || idx}`} className="rounded-lg border border-border bg-surface p-3">
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="warning">{String(f.type || 'figure')}</Badge>
                  <span className="text-xs font-medium text-text">{String(f.title || f.caption || `Figure ${idx + 1}`)}</span>
                </div>
                <p className="text-[10px] text-text-muted">Page: {String(f.page || '—')}</p>
                {Boolean(f.description) && <p className="text-[10px] text-text-muted mt-1">{String(f.description)}</p>}
              </div>
            ))}
            {figures.length === 0 && (
              <details className="rounded border border-border">
                <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw JSON</summary>
                <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(ast.figureAST, null, 2)}</pre>
              </details>
            )}
          </div>
        );

      case 'Semantic':
        return (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{hierarchy.length} hierarchy nodes</p>
            {hierarchy.length > 0 && (
              <div className="rounded-lg border border-border bg-surface p-4 space-y-1">
                {hierarchy.slice(0, 30).map((node, idx) => {
                  const level = Number(node.level || node.depth || 1);
                  return (
                    <div key={`sn-${node.nodeId || idx}`} className="flex items-center gap-2" style={{ paddingLeft: `${(level - 1) * 16}px` }}>
                      <span className={`w-2 h-2 rounded-full shrink-0 ${level === 1 ? 'bg-primary' : level === 2 ? 'bg-blue-400' : 'bg-gray-300'}`} />
                      <span className="text-xs text-text">{String(node.title || node.name || '—')}</span>
                      {Boolean(node.pageSpan) && <span className="text-[10px] text-text-muted">p.{JSON.stringify(node.pageSpan)}</span>}
                    </div>
                  );
                })}
              </div>
            )}
            <details className="rounded border border-border">
              <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw JSON</summary>
              <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(ast.semanticAST, null, 2)}</pre>
            </details>
          </div>
        );

      case 'Graphs':
        return (
          <div className="space-y-3">
            {/* Entities */}
            {entities.length > 0 && (
              <div className="rounded-lg border border-border bg-surface p-3">
                <h4 className="text-xs font-semibold text-text mb-2">Entities ({entities.length})</h4>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {Object.entries(
                    entities.reduce<Record<string, number>>((acc, e) => {
                      const t = String(e.type || e.entityType || 'unknown');
                      acc[t] = (acc[t] || 0) + 1;
                      return acc;
                    }, {})
                  ).map(([type, count]) => (
                    <span key={type} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${entityTypeColors[type] || 'bg-gray-100 text-gray-600'}`}>
                      {type}: {count}
                    </span>
                  ))}
                </div>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {entities.slice(0, 15).map((e, idx) => (
                    <div key={`e-${e.entityId || idx}`} className="flex items-center gap-2 text-[10px]">
                      <span className={`rounded-full px-1.5 py-0.5 ${entityTypeColors[String(e.type || e.entityType)] || 'bg-gray-100 text-gray-600'}`}>{String(e.type || e.entityType || '—')}</span>
                      <span className="text-text font-medium">{String(e.name || e.canonicalName || e.entityId || '—')}</span>
                      {Boolean(e.entityType) && (
                        <span className={`rounded-full px-1.5 py-0.5 text-[9px] ${
                          e.entityType === 'dimension' ? 'bg-blue-100 text-blue-700' :
                          e.entityType === 'measure' ? 'bg-green-100 text-green-700' :
                          e.entityType === 'filter' ? 'bg-orange-100 text-orange-700' :
                          'bg-gray-100 text-gray-500'
                        }`}>{String(e.entityType)}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {/* Facts */}
            {facts.length > 0 && (
              <div className="rounded-lg border border-border bg-surface p-3">
                <h4 className="text-xs font-semibold text-text mb-2">Facts ({facts.length})</h4>
                <ul className="space-y-1 max-h-40 overflow-y-auto">
                  {facts.slice(0, 10).map((f, idx) => (
                    <li key={`f-${f.factId || idx}`} className="text-[10px] text-text flex gap-1">
                      <span className="text-text-muted shrink-0">{idx + 1}.</span>
                      <span>{String(f.statement || f.text || '—')}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <details className="rounded border border-border">
              <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw Graphs JSON</summary>
              <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">
                {JSON.stringify({ entityGraph: ast.entityGraph, factGraph: ast.factGraph, relationshipGraph: ast.relationshipGraph }, null, 2)}
              </pre>
            </details>
          </div>
        );

      case 'Blueprint': {
        const enterpriseAst = (ast.enterprise_ast as Record<string, unknown>) || ast || {};
        const blueprint = (enterpriseAst.blueprint as Record<string, unknown>) || (ast.blueprint as Record<string, unknown>) || {};
        const bpTopics = Array.isArray(blueprint.topics) ? (blueprint.topics as Array<Record<string, unknown>>) : [];
        const bpEntities = Array.isArray(blueprint.entities) ? (blueprint.entities as Array<Record<string, unknown>>) : [];
        const bpTables = Array.isArray(blueprint.tableStructures || blueprint.tableTemplates) ? (((blueprint.tableStructures || blueprint.tableTemplates) as Array<Record<string, unknown>>)) : [];
        const entityNameById = buildEntityNameMap(bpEntities, entities);
        return (
          <div className="space-y-4">
            {bpTopics.length === 0 && bpEntities.length === 0 ? (
              <p className="text-xs text-text-muted italic">Blueprint not yet generated. Re-run extraction.</p>
            ) : (
              <>
                <p className="text-xs text-text-muted">
                  {bpTopics.length} topics · {bpEntities.length} entities · {bpTables.length} table structures
                </p>
                {/* Topics */}
                {bpTopics.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-text">Topics</h4>
                    {bpTopics.map((topic, ti) => {
                      const questions = Array.isArray(topic.questions) ? (topic.questions as Array<Record<string, unknown>>) : [];
                      return (
                        <details key={`bp-topic-${ti}`} className="rounded-lg border border-border bg-surface">
                          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-text flex items-center gap-2">
                            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary text-white text-[10px] font-bold shrink-0">
                              {ti + 1}
                            </span>
                            {String(topic.title || topic.topicId || `Topic ${ti + 1}`)}
                            <span className="ml-auto text-[10px] text-text-muted">{questions.length} questions</span>
                          </summary>
                          <div className="px-3 pb-3 space-y-2">
                            {questions.slice(0, 8).map((q, qi) => (
                              <div key={`bp-q-${qi}`} className="rounded border border-border/50 bg-white p-2">
                                <div className="flex items-start gap-2 mb-1">
                                  <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium ${
                                    q.questionType === 'comparison' ? 'bg-blue-100 text-blue-700' :
                                    q.questionType === 'trend' ? 'bg-green-100 text-green-700' :
                                    q.questionType === 'ranking' ? 'bg-amber-100 text-amber-700' :
                                    q.questionType === 'distribution' ? 'bg-purple-100 text-purple-700' :
                                    'bg-gray-100 text-gray-600'
                                  }`}>{String(q.questionType || 'describe')}</span>
                                  <span className="text-xs text-text">{String(q.intent || q.questionId || '—')}</span>
                                </div>
                                {Array.isArray(q.requiredEntities) && (q.requiredEntities as Array<Record<string,unknown>>).length > 0 && (
                                  <div className="flex flex-wrap gap-1 mt-1">
                                    {(q.requiredEntities as Array<Record<string, unknown>>).slice(0, 5).map((re, ri) => (
                                      <span key={ri} className="text-[9px] bg-indigo-50 text-indigo-700 rounded px-1.5 py-0.5">
                                        {resolveEntityLabel(re.entityRef || re.entityId, entityNameById)}{' '}
                                        <span className="opacity-60">({String(re.role || '?')})</span>
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            ))}
                            {questions.length > 8 && (
                              <p className="text-[10px] text-text-muted pl-1">…and {questions.length - 8} more questions</p>
                            )}
                          </div>
                        </details>
                      );
                    })}
                  </div>
                )}
                {/* Blueprint Table Structures */}
                {bpTables.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-text mb-2">Table Structures ({bpTables.length})</h4>
                    {bpTables.slice(0, 6).map((t, ti) => (
                      <div key={ti} className="rounded border border-border bg-surface p-2 mb-2">
                        <p className="text-xs font-medium text-text mb-1">{String(t.title || `Table ${ti + 1}`)}</p>
                        {Array.isArray(t.dimensions) && (
                          <div className="flex flex-wrap gap-1">
                            {(t.dimensions as unknown[]).map((d, di) => (
                              <span key={di} className="text-[9px] bg-blue-50 text-blue-700 rounded px-1.5 py-0.5">
                                {typeof d === 'string' ? d : typeof d === 'object' && d !== null ? String((d as Record<string, unknown>).header || (d as Record<string, unknown>).columnId || JSON.stringify(d)) : String(d)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <details className="rounded border border-border">
                  <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw Blueprint JSON</summary>
                  <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(blueprint, null, 2)}</pre>
                </details>
              </>
            )}
          </div>
        );
      }

      case 'Retrieval':
        return (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{chunks.length} retrieval chunks</p>
            {chunks.slice(0, 10).map((c, idx) => (
              <div key={`rc-${c.chunkId || idx}`} className="rounded-lg border border-border bg-surface p-3">
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="muted">chunk {idx + 1}</Badge>
                  {Boolean(c.page) && <span className="text-[10px] text-text-muted">p.{String(c.page)}</span>}
                </div>
                <p className="text-[10px] text-text line-clamp-3">{String(c.text || c.content || '—').slice(0, 200)}</p>
              </div>
            ))}
            {chunks.length === 0 && (
              <details className="rounded border border-border">
                <summary className="cursor-pointer px-3 py-2 text-xs text-text-muted">Raw JSON</summary>
                <pre className="px-3 pb-3 text-[10px] overflow-auto max-h-48">{JSON.stringify(ast.retrievalAST, null, 2)}</pre>
              </details>
            )}
          </div>
        );

      case 'Quality':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
              <div className="rounded border border-border bg-surface p-3">
                <p className="text-[10px] text-text-muted uppercase">Score</p>
                <p className="text-lg font-bold text-text">{String(quality.score ?? '—')}</p>
              </div>
              <div className="rounded border border-border bg-surface p-3">
                <p className="text-[10px] text-text-muted uppercase">Passed</p>
                <p className={`text-lg font-bold ${quality.passed ? 'text-green-600' : 'text-red-500'}`}>{quality.passed ? '✓ Yes' : '✗ No'}</p>
              </div>
              <div className="rounded border border-border bg-surface p-3">
                <p className="text-[10px] text-text-muted uppercase">Issues</p>
                <p className="text-lg font-bold">{Array.isArray(quality.errors) ? quality.errors.length : 0}</p>
              </div>
            </div>
            {Array.isArray(quality.errors) && quality.errors.length > 0 && (
              <Alert variant="error">{(quality.errors as string[]).join('; ')}</Alert>
            )}
            {Array.isArray(quality.warnings) && (quality.warnings as string[]).length > 0 && (
              <div className="rounded border border-border bg-surface p-3">
                <h4 className="text-xs font-semibold text-text mb-2">Warnings</h4>
                <ul className="space-y-1">
                  {(quality.warnings as string[]).slice(0, 8).map((w, i) => (
                    <li key={i} className="text-[10px] text-text-muted">⚠ {w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Document ID</p>
          <p className="text-sm font-mono truncate">{String(meta.documentId || '—')}</p>
        </Card>
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Pages</p>
          <p className="text-sm font-medium">{String(meta.page_count ?? ast.page_count ?? 0)}</p>
        </Card>
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Semantic nodes</p>
          <p className="text-sm font-medium">{countNodes(ast)}</p>
        </Card>
        <Card className="p-3">
          <p className="text-[11px] text-text-muted">Checksum</p>
          <p className="text-xs font-mono truncate">{String(meta.checksum || '—').slice(0, 16)}…</p>
        </Card>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-border pb-2">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-2 py-1 text-xs rounded ${
              tab === t ? 'bg-primary text-white' : 'text-text-muted hover:bg-border/40'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {renderBody()}
    </div>
  );
}
