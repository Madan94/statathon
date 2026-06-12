'use client';

import { useMemo, useState } from 'react';
import {
  BarChart3,
  BookOpen,
  Boxes,
  CircleHelp,
  FileStack,
  GitBranch,
  LayoutDashboard,
  Layers,
  Table2,
  Timer,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import {
  TypeFilterDropdown,
  collectTypeOptions,
  useTypeFilter,
} from '@/components/report-builder/TypeFilterDropdown';
import { resolveEntityLabel } from '@/lib/entityDisplayUtils';
import {
  PASS_LABELS,
  type AstTabId,
  type ParsedTemplateAst,
  formatColumnLabel,
  parseTemplateAst,
} from './parseTemplateAst';

const BLOCK_KIND_COLORS: Record<string, string> = {
  heading: 'bg-purple-100 text-purple-800',
  narrative: 'bg-blue-100 text-blue-800',
  table: 'bg-emerald-100 text-emerald-800',
  chart: 'bg-amber-100 text-amber-800',
  metric: 'bg-rose-100 text-rose-800',
};

const ENTITY_TYPE_COLORS: Record<string, string> = {
  dimension: 'bg-blue-100 text-blue-800',
  measure: 'bg-emerald-100 text-emerald-800',
  filter: 'bg-orange-100 text-orange-800',
  time: 'bg-amber-100 text-amber-800',
  metadata: 'bg-slate-100 text-slate-700',
  org: 'bg-indigo-100 text-indigo-800',
  metric: 'bg-emerald-100 text-emerald-800',
  demographic: 'bg-cyan-100 text-cyan-800',
  location: 'bg-rose-100 text-rose-800',
  resource: 'bg-teal-100 text-teal-800',
};

const QUESTION_TYPE_COLORS: Record<string, string> = {
  comparison: 'bg-blue-100 text-blue-800',
  trend: 'bg-emerald-100 text-emerald-800',
  ranking: 'bg-violet-100 text-violet-800',
};

interface TabDef {
  id: AstTabId;
  label: string;
  headline: string;
  description: string;
  icon: LucideIcon;
  count: number;
}

function SectionIntro({ headline, description }: { headline: string; description: string }) {
  return (
    <div className="mb-5 rounded-xl border border-border/70 bg-gradient-to-br from-surface to-surface-card px-4 py-3.5 sm:px-5">
      <h3 className="text-sm font-semibold text-text">{headline}</h3>
      <p className="mt-1 text-sm leading-relaxed text-text-muted">{description}</p>
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface/40 px-6 py-10 text-center">
      <p className="text-sm font-medium text-text">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-text-muted">{body}</p>
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-card p-4 shadow-sm">
      <p className="text-2xl font-bold tabular-nums text-text">{value}</p>
      <p className="mt-1 text-sm font-medium text-text">{label}</p>
      <p className="mt-0.5 text-xs leading-snug text-text-muted">{hint}</p>
    </div>
  );
}

function chartTypeColor(type: string): string {
  if (type.includes('bar')) return 'bg-orange-100 text-orange-800';
  if (type.includes('line')) return 'bg-blue-100 text-blue-800';
  if (type.includes('pie')) return 'bg-pink-100 text-pink-800';
  if (type.includes('scatter')) return 'bg-violet-100 text-violet-800';
  if (type.includes('area')) return 'bg-teal-100 text-teal-800';
  if (type.includes('map')) return 'bg-emerald-100 text-emerald-800';
  return 'bg-amber-100 text-amber-800';
}

export default function TemplateAstExplorer({ ast }: { ast: Record<string, unknown> }) {
  const data = useMemo(() => parseTemplateAst(ast), [ast]);
  const [activeTab, setActiveTab] = useState<AstTabId>('overview');

  const tabs: TabDef[] = [
    {
      id: 'overview',
      label: 'Summary',
      headline: 'Extraction summary',
      description:
        'A quick read of what the pipeline found in your MoSPI PDF — page count, content pieces, and document outline.',
      icon: LayoutDashboard,
      count: data.pageCount,
    },
    {
      id: 'blocks',
      label: 'Layout pieces',
      headline: 'Page layout pieces',
      description:
        'Every heading, paragraph, table slot, and chart region detected on the PDF. These become the building blocks of generated reports.',
      icon: Layers,
      count: data.blocks.length,
    },
    {
      id: 'entities',
      label: 'Data fields',
      headline: 'Data fields in this template',
      description:
        'Named measures and dimensions the report expects. During binding, you map your dataset columns to these fields.',
      icon: Boxes,
      count: data.entities.length,
    },
    {
      id: 'tables',
      label: 'Tables',
      headline: 'Tables found in the PDF',
      description:
        'Tabular regions with column headers and sample rows extracted from the source document.',
      icon: Table2,
      count: data.tables.length,
    },
    {
      id: 'charts',
      label: 'Charts & figures',
      headline: 'Charts and figures',
      description:
        'Visual elements detected on the PDF — bar charts, line charts, maps, and other figures with their page location.',
      icon: BarChart3,
      count: data.allFigures.length,
    },
    {
      id: 'blueprint',
      label: 'Report blueprint',
      headline: 'Report blueprint',
      description:
        'How the final report will be organized: topics, analytical questions, and the data fields each question needs.',
      icon: BookOpen,
      count: data.bpTopics.length,
    },
    {
      id: 'questions',
      label: 'Questions',
      headline: 'Extracted questions',
      description:
        'Plain-language analytical questions inferred from the PDF. These drive narrative and chart generation.',
      icon: CircleHelp,
      count: data.questionStrings.length,
    },
    {
      id: 'trace',
      label: 'Extraction log',
      headline: 'Extraction pipeline log',
      description:
        'Step-by-step record of how the PDF was processed, how long each step took, and quality checks performed.',
      icon: GitBranch,
      count: Object.keys(data.passes).length,
    },
  ];

  const active = tabs.find((t) => t.id === activeTab) ?? tabs[0];

  const blockTypeOptions = useMemo(
    () => collectTypeOptions(data.blocks, (b) => String(b.kind || b.type || 'unknown')),
    [data.blocks]
  );
  const entityTypeOptions = useMemo(
    () => collectTypeOptions(data.entities, (e) => String(e.type || e.entityType || 'unknown')),
    [data.entities]
  );
  const [selectedBlockTypes, setSelectedBlockTypes] = useTypeFilter(blockTypeOptions.types);
  const [selectedEntityTypes, setSelectedEntityTypes] = useTypeFilter(entityTypeOptions.types);

  const filteredBlocks = useMemo(
    () =>
      data.blocks.filter((b) =>
        selectedBlockTypes.has(String(b.kind || b.type || 'unknown'))
      ),
    [data.blocks, selectedBlockTypes]
  );
  const filteredEntities = useMemo(
    () =>
      data.entities.filter((e) =>
        selectedEntityTypes.has(String(e.type || e.entityType || 'unknown'))
      ),
    [data.entities, selectedEntityTypes]
  );

  return (
    <div className="space-y-6">
      {/* At-a-glance metrics — always visible */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard
          label="Pages scanned"
          value={data.pageCount}
          hint="Total PDF pages processed"
        />
        <MetricCard
          label="Layout pieces"
          value={data.blocks.length}
          hint="Headings, text, tables, charts"
        />
        <MetricCard
          label="Data fields"
          value={data.entities.length}
          hint="Fields to bind to your dataset"
        />
        <MetricCard
          label="Report topics"
          value={data.bpTopics.length}
          hint="Sections in the blueprint"
        />
        <MetricCard
          label="Processing time"
          value={data.totalElapsed ? `${data.totalElapsed}s` : '—'}
          hint={`Method: ${data.extractionMethod}`}
        />
      </div>

      {!data.hasContent && (
        <Alert variant="error">
          No extraction data was found in this template. Upload the PDF again from the AST
          Generator page while backend services are running.
        </Alert>
      )}

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        {/* Sidebar navigation */}
        <nav
          className="lg:w-64 lg:shrink-0 lg:sticky lg:top-4"
          aria-label="Template sections"
        >
          <p className="mb-2 hidden text-xs font-semibold uppercase tracking-wide text-text-muted lg:block">
            Explore this template
          </p>
          <div className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex min-w-[140px] shrink-0 flex-col rounded-xl border px-3 py-2.5 text-left transition-colors lg:min-w-0 lg:w-full ${
                    isActive
                      ? 'border-primary/40 bg-primary/5 shadow-sm'
                      : 'border-border bg-surface-card hover:border-primary/25 hover:bg-surface'
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <Icon
                      className={`h-4 w-4 shrink-0 ${isActive ? 'text-primary' : 'text-text-muted'}`}
                      aria-hidden
                    />
                    <span className={`text-sm font-medium ${isActive ? 'text-primary' : 'text-text'}`}>
                      {tab.label}
                    </span>
                    <span
                      className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${
                        isActive ? 'bg-primary/15 text-primary' : 'bg-border/60 text-text-muted'
                      }`}
                    >
                      {tab.count}
                    </span>
                  </span>
                  <span className="mt-1 hidden text-[11px] leading-snug text-text-muted lg:block">
                    {tab.description.split('.')[0]}.
                  </span>
                </button>
              );
            })}
          </div>
        </nav>

        {/* Main panel */}
        <div className="min-w-0 flex-1 rounded-2xl border border-border bg-surface-card p-5 shadow-sm sm:p-6">
          <SectionIntro headline={active.headline} description={active.description} />

          {activeTab === 'overview' && (
            <OverviewPanel data={data} />
          )}
          {activeTab === 'blocks' && (
            <BlocksPanel
              data={data}
              filteredBlocks={filteredBlocks}
              blockTypeOptions={blockTypeOptions}
              selectedBlockTypes={selectedBlockTypes}
              setSelectedBlockTypes={setSelectedBlockTypes}
            />
          )}
          {activeTab === 'entities' && (
            <EntitiesPanel
              filteredEntities={filteredEntities}
              entityTypeOptions={entityTypeOptions}
              selectedEntityTypes={selectedEntityTypes}
              setSelectedEntityTypes={setSelectedEntityTypes}
              total={data.entities.length}
            />
          )}
          {activeTab === 'tables' && <TablesPanel tables={data.tables} />}
          {activeTab === 'charts' && (
            <ChartsPanel
              allFigures={data.allFigures}
              chartFigures={data.chartFigures}
              pureFigures={data.pureFigures}
            />
          )}
          {activeTab === 'blueprint' && (
            <BlueprintPanel
              topics={data.bpTopics}
              tableTemplates={data.bpTableTemplates}
              entityCount={data.bpEntities.length}
              entityNameById={data.entityNameById}
            />
          )}
          {activeTab === 'questions' && (
            <QuestionsPanel questions={data.questionStrings} />
          )}
          {activeTab === 'trace' && (
            <TracePanel passes={data.passes} pipelineTrace={data.pipelineTrace} />
          )}
        </div>
      </div>
    </div>
  );
}

function OverviewPanel({ data }: { data: ParsedTemplateAst }) {
  const flowSteps = [
    { label: 'PDF pages', value: data.pageCount, icon: FileStack },
    { label: 'Layout pieces', value: data.blocks.length, icon: Layers },
    { label: 'Data fields', value: data.entities.length, icon: Boxes },
    { label: 'Blueprint topics', value: data.bpTopics.length, icon: BookOpen },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="success">Extraction: {data.extractionMethod}</Badge>
        {data.totalElapsed != null && (
          <Badge variant="muted">
            <Timer className="mr-1 inline h-3 w-3" aria-hidden />
            Completed in {String(data.totalElapsed)}s
          </Badge>
        )}
        <span className="text-xs text-text-muted">
          Document reference: <span className="font-mono">{data.docId}</span>
        </span>
      </div>

      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
          From PDF to blueprint
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {flowSteps.map((step, i) => {
            const Icon = step.icon;
            return (
              <div key={step.label} className="flex items-center gap-2">
                <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                  <Icon className="h-4 w-4 text-primary" aria-hidden />
                  <div>
                    <p className="text-sm font-bold tabular-nums text-text">{step.value}</p>
                    <p className="text-[11px] text-text-muted">{step.label}</p>
                  </div>
                </div>
                {i < flowSteps.length - 1 && (
                  <span className="hidden text-text-muted sm:inline" aria-hidden>
                    →
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {data.hierarchy.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-semibold text-text">Document outline</h4>
          <p className="mb-3 text-xs text-text-muted">
            Section headings detected in the PDF, indented by depth.
          </p>
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="space-y-1.5">
              {data.hierarchy.slice(0, 24).map((node, idx) => {
                const level = Number(node.level || node.depth || 1);
                return (
                  <div
                    key={`h-${node.nodeId || idx}`}
                    className="flex items-center gap-2 text-sm"
                    style={{ paddingLeft: `${(level - 1) * 14}px` }}
                  >
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${
                        level === 1 ? 'bg-primary' : level === 2 ? 'bg-blue-400' : 'bg-slate-300'
                      }`}
                      aria-hidden
                    />
                    <span className="text-text">{String(node.title || node.name || 'Untitled section')}</span>
                    {Boolean(node.pageSpan) && (
                      <span className="text-xs text-text-muted">
                        pages {JSON.stringify(node.pageSpan)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {data.facts.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-semibold text-text">Key statements from the PDF</h4>
          <p className="mb-3 text-xs text-text-muted">
            Factual sentences extracted with confidence scores.
          </p>
          <ul className="space-y-2">
            {data.facts.slice(0, 8).map((f, idx) => (
              <li
                key={`f-${f.factId || idx}`}
                className="flex gap-3 rounded-lg border border-border/60 bg-surface px-3 py-2.5 text-sm"
              >
                <span className="shrink-0 font-mono text-xs text-text-muted">{idx + 1}</span>
                <span className="flex-1 text-text">{String(f.statement || f.text || '—')}</span>
                {Boolean(f.confidence) && (
                  <Badge variant="muted" className="shrink-0 text-[10px]">
                    {Math.round(Number(f.confidence) * 100)}% confident
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function BlocksPanel({
  data,
  filteredBlocks,
  blockTypeOptions,
  selectedBlockTypes,
  setSelectedBlockTypes,
}: {
  data: ParsedTemplateAst;
  filteredBlocks: Array<Record<string, unknown>>;
  blockTypeOptions: ReturnType<typeof collectTypeOptions>;
  selectedBlockTypes: Set<string>;
  setSelectedBlockTypes: (s: Set<string>) => void;
}) {
  if (data.blocks.length === 0) {
    return (
      <EmptyState
        title="No layout pieces found"
        body="The pipeline did not detect headings, paragraphs, or other content regions in this PDF."
      />
    );
  }

  return (
    <div className="space-y-4">
      <TypeFilterDropdown
        label="Show layout types"
        types={blockTypeOptions.types}
        selected={selectedBlockTypes}
        onChange={setSelectedBlockTypes}
        counts={blockTypeOptions.counts}
        typeColors={BLOCK_KIND_COLORS}
      />
      <p className="text-xs text-text-muted">
        Showing {filteredBlocks.length} of {data.blocks.length} pieces
      </p>
      {filteredBlocks.length === 0 ? (
        <EmptyState
          title="No pieces match your filter"
          body="Select one or more layout types above to see matching content."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left">
              <tr className="border-b border-border">
                <th className="px-4 py-3 font-medium text-text-muted">Piece ID</th>
                <th className="px-4 py-3 font-medium text-text-muted">Type</th>
                <th className="px-4 py-3 font-medium text-text-muted">Section</th>
                <th className="px-4 py-3 font-medium text-text-muted">Title / label</th>
              </tr>
            </thead>
            <tbody>
              {filteredBlocks.map((b, idx) => (
                <tr key={`${b.block_id ?? idx}`} className="border-b border-border/40 hover:bg-surface/60">
                  <td className="px-4 py-2.5 font-mono text-xs text-text-muted">
                    {String(b.block_id || '—')}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        BLOCK_KIND_COLORS[String(b.kind)] || 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {String(b.kind || 'unknown')}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-text-muted">{String(b.section || '—')}</td>
                  <td className="max-w-xs truncate px-4 py-2.5 text-text">
                    {String(b.title || '—')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EntitiesPanel({
  filteredEntities,
  entityTypeOptions,
  selectedEntityTypes,
  setSelectedEntityTypes,
  total,
}: {
  filteredEntities: Array<Record<string, unknown>>;
  entityTypeOptions: ReturnType<typeof collectTypeOptions>;
  selectedEntityTypes: Set<string>;
  setSelectedEntityTypes: (s: Set<string>) => void;
  total: number;
}) {
  if (total === 0) {
    return (
      <EmptyState
        title="No data fields found"
        body="Entities are the named measures and dimensions your dataset will map to during binding."
      />
    );
  }

  return (
    <div className="space-y-4">
      <TypeFilterDropdown
        label="Show field roles"
        types={entityTypeOptions.types}
        selected={selectedEntityTypes}
        onChange={setSelectedEntityTypes}
        counts={entityTypeOptions.counts}
        typeColors={ENTITY_TYPE_COLORS}
      />
      <p className="text-xs text-text-muted">
        Showing {filteredEntities.length} of {total} fields
      </p>
      {filteredEntities.length === 0 ? (
        <EmptyState
          title="No fields match your filter"
          body="Select one or more field roles above to see matching entries."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left">
              <tr className="border-b border-border">
                <th className="px-4 py-3 font-medium text-text-muted">Internal ID</th>
                <th className="px-4 py-3 font-medium text-text-muted">Role</th>
                <th className="px-4 py-3 font-medium text-text-muted">Field name</th>
                <th className="px-4 py-3 font-medium text-text-muted">Where it appears</th>
              </tr>
            </thead>
            <tbody>
              {filteredEntities.map((e, idx) => (
                <tr key={`${e.entityId || idx}`} className="border-b border-border/40 hover:bg-surface/60">
                  <td className="px-4 py-2.5 font-mono text-xs text-text-muted">
                    {String(e.entityId || '—')}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        ENTITY_TYPE_COLORS[String(e.type || e.entityType)] ||
                        'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {String(e.type || e.entityType || 'unknown')}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-medium text-text">{String(e.name || '—')}</td>
                  <td className="max-w-xs truncate px-4 py-2.5 text-text-muted">
                    {String(e.context || '—')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TablesPanel({ tables }: { tables: Array<Record<string, unknown>> }) {
  if (tables.length === 0) {
    return (
      <EmptyState
        title="No tables found"
        body="Tabular regions with column headers were not detected in this PDF."
      />
    );
  }

  return (
    <div className="space-y-4">
      {tables.slice(0, 12).map((t, idx) => (
        <article
          key={`${t.tableId || idx}`}
          className="rounded-xl border border-border bg-surface p-4"
        >
          <header className="mb-3 flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-text">
              {String(t.title || `Table ${idx + 1}`)}
            </h4>
            {t.pageRef != null && String(t.pageRef) !== '' && (
              <Badge variant="muted">Page {String(t.pageRef)}</Badge>
            )}
            {Boolean(t.source) && <Badge variant="muted">Source: {String(t.source)}</Badge>}
            {t.rowCount != null && (
              <span className="text-xs text-text-muted">{String(t.rowCount)} rows detected</span>
            )}
          </header>

          {Array.isArray(t.columns) && (t.columns as unknown[]).length > 0 && (
            <div className="mb-3">
              <p className="mb-1.5 text-xs font-medium text-text-muted">Column headers</p>
              <div className="flex flex-wrap gap-1.5">
                {(t.columns as unknown[]).slice(0, 14).map((col, ci) => (
                  <span
                    key={ci}
                    className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800"
                  >
                    {formatColumnLabel(col)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {Array.isArray(t.sampleRows) && (t.sampleRows as unknown[]).length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-medium text-text-muted">Sample rows from PDF</p>
              <pre className="max-h-32 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-text-muted">
                {JSON.stringify(t.sampleRows, null, 2)}
              </pre>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function ChartsPanel({
  allFigures,
  chartFigures,
  pureFigures,
}: {
  allFigures: Array<Record<string, unknown>>;
  chartFigures: Array<Record<string, unknown>>;
  pureFigures: Array<Record<string, unknown>>;
}) {
  if (allFigures.length === 0) {
    return (
      <EmptyState
        title="No charts or figures found"
        body="The PDF may not contain embedded charts, or visual detection did not find chart regions."
      />
    );
  }

  const typeCounts = allFigures.reduce<Record<string, number>>((acc, f) => {
    const t = String(f.chartType || f.type || 'other');
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900">
          {allFigures.length} total visuals
        </span>
        <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-900">
          {chartFigures.length} charts
        </span>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
          {pureFigures.length} other figures
        </span>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-text-muted">Chart types found</p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(typeCounts)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => (
              <span
                key={type}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${chartTypeColor(type)}`}
              >
                {type.replace(/_/g, ' ')} × {count}
              </span>
            ))}
        </div>
      </div>

      <div className="space-y-3">
        {allFigures.slice(0, 24).map((f, idx) => {
          const chartType = String(f.chartType || f.type || 'figure');
          const title = String(
            f.title || f.caption || `Visual on page ${Number(f.page || 0) + 1}`
          );
          const pageNum = Number(f.page || 0) + 1;
          const source = String(f.detectionSource || f.source || 'unknown');
          const desc = String(f.description || f.vlmDescription || '');

          return (
            <article
              key={`fig-${String(f.figureId || idx)}`}
              className="rounded-xl border border-border bg-surface p-4"
            >
              <div className="flex flex-wrap items-start gap-2">
                <span
                  className={`rounded-md px-2 py-0.5 text-xs font-semibold ${chartTypeColor(chartType)}`}
                >
                  {chartType.replace(/_/g, ' ')}
                </span>
                <h4 className="min-w-0 flex-1 text-sm font-medium text-text">{title}</h4>
                <Badge variant="muted">Page {pageNum}</Badge>
              </div>
              {desc && (
                <p className="mt-2 text-sm leading-relaxed text-text-muted">{desc}</p>
              )}
              <p className="mt-2 text-xs text-text-muted">
                Detected via{' '}
                <span className="font-medium text-text">
                  {source === 'vlm'
                    ? 'vision AI'
                    : source === 'embedded'
                      ? 'embedded image'
                      : source === 'layoutlm'
                        ? 'layout model'
                        : source}
                </span>
                {Boolean(f.areaFraction) && (
                  <> · covers {Math.round(Number(f.areaFraction) * 100)}% of page</>
                )}
              </p>
            </article>
          );
        })}
        {allFigures.length > 24 && (
          <p className="text-center text-sm text-text-muted">
            And {allFigures.length - 24} more visuals not shown
          </p>
        )}
      </div>
    </div>
  );
}

function BlueprintPanel({
  topics,
  tableTemplates,
  entityCount,
  entityNameById,
}: {
  topics: Array<Record<string, unknown>>;
  tableTemplates: Array<Record<string, unknown>>;
  entityCount: number;
  entityNameById: Map<string, string>;
}) {
  if (topics.length === 0) {
    return (
      <EmptyState
        title="Blueprint not generated"
        body="Re-run template extraction to populate report topics and analytical questions."
      />
    );
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-text-muted">
        {topics.length} report topics · {entityCount} linked data fields ·{' '}
        {tableTemplates.length} table layouts
      </p>

      <div className="space-y-3">
        {topics.map((topicRaw, ti) => {
          const topic = topicRaw as Record<string, unknown>;
          const qs = Array.isArray(topic.questions)
            ? (topic.questions as Array<Record<string, unknown>>)
            : [];
          return (
            <details
              key={ti}
              className="group rounded-xl border border-border bg-surface open:shadow-sm"
              open={ti === 0}
            >
              <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                  {ti + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-text">
                    {String(topic.title || topic.topicId || `Topic ${ti + 1}`)}
                  </p>
                  <p className="text-xs text-text-muted">
                    {qs.length} analytical question{qs.length === 1 ? '' : 's'} in this section
                  </p>
                </div>
              </summary>
              <div className="space-y-2 border-t border-border/50 px-4 pb-4 pt-3">
                {qs.length === 0 && (
                  <p className="text-sm text-text-muted">No questions in this topic yet.</p>
                )}
                {qs.slice(0, 10).map((q, qi) => (
                  <div
                    key={qi}
                    className="rounded-lg border border-border/50 bg-white/70 p-3"
                  >
                    <div className="flex flex-wrap items-start gap-2">
                      <span
                        className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                          QUESTION_TYPE_COLORS[String(q.questionType)] ||
                          'bg-slate-100 text-slate-700'
                        }`}
                      >
                        {String(q.questionType || 'describe')}
                      </span>
                      <p className="flex-1 text-sm text-text">
                        {String(q.intent || q.questionId || '—')}
                      </p>
                    </div>
                    {Array.isArray(q.requiredEntities) &&
                      (q.requiredEntities as Array<Record<string, unknown>>).length > 0 && (
                        <div className="mt-2">
                          <p className="mb-1 text-[11px] font-medium text-text-muted">
                            Requires these data fields:
                          </p>
                          <div className="flex flex-wrap gap-1.5">
                            {(q.requiredEntities as Array<Record<string, unknown>>)
                              .slice(0, 6)
                              .map((re, ri) => (
                                <span
                                  key={ri}
                                  className="rounded-md bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-800"
                                >
                                  {resolveEntityLabel(
                                    re.entityRef || re.entityId,
                                    entityNameById
                                  )}
                                  <span className="opacity-70"> ({String(re.role || 'field')})</span>
                                </span>
                              ))}
                          </div>
                        </div>
                      )}
                  </div>
                ))}
              </div>
            </details>
          );
        })}
      </div>

      {tableTemplates.length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-4">
          <h4 className="mb-2 text-sm font-semibold text-text">Table layouts in blueprint</h4>
          <ul className="space-y-2">
            {(tableTemplates as Array<Record<string, unknown>>).slice(0, 10).map((t, ti) => (
              <li key={ti} className="flex items-center justify-between text-sm">
                <span className="font-medium text-text">
                  {String(t.title || t.tableId || `Table ${ti + 1}`)}
                </span>
                {Array.isArray(t.columns) && (
                  <span className="text-xs text-text-muted">
                    {(t.columns as unknown[]).length} columns
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function QuestionsPanel({ questions }: { questions: string[] }) {
  if (questions.length === 0) {
    return (
      <EmptyState
        title="No questions extracted"
        body="The pipeline did not infer analytical questions from this PDF."
      />
    );
  }

  return (
    <ol className="space-y-2">
      {questions.slice(0, 30).map((q, idx) => (
        <li
          key={`q-${idx}`}
          className="flex gap-3 rounded-xl border border-border bg-surface px-4 py-3"
        >
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
            {idx + 1}
          </span>
          <p className="text-sm leading-relaxed text-text">{String(q)}</p>
        </li>
      ))}
      {questions.length > 30 && (
        <p className="text-center text-sm text-text-muted">
          And {questions.length - 30} more questions
        </p>
      )}
    </ol>
  );
}

function TracePanel({
  passes,
  pipelineTrace,
}: {
  passes: Record<string, Record<string, unknown>>;
  pipelineTrace: Record<string, unknown>;
}) {
  if (Object.keys(passes).length === 0) {
    return (
      <EmptyState
        title="No extraction log available"
        body="Re-extract this template with the latest backend to record pipeline timing and quality metrics."
      />
    );
  }

  const total = Number(pipelineTrace.total_elapsed || 1);

  return (
    <div className="space-y-6">
      <div>
        <h4 className="mb-1 text-sm font-semibold text-text">Processing steps</h4>
        <p className="mb-4 text-xs text-text-muted">
          Each bar shows how long a pipeline step took relative to the full run (
          {String(pipelineTrace.total_elapsed || 0)}s total).
        </p>
        <div className="space-y-3">
          {Object.entries(passes).map(([name, stepData]) => {
            const meta = PASS_LABELS[name] || {
              title: name.replace(/_/g, ' '),
              description: 'Pipeline processing step',
            };
            const elapsed = Number(stepData.elapsed_s || 0);
            const pct = Math.min(Math.round((elapsed / total) * 100), 100);
            return (
              <div key={name} className="rounded-xl border border-border bg-surface p-3">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-text">{meta.title}</p>
                    <p className="text-xs text-text-muted">{meta.description}</p>
                  </div>
                  <span className="text-sm font-semibold tabular-nums text-text">
                    {elapsed}s ({pct}%)
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-primary/75 transition-all"
                    style={{ width: `${Math.max(pct, 3)}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <h4 className="mb-3 text-sm font-semibold text-text">Quality checks</h4>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {passes.pass0_rasterize && (
            <QualityStat
              label="Pages converted to images"
              value={String((passes.pass0_rasterize as Record<string, unknown>).images || 0)}
            />
          )}
          {passes.pass1_layout && (
            <QualityStat
              label="Layout regions found"
              value={String((passes.pass1_layout as Record<string, unknown>).total_regions || 0)}
            />
          )}
          {(passes.pass2_entities || passes.pass2_vlm) && (
            <QualityStat
              label="Vision model success rate"
              value={`${String(
                ((passes.pass2_entities || passes.pass2_vlm) as Record<string, unknown>)
                  .vlm_success_rate || 0
              )}%`}
            />
          )}
          {(passes.pass3_questions || passes.pass3_semantic) && (
            <QualityStat
              label="Questions generated"
              value={String(
                ((passes.pass3_questions || passes.pass3_semantic) as Record<string, unknown>)
                  .questions ||
                  ((passes.pass3_questions || passes.pass3_semantic) as Record<string, unknown>)
                    .source ||
                  '—'
              )}
            />
          )}
          {(passes.pass2_5_kg || passes.pass2_5_merge) && (
            <QualityStat
              label="Knowledge graph entities"
              value={String(
                ((passes.pass2_5_kg || passes.pass2_5_merge) as Record<string, unknown>)
                  .total_entities ||
                  ((passes.pass2_5_kg || passes.pass2_5_merge) as Record<string, unknown>)
                    .hierarchy_nodes ||
                  0
              )}
            />
          )}
          {passes.pass4_assembly && (
            <>
              <QualityStat
                label="Tables assembled"
                value={String((passes.pass4_assembly as Record<string, unknown>).tables || 0)}
              />
              <QualityStat
                label="Charts assembled"
                value={String(
                  (passes.pass4_assembly as Record<string, unknown>).charts_detected ??
                    (passes.pass4_assembly as Record<string, unknown>).figures ??
                    0
                )}
              />
            </>
          )}
        </div>
      </div>

      <details className="rounded-xl border border-border bg-surface">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-text-muted">
          View raw pipeline JSON (for developers)
        </summary>
        <pre className="max-h-64 overflow-auto border-t border-border px-4 pb-4 pt-2 text-xs text-text-muted">
          {JSON.stringify(pipelineTrace, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function QualityStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <p className="text-xl font-bold tabular-nums text-text">{value}</p>
      <p className="mt-1 text-xs leading-snug text-text-muted">{label}</p>
    </div>
  );
}
