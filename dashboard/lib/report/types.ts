/**
 * R3 — TypeScript types mirroring the server `report.output.ast.json` contract
 * (§0 of PLAN_RENDER_EXECUTION). Kept intentionally loose where the server is
 * permissive, but typed enough for the preview renderer to be safe.
 */

export type Locale = 'en-IN' | 'hi-IN' | string;
export type NumberSystem = 'indian' | 'international';

/** A label that may be plain text or a bilingual `{en,hi}` dict. */
export type LocalizedLabel =
  | string
  | number
  | { en?: string; hi?: string; [lang: string]: string | undefined };

export interface Provenance {
  questionId?: string;
  componentId?: string;
  analyticsRef?: string;
  evidenceRef?: string | string[];
}

export interface ChartPoint {
  x: LocalizedLabel;
  y: number;
  color?: string;
  rowIds?: string[];
}

export interface ChartSeries {
  label?: LocalizedLabel;
  points: ChartPoint[];
}

export interface ChartAxis {
  entityRef?: string;
  label?: LocalizedLabel;
  unit?: string;
}

export interface Chart {
  chartId: string;
  chartType: string;
  title?: LocalizedLabel;
  xAxis?: ChartAxis;
  yAxis?: ChartAxis;
  paletteRef?: string;
  series: ChartSeries[];
  biQuery?: string;
  provenance?: Provenance;
}

export interface Figure {
  figureId: string;
  caption?: LocalizedLabel;
  chartRef?: string;
  figureNumber?: string;
}

export interface ColumnGroup {
  groupId: string;
  label?: LocalizedLabel;
  spanRefs: string[];
}

export interface Column {
  columnId: string;
  header?: LocalizedLabel;
  role?: string;
  unit?: string;
  format?: string | null;
  align?: string;
  group?: string;
}

export interface TableRow {
  rowIds?: string[];
  isTotal?: boolean;
  isSubtotal?: boolean;
  [columnId: string]: unknown;
}

export interface Footnote {
  noteId?: string;
  text?: LocalizedLabel;
}

export interface Table {
  tableId: string;
  title?: LocalizedLabel;
  columnGroups?: ColumnGroup[];
  columns: Column[];
  rows: TableRow[];
  footnotes?: Footnote[];
  tableNumber?: string;
  biQuery?: string;
  provenance?: Provenance;
}

export interface Block {
  blockId: string;
  kind?: string;
  content?: LocalizedLabel;
  provenance?: Provenance;
  biQuery?: string;
}

export interface Section {
  sectionId?: string;
  title?: LocalizedLabel;
  level?: number;
  order?: number;
  children?: string[];
}

export interface EvidenceItem {
  questionId?: string;
  componentId?: string;
  evidenceId?: string;
  analyticsRef?: string;
  computation?: string;
  rowIds?: string[];
}

export interface VerificationCheck {
  code: string;
  severity: 'fail' | 'warn' | 'info' | string;
  message: string;
  [k: string]: unknown;
}

export interface VerificationQuality {
  finalScore?: number;
  provenanceCoverage?: number;
  formulaCoverage?: number;
  failCount?: number;
  warnCount?: number;
  [k: string]: unknown;
}

export interface VerificationSummary {
  verdict?: string;
  quality?: VerificationQuality;
  checks?: VerificationCheck[];
  [k: string]: unknown;
}

export interface PublishGate {
  publishable?: boolean;
  reason?: string;
  [k: string]: unknown;
}

export interface Insight {
  insightId: string;
  text: string;
  severity?: 'finding' | 'caveat' | 'warning' | string;
  [k: string]: unknown;
}

export interface AuditProvenance {
  contentHash?: string;
  [k: string]: unknown;
}

export interface AuditAST {
  verification?: VerificationSummary;
  gate?: PublishGate;
  insights?: Insight[];
  provenance?: AuditProvenance;
  publishable?: boolean;
  [k: string]: unknown;
}

export interface ReportAST {
  metadata?: {
    reportId?: string;
    title?: string;
    status?: string;
    version?: number;
    publishStatus?: string;
    publishedAt?: string;
    publishedBy?: string;
    dataContentHash?: string;
    period?: { current?: string };
    [k: string]: unknown;
  };
  semanticAST?: { sections?: Section[] };
  contentAST?: { blocks?: Block[] };
  figureAST?: { figures?: Figure[] };
  chartAST?: { charts?: Chart[] };
  tableAST?: { tables?: Table[] };
  provenanceAST?: { evidence?: EvidenceItem[] };
  auditAST?: AuditAST;
}

export interface EditTarget {
  kind: string;
  id: string;
  col?: string;
  rowIds?: string[];
  series?: number;
  point?: number;
  note?: string;
}

export interface EditInput {
  target: EditTarget;
  value: string | number;
  reason?: string;
  by?: string;
}
