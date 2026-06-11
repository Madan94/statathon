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
  // Phase 6 lineage enrichment (optional — older reports won't have these).
  planId?: string;
  componentRef?: string;
  sourceColumns?: string[];
  formulaType?: string;
  filters?: string[];
  rowIds?: string[];
  contentHash?: string;
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
  locked?: boolean;
  title?: LocalizedLabel;
  items?: string[];
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

/** Phase 5 — one verifier check (pass | warn | fail). */
export interface VerificationCheck {
  code: string;
  severity: 'pass' | 'warn' | 'fail' | string;
  message: string;
  refs?: Record<string, unknown>;
}

/** Phase 5 — verifier verdict + quality score. */
export interface Verification {
  verdict?: 'PASS' | 'WARN' | 'FAIL' | string;
  checks?: VerificationCheck[];
  quality?: {
    finalScore?: number;
    provenanceCoverage?: number;
    formulaCoverage?: number;
    verifiedNumberRatio?: number;
    caveatCoverage?: number;
    blockedLeakCount?: number;
    failCount?: number;
    warnCount?: number;
    [k: string]: number | undefined;
  };
}

/** Phase 8 — publish gate decision. */
export interface GateDecision {
  verdict?: string;
  publishMode?: 'strict' | 'draft' | string;
  publishable?: boolean;
  blocked?: boolean;
  reason?: string;
  failedChecks?: string[];
}

/** Phase 7 — one evidence-backed BI insight. */
export interface Insight {
  insightId: string;
  kind: string;
  text: string;
  questionId?: string;
  planId?: string;
  analyticsRef?: string;
  evidenceRef?: string;
  value?: unknown;
  confidence?: number;
  severity?: 'info' | 'warning' | 'caveat' | string;
  refs?: Record<string, unknown>;
}

/** Phase 6 — per-plan provenance lineage entry. */
export interface LineageEntry {
  questionId?: string;
  planId?: string;
  componentRef?: string;
  measureColumn?: string;
  analyticsRef?: string;
  evidenceRef?: string;
  sourceColumns?: string[];
  rowIds?: string[];
  formulaType?: string;
  filters?: string[];
  status?: string;
}

/** Phase 9 — one officer lifecycle transition / action log entry. */
export interface LifecycleEntry {
  action?: string;
  from?: string;
  to?: string;
  blockId?: string;
  fromVersion?: number;
  toVersion?: number;
  by?: string;
  at?: string;
  note?: string;
}

/** The audit subtree — trust (verifier/gate/provenance/insights) + officer control. */
export interface AuditAST {
  warnings?: string[];
  publishable?: boolean;
  verification?: Verification;
  gate?: GateDecision;
  insights?: Insight[];
  provenance?: {
    coverage?: number;
    measuredValues?: number;
    tracedValues?: number;
    datasetSignature?: string;
    contentHash?: string;
    entries?: LineageEntry[];
  };
  statisticalContext?: {
    geographyLevel?: string;
    timeCoverage?: string[];
    unitRegistry?: Record<string, string>;
    sourceNotes?: string[];
    footnotes?: string[];
    estimateStatus?: string;
    surveyRound?: string;
    referenceDate?: string;
    [k: string]: unknown;
  };
  humanReview?: {
    edits?: Array<Record<string, unknown>>;
    lifecycle?: LifecycleEntry[];
  };
  [k: string]: unknown;
}

export interface ReportAST {
  metadata?: {
    reportId?: string;
    title?: string;
    status?: string;
    version?: number;
    period?: { current?: string };
    // Phase 9 lifecycle + Phase 4 reproducibility (optional).
    publishStatus?: string;
    publishedAt?: string;
    publishedBy?: string;
    dataContentHash?: string;
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
