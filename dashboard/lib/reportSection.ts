// ─────────────────────────────────────────────────────────────────────────────
// report.section.v1 builder config → canonical team contract.
//
// The loop-template "query indicator" builder lets an officer pick columns,
// filter values, choose dimensions/measures (optionally weighted) and the
// analysis + components they want. That editable config (`ReportSectionConfig`)
// compiles into the team's canonical `ReportSectionRequest`
// (dashboard/lib/report-section/types.ts) that the slice engine and canvas
// section workflow consume. We import the team types so the emitted JSON always
// matches the contract exactly (ops `ne/ge/le`, `mode: append|insert_after`,
// `engine: local|backend|auto`, etc.).
// ─────────────────────────────────────────────────────────────────────────────

import type {
  AggregationKind,
  AnalysisType,
  FilterOp,
  ReportSectionRequest,
  SectionComponentConfig,
  SectionComponentType,
  SectionMeasure as TeamSectionMeasure,
  SectionPredicate,
} from '@/lib/report-section';

export type { AggregationKind, AnalysisType, FilterOp, ReportSectionRequest, SectionComponentType } from '@/lib/report-section';

export type ChartType = 'bar' | 'hbar' | 'line' | 'donut' | 'pie';

// ── Editable builder config (UI state, lifted to the binding page) ──────────
export interface SectionFilterRule {
  id: string;
  col: string;
  op: FilterOp;
  value: string; // raw text; `in/not_in` → comma list, `between` → "lo, hi"
  required: boolean;
  connector?: 'AND' | 'OR'; // joins THIS rule to the NEXT rule; last rule's connector is ignored
}

export interface SectionMeasure {
  id: string;
  col: string;
  label: string;
  agg: AggregationKind;
  unit: string;
  weighted: boolean; // toggled with the "w" button → agg becomes weighted_mean
}

export interface ReportSectionConfig {
  chapterTitle: string;
  sectionTitle: string;
  mode: 'append' | 'insert_after';
  filters: SectionFilterRule[];
  combinator: 'AND' | 'OR';
  dimensions: string[];
  measures: SectionMeasure[];
  timeCol: string | null;
  weightCol: string | null;
  descriptionText: string;
  analysisType: AnalysisType;
  sortBy: string | null;
  sortOrder: 'asc' | 'desc';
  components: SectionComponentType[];
  chartType: ChartType;
  engine: 'local' | 'backend' | 'auto';
  cache: boolean;
  verify: boolean;
  requireEvidence: boolean;
  warningPolicy: 'acknowledge_before_append' | 'warn_only' | 'block_on_warning';
}

const NUMERIC_OPS: FilterOp[] = ['gt', 'ge', 'lt', 'le'];
const NO_VALUE_OPS: FilterOp[] = ['is_null', 'not_null'];

let idSeq = 0;
export function newId(prefix: string): string {
  idSeq += 1;
  return `${prefix}_${Date.now().toString(36)}_${idSeq}`;
}

/** URL/id-safe slug: lowercase alphanumerics joined by underscores. */
export function slug(text: string, fallback = 'section'): string {
  const s = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_');
  return s || fallback;
}

/** Short deterministic hash (djb2) → 8 hex chars, for stable requestIds. */
export function shortHash(text: string): string {
  let h = 5381;
  for (let i = 0; i < text.length; i += 1) {
    h = ((h << 5) + h + text.charCodeAt(i)) >>> 0;
  }
  return h.toString(16).padStart(8, '0').slice(0, 8);
}

export function defaultSectionConfig(): ReportSectionConfig {
  return {
    chapterTitle: 'Generated Analysis',
    sectionTitle: 'New Section',
    mode: 'append',
    filters: [],
    combinator: 'AND',
    dimensions: [],
    measures: [],
    timeCol: null,
    weightCol: null,
    descriptionText: '',
    analysisType: 'comparison',
    sortBy: null,
    sortOrder: 'desc',
    components: ['narrative', 'table', 'chart', 'key_finding'],
    chartType: 'bar',
    engine: 'local',
    cache: true,
    verify: true,
    requireEvidence: true,
    warningPolicy: 'acknowledge_before_append',
  };
}

const FILTER_OP_TEXT: Record<FilterOp, string> = {
  eq: 'equals',
  ne: 'does not equal',
  gt: 'is greater than',
  ge: 'is at least',
  lt: 'is less than',
  le: 'is at most',
  in: 'is one of',
  not_in: 'is not one of',
  between: 'is between',
  contains: 'contains',
  is_null: 'is empty',
  not_null: 'is not empty',
};

function joinHuman(parts: string[]): string {
  const clean = parts.map((p) => p.trim()).filter(Boolean);
  if (clean.length <= 1) return clean[0] ?? '';
  if (clean.length === 2) return `${clean[0]} and ${clean[1]}`;
  return `${clean.slice(0, -1).join(', ')}, and ${clean[clean.length - 1]}`;
}

function readableAgg(agg: AggregationKind): string {
  return agg.replace(/_/g, ' ');
}

function describeFilter(rule: SectionFilterRule): string {
  const col = rule.col.trim();
  if (!col) return '';
  const op = FILTER_OP_TEXT[rule.op] ?? rule.op;
  const raw = rule.value.trim();
  if (NO_VALUE_OPS.includes(rule.op)) return `${col} ${op}`;
  if (rule.op === 'between') {
    const [lo, hi] = raw.split(',').map((part) => part.trim()).filter(Boolean);
    return `${col} ${op} ${lo || 'lower bound'} and ${hi || 'upper bound'}`;
  }
  if (rule.op === 'in' || rule.op === 'not_in') {
    const values = raw.split(',').map((part) => part.trim()).filter(Boolean);
    return `${col} ${op} ${joinHuman(values) || 'selected values'}`;
  }
  return `${col} ${op} ${raw || 'selected value'}`;
}

function describeFilters(filters: SectionFilterRule[], fallback: 'AND' | 'OR'): string {
  const parts = filters.map(describeFilter).filter(Boolean);
  if (!parts.length) return '';
  return parts.reduce((text, part, index) => {
    if (index === 0) return part;
    const connector = filters[index - 1]?.connector || fallback;
    return `${text} ${connector.toLowerCase()} ${part}`;
  }, '');
}

export function buildSectionDescription(config: ReportSectionConfig): string {
  const measures = config.measures.map((m) => {
    const label = (m.label || m.col).trim();
    const weighted = m.weighted && config.weightCol ? ` weighted by ${config.weightCol}` : '';
    return `${label} (${readableAgg(m.weighted ? 'weighted_mean' : m.agg)}${weighted})`;
  });
  const measureText = joinHuman(measures) || 'the selected indicators';
  const dimensionText = config.dimensions.length ? ` by ${joinHuman(config.dimensions)}` : '';
  const timeText = config.timeCol ? ` across ${config.timeCol}` : '';
  const filterText = describeFilters(config.filters, config.combinator);
  const scopeText = filterText ? ` for rows where ${filterText}` : ' for all rows in scope';
  return `Generate a ${config.analysisType} section showing ${measureText}${dimensionText}${timeText}${scopeText}.`;
}

function coerceScalar(raw: string): string | number {
  const t = raw.trim();
  if (t === '') return t;
  const n = Number(t.replace(/,/g, ''));
  return /^-?\d[\d.]*$/.test(t) && Number.isFinite(n) ? n : t;
}

/** Coerce a builder text value into the shape the team predicate engine expects. */
function coerceFilterValue(op: FilterOp, raw: string): unknown {
  if (NO_VALUE_OPS.includes(op)) return undefined;
  if (op === 'in' || op === 'not_in') {
    return raw
      .split(',')
      .map((s) => coerceScalar(s.trim()))
      .filter((s) => s !== '');
  }
  if (op === 'between') {
    const parts = raw.split(',').map((s) => Number(s.trim()));
    return [parts[0] ?? null, parts[1] ?? null];
  }
  if (NUMERIC_OPS.includes(op)) {
    const n = Number(raw.replace(/,/g, ''));
    return Number.isFinite(n) ? n : raw.trim();
  }
  return coerceScalar(raw);
}

function titleFor(type: SectionComponentType, config: ReportSectionConfig): string {
  const firstDim = config.dimensions[0];
  const firstMeasure = config.measures[0];
  const measureLabel = firstMeasure?.label || firstMeasure?.col || 'Value';
  switch (type) {
    case 'narrative':
      return 'Comparative Summary';
    case 'table':
      return firstDim ? `${measureLabel} by ${firstDim}` : measureLabel;
    case 'chart':
      return measureLabel;
    case 'metric':
      return measureLabel;
    case 'key_finding':
      return 'Key Finding';
    case 'source_note':
      return 'Source';
    case 'caveat':
      return 'Caveat';
    case 'footnote':
      return 'Footnote';
    default:
      return 'Section';
  }
}

function buildComponent(type: SectionComponentType, config: ReportSectionConfig): SectionComponentConfig {
  const firstDim = config.dimensions[0];
  const firstMeasure = config.measures[0];
  const base: SectionComponentConfig = { type, title: titleFor(type, config) };
  if (type === 'narrative') base.maxWords = 120;
  if (type === 'chart') {
    base.chartType = config.chartType;
    if (firstDim) base.x = firstDim;
    if (firstMeasure) base.y = firstMeasure.col;
  }
  return base;
}

/** Compile the editable builder config into the canonical report.section.v1 request. */
export function buildReportSectionSpec(
  config: ReportSectionConfig,
  ctx: { templateId: string; signature: string; datasetId: string },
): ReportSectionRequest {
  const includeSet = new Set<string>();
  config.dimensions.forEach((c) => includeSet.add(c));
  config.measures.forEach((m) => includeSet.add(m.col));
  config.filters.forEach((f) => f.col && includeSet.add(f.col));
  if (config.timeCol) includeSet.add(config.timeCol);
  if (config.weightCol && config.measures.some((m) => m.weighted)) includeSet.add(config.weightCol);

  const chapterTitle = config.chapterTitle.trim() || 'Generated Analysis';
  const sectionTitle = config.sectionTitle.trim() || 'New Section';
  const requestId = `req_${slug(sectionTitle)}_${shortHash(`${ctx.signature}:${sectionTitle}:${chapterTitle}`)}`;

  const filters: SectionPredicate[] = config.filters
    .filter((f) => f.col)
    .map((f) => {
      const predicate: SectionPredicate = { col: f.col, op: f.op, required: f.required, connector: f.connector };
      const value = coerceFilterValue(f.op, f.value);
      if (value !== undefined) predicate.value = value;
      return predicate;
    });

  const measures: TeamSectionMeasure[] = config.measures.map((m) => ({
    col: m.col,
    label: m.label.trim() || m.col,
    agg: m.weighted ? 'weighted_mean' : m.agg,
    unit: m.unit.trim() || undefined,
    weightCol: m.weighted ? config.weightCol : null,
    moe: m.weighted && config.weightCol ? { enabled: true, confidence: 0.95, mode: 'frequency' } : undefined,
  }));

  const descriptionText = config.descriptionText.trim();

  return {
    version: 'report.section.v1',
    requestId,
    datasetId: ctx.datasetId,
    target: {
      templateId: ctx.templateId,
      signature: ctx.signature,
      mode: config.mode,
      chapter: { id: `ch_${slug(chapterTitle, 'chapter')}`, title: chapterTitle, create: true },
      section: { id: `sec_${slug(sectionTitle)}`, title: sectionTitle, create: true },
      insertAfterBlockId: null,
    },
    scope: {
      filters,
      filterCombinator: config.combinator,
      columns: {
        dimensions: config.dimensions,
        measures,
        time: config.timeCol,
        include: Array.from(includeSet),
      },
    },
    description: {
      text: descriptionText || buildSectionDescription(config),
      source: descriptionText ? 'user' : 'suggested',
    },
    analysis: {
      type: config.analysisType,
      groupBy: config.dimensions,
      sort: config.sortBy ? { by: config.sortBy, order: config.sortOrder } : null,
    },
    components: config.components.map((c) => buildComponent(c, config)),
    options: {
      engine: config.engine,
      cache: config.cache,
      verify: config.verify,
      requireEvidence: config.requireEvidence,
      warningPolicy: config.warningPolicy,
    },
  };
}

/** Lightweight readiness check for the section config (officer guidance). */
export function validateSectionConfig(
  config: ReportSectionConfig,
  options: {
    requireMeasure?: boolean;
    requireDimension?: boolean;
    requireComponents?: boolean;
    requireChartAxis?: boolean;
  } = {},
): string[] {
  const requireMeasure = options.requireMeasure ?? true;
  const requireDimension = options.requireDimension ?? true;
  const requireComponents = options.requireComponents ?? true;
  const requireChartAxis = options.requireChartAxis ?? true;
  const issues: string[] = [];
  if (!config.sectionTitle.trim()) issues.push('Section title is required.');
  if (requireMeasure && config.measures.length === 0) issues.push('Add at least one measure column.');
  if (requireDimension && !['summary', 'metric'].includes(config.analysisType) && config.dimensions.length === 0) issues.push('Pick at least one dimension to group by.');
  if (config.analysisType === 'trend' && !config.timeCol) issues.push('Trend analysis needs a time column.');
  if (requireComponents && config.components.length === 0) issues.push('Select at least one output component.');
  if (requireChartAxis && config.components.includes('chart') && config.dimensions.length === 0) issues.push('A chart needs at least one dimension for its x-axis.');
  for (const measure of config.measures) {
    if (measure.weighted && !config.weightCol) issues.push(`Weighted measure '${measure.label || measure.col}' needs a multiplier column.`);
  }
  for (const filter of config.filters) {
    if (!filter.col) issues.push('Every filter needs a column.');
    if (!NO_VALUE_OPS.includes(filter.op) && !filter.value.trim()) issues.push(`Filter '${filter.col || 'column'}' needs a value.`);
    if (filter.op === 'between' && filter.value.split(',').map((part) => part.trim()).filter(Boolean).length < 2) issues.push(`Between filter '${filter.col}' needs two values.`);
  }
  return issues;
}
