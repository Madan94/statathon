export type DataRow = Record<string, unknown>;

export type FilterOp =
  | 'eq'
  | 'ne'
  | 'in'
  | 'not_in'
  | 'gt'
  | 'ge'
  | 'lt'
  | 'le'
  | 'between'
  | 'contains'
  | 'is_null'
  | 'not_null';

export type AnalysisType = 'summary' | 'comparison' | 'trend' | 'ranking' | 'distribution' | 'metric';
export type SectionComponentType = 'narrative' | 'table' | 'chart' | 'metric' | 'key_finding' | 'source_note' | 'footnote' | 'caveat';
export type AggregationKind = 'reported_value' | 'mean' | 'sum' | 'count' | 'median' | 'min' | 'max' | 'weighted_mean' | 'weighted_ratio';
export type WarningSeverity = 'info' | 'warn' | 'error';

export interface SectionPredicate {
  col: string;
  op: FilterOp;
  value?: unknown;
  required?: boolean;
}

export interface SectionMeasure {
  col: string;
  label?: string;
  agg?: AggregationKind;
  unit?: string;
}

export interface SectionTargetRef {
  templateId: string;
  signature: string;
  mode?: 'append' | 'insert_after';
  chapter?: { id?: string | null; title: string; create?: boolean } | null;
  section?: { id?: string | null; title: string; create?: boolean } | null;
  insertAfterBlockId?: string | null;
}

export interface ReportSectionRequest {
  version: 'report.section.v1';
  requestId: string;
  datasetId: string;
  target: SectionTargetRef;
  scope: {
    filters: SectionPredicate[];
    columns: {
      dimensions: string[];
      measures: SectionMeasure[];
      time?: string | null;
      include: string[];
    };
  };
  description: {
    text: string;
    source: 'user' | 'suggested' | 'system';
  };
  analysis: {
    type: AnalysisType;
    groupBy?: string[];
    sort?: { by: string; order: 'asc' | 'desc' } | null;
    limit?: number | null;
  };
  components: SectionComponentConfig[];
  options?: {
    engine?: 'local' | 'backend' | 'auto';
    cache?: boolean;
    verify?: boolean;
    requireEvidence?: boolean;
    warningPolicy?: 'acknowledge_before_append' | 'warn_only' | 'block_on_warning';
  };
}

export interface SectionComponentConfig {
  type: SectionComponentType;
  title: string;
  maxWords?: number;
  chartType?: 'bar' | 'hbar' | 'line' | 'donut' | 'pie';
  x?: string;
  y?: string;
  series?: string | null;
  enabled?: boolean;
}

export interface DatasetSnapshot {
  datasetId: string;
  rows: DataRow[];
  columns: string[];
  columnTypes: Record<string, 'number' | 'string' | 'boolean' | 'date' | 'unknown'>;
  distinctValues: Record<string, unknown[]>;
  signature: string;
  rowCount: number;
}

export interface SectionIssue {
  severity: WarningSeverity;
  code: string;
  message: string;
  column?: string;
  suggestion?: unknown;
}

export interface SectionValidationResult {
  status: 'ready' | 'warning' | 'cannot_compute';
  issues: SectionIssue[];
}

export interface DescriptionSuggestion {
  suggestionId: string;
  label: string;
  description: string;
  analysisPatch: Partial<ReportSectionRequest['analysis']>;
  recommendedComponents: SectionComponentConfig[];
  reason: string;
}

export interface ComponentSuggestion {
  component: SectionComponentConfig;
  recommended: boolean;
  reason: string;
}

export interface QueryAst {
  datasetId: string;
  select: Array<{ expr: string; as: string; role: 'dimension' | 'measure' | 'metadata'; agg?: AggregationKind; unit?: string }>;
  where: SectionPredicate[];
  groupBy: string[];
  orderBy?: { expr: string; direction: 'asc' | 'desc' } | null;
  limit?: number | null;
  provenance: { rowIdsRequired: boolean; sourceColumns: string[] };
}

export interface SectionResultRow {
  key: Record<string, unknown>;
  value: number | null;
  n: number;
  rowIds: string[];
}

export interface SectionExecutionResult {
  requestId: string;
  datasetId: string;
  rows: SectionResultRow[];
  measure: SectionMeasure | null;
  groupBy: string[];
  filtersApplied: string[];
  rowsScanned: number;
  rowsAfterFilter: number;
  cacheHit: boolean;
  sliceSignature: string;
  warnings: SectionIssue[];
}

export interface GeneratedSectionBlock {
  id: string;
  index: number;
  kind: 'heading' | 'narrative' | 'table' | 'chart' | 'metric' | 'key_finding' | 'source_note' | 'divider';
  title: string;
  content: string;
  tableData?: Record<string, unknown>;
  metricValue?: string;
  metricUnit?: string;
  sectionPath: string[];
  status: 'pending' | 'generating' | 'done' | 'error';
  pageIndex: number;
}

export interface CanvasPatchOperation {
  op: 'create_chapter' | 'create_section' | 'append_block' | 'insert_after_block';
  block?: GeneratedSectionBlock;
  chapterTitle?: string;
  sectionTitle?: string;
  afterBlockId?: string | null;
}

export interface CanvasPatch {
  requestId: string;
  templateId: string;
  signature: string;
  operations: CanvasPatchOperation[];
}
