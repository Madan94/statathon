import { buildEntityNameMap } from '@/lib/entityDisplayUtils';

export type AstTabId =
  | 'overview'
  | 'blocks'
  | 'entities'
  | 'tables'
  | 'charts'
  | 'blueprint'
  | 'questions'
  | 'trace';

export interface ParsedTemplateAst {
  docId: string;
  pageCount: number;
  extractionMethod: string;
  totalElapsed: string | number | null;
  blocks: Array<Record<string, unknown>>;
  entities: Array<Record<string, unknown>>;
  tables: Array<Record<string, unknown>>;
  allFigures: Array<Record<string, unknown>>;
  chartFigures: Array<Record<string, unknown>>;
  pureFigures: Array<Record<string, unknown>>;
  hierarchy: Array<Record<string, unknown>>;
  facts: Array<Record<string, unknown>>;
  questionStrings: string[];
  bpTopics: Array<Record<string, unknown>>;
  bpEntities: Array<Record<string, unknown>>;
  bpTableTemplates: Array<Record<string, unknown>>;
  entityNameById: Map<string, string>;
  pipelineTrace: Record<string, unknown>;
  passes: Record<string, Record<string, unknown>>;
  hasContent: boolean;
}

export function parseTemplateAst(ast: Record<string, unknown>): ParsedTemplateAst {
  const enterpriseAst = (ast.enterprise_ast as Record<string, unknown>) || {};
  const assets = (ast.extracted_assets as Record<string, unknown> | undefined) || {};
  const pipelineTrace =
    (ast.pipeline_trace as Record<string, unknown>) ||
    (enterpriseAst.pipeline_trace as Record<string, unknown>) ||
    {};
  const passes = (pipelineTrace.passes as Record<string, Record<string, unknown>>) || {};

  const semanticAST =
    (ast.semanticAST as Record<string, unknown>) ||
    (enterpriseAst.semanticAST as Record<string, unknown>) ||
    {};
  const sections = Array.isArray(semanticAST.sections)
    ? (semanticAST.sections as Array<Record<string, unknown>>)
    : [];
  const hierarchy =
    sections.length > 0
      ? sections
      : Array.isArray(semanticAST.hierarchy)
        ? (semanticAST.hierarchy as Array<Record<string, unknown>>)
        : [];

  const entityGraph =
    (ast.entityGraph as Record<string, unknown>) ||
    (enterpriseAst.entityGraph as Record<string, unknown>) ||
    {};
  const entities = Array.isArray(entityGraph.entities)
    ? (entityGraph.entities as Array<Record<string, unknown>>)
    : [];

  const tableAST =
    (ast.tableAST as Record<string, unknown>) ||
    (enterpriseAst.tableAST as Record<string, unknown>) ||
    {};
  const tables = Array.isArray(tableAST.tables)
    ? (tableAST.tables as Array<Record<string, unknown>>)
    : [];

  const factGraph =
    (ast.factGraph as Record<string, unknown>) ||
    (enterpriseAst.factGraph as Record<string, unknown>) ||
    {};
  const facts = Array.isArray(factGraph.facts)
    ? (factGraph.facts as Array<Record<string, unknown>>)
    : [];

  const questionStrings = Array.isArray(ast.questions) ? (ast.questions as string[]) : [];
  const blocks = Array.isArray(ast.blocks) ? (ast.blocks as Array<Record<string, unknown>>) : [];

  const figureAST = (ast.figureAST as Record<string, unknown>) || {};
  const allFigures = Array.isArray(figureAST.figures)
    ? (figureAST.figures as Array<Record<string, unknown>>)
    : [];
  const chartAST = (ast.chartAST as Record<string, unknown>) || {};
  const charts = Array.isArray(chartAST.charts)
    ? (chartAST.charts as Array<Record<string, unknown>>)
    : [];
  const chartFigures =
    charts.length > 0
      ? charts
      : allFigures.filter((f) => f.type === 'chart' || Boolean(f.chartType));
  const pureFigures = allFigures.filter((f) => !f.chartRef);

  const blueprint =
    (ast.blueprint as Record<string, unknown>) ||
    (enterpriseAst.blueprint as Record<string, unknown>) ||
    {};
  const bpTopics = Array.isArray(blueprint.topics)
    ? (blueprint.topics as Array<Record<string, unknown>>)
    : [];
  const bpEntities = Array.isArray(blueprint.entities)
    ? (blueprint.entities as Array<Record<string, unknown>>)
    : [];
  const bpTableTemplates = Array.isArray(blueprint.tableTemplates)
    ? (blueprint.tableTemplates as Array<Record<string, unknown>>)
    : [];

  const entityNameById = buildEntityNameMap(bpEntities, entities);
  const textPages = Array.isArray(assets.text_pages)
    ? (assets.text_pages as Array<Record<string, unknown>>)
    : [];

  const docId = String(
    ast.doc_id ||
      (enterpriseAst.metadata as Record<string, unknown> | undefined)?.documentId ||
      '—'
  );

  return {
    docId,
    pageCount: Number(ast.page_count || 0),
    extractionMethod: String(ast.extraction_method || 'unknown'),
    totalElapsed: pipelineTrace.total_elapsed as string | number | null,
    blocks,
    entities,
    tables,
    allFigures,
    chartFigures,
    pureFigures,
    hierarchy,
    facts,
    questionStrings,
    bpTopics,
    bpEntities,
    bpTableTemplates,
    entityNameById,
    pipelineTrace,
    passes,
    hasContent:
      textPages.length > 0 ||
      entities.length > 0 ||
      blocks.length > 0 ||
      hierarchy.length > 0 ||
      charts.length > 0 ||
      bpTopics.length > 0 ||
      tables.length > 0,
  };
}

export const PASS_LABELS: Record<string, { title: string; description: string }> = {
  pass0_rasterize: {
    title: 'PDF to page images',
    description: 'Each PDF page is converted into an image for visual analysis.',
  },
  pass1_layout: {
    title: 'Layout detection',
    description: 'Headings, paragraphs, tables, and chart regions are located on each page.',
  },
  pass2_entities: {
    title: 'Entity extraction',
    description: 'Named fields and measures are identified from text and visuals.',
  },
  pass2_vlm: {
    title: 'Visual language model',
    description: 'Charts and complex regions are interpreted using vision AI.',
  },
  'pass2_5_kg': {
    title: 'Knowledge graph merge',
    description: 'Extracted entities are linked into a structured hierarchy.',
  },
  pass2_5_merge: {
    title: 'Knowledge graph merge',
    description: 'Extracted entities are linked into a structured hierarchy.',
  },
  pass3_questions: {
    title: 'Question generation',
    description: 'Analytical questions are inferred from the document content.',
  },
  pass3_semantic: {
    title: 'Semantic analysis',
    description: 'Document meaning and section relationships are mapped.',
  },
  pass4_assembly: {
    title: 'AST assembly',
    description: 'All pieces are combined into the final template blueprint.',
  },
};

export function formatColumnLabel(col: unknown): string {
  if (typeof col === 'string') return col;
  if (typeof col === 'object' && col !== null) {
    const o = col as Record<string, unknown>;
    return String(o.header || o.columnId || JSON.stringify(col));
  }
  return String(col);
}
