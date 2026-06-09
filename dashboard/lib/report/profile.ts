/**
 * R4 — client-side customization, a faithful port of the server
 * `report_builder/generation/profile.py` so the live preview reshapes the report
 * identically to the exported HTML/PDF: section reorder, question filtering,
 * per-question chart-type swap and table-format override. Overrides are sparse
 * (only set keys take effect).
 */
import type { Chart, ReportAST, Section, Table } from './types';

export interface PerQuestionSpec {
  chartType?: string;
  tableFormat?: string | Record<string, string>;
  tone?: string;
  maxWords?: number;
}

export interface MatterFlags {
  cover?: boolean;
  foreword?: boolean;
  toc?: boolean;
  glossary?: boolean;
  notes?: boolean;
}

export interface ReportOverrides {
  theme?: string;
  numberSystem?: 'indian' | 'international';
  locale?: string;
  sectionOrder?: string[];
  includedQuestions?: string[];
  perQuestion?: Record<string, PerQuestionSpec>;
  frontMatter?: MatterFlags;
  backMatter?: MatterFlags;
}

function clone<T>(value: T): T {
  return typeof structuredClone === 'function'
    ? structuredClone(value)
    : (JSON.parse(JSON.stringify(value)) as T);
}

function chartQuestion(c: Chart): string | undefined {
  return c.provenance?.questionId ?? c.biQuery;
}

function tableQuestion(t: Table): string | undefined {
  return t.provenance?.questionId ?? t.biQuery;
}

/** element id → question id (blocks, figures via chartRef, tables). */
export function elementQuestionMap(report: ReportAST): Record<string, string> {
  const out: Record<string, string> = {};
  for (const b of report.contentAST?.blocks ?? []) {
    const q = b.provenance?.questionId ?? b.biQuery;
    if (b.blockId && q) out[b.blockId] = q;
  }
  const chartQ: Record<string, string> = {};
  for (const c of report.chartAST?.charts ?? []) {
    const q = chartQuestion(c);
    if (c.chartId && q) chartQ[c.chartId] = q;
  }
  for (const f of report.figureAST?.figures ?? []) {
    const q = f.chartRef ? chartQ[f.chartRef] : undefined;
    if (f.figureId && q) out[f.figureId] = q;
  }
  for (const t of report.tableAST?.tables ?? []) {
    const q = tableQuestion(t);
    if (t.tableId && q) out[t.tableId] = q;
  }
  return out;
}

function filterQuestions(report: ReportAST, sections: Section[], included: string[]): Section[] {
  const keep = new Set(included);
  const elemQ = elementQuestionMap(report);
  const out: Section[] = [];
  for (const sec of sections) {
    const children = sec.children ?? [];
    const newChildren = children.filter((c) => elemQ[c] === undefined || keep.has(elemQ[c]));
    const hadQs = children.some((c) => elemQ[c] !== undefined);
    if (hadQs && !newChildren.some((c) => keep.has(elemQ[c]))) continue;
    out.push({ ...sec, children: newChildren });
  }
  return out;
}

function reorderSections(sections: Section[], order: string[]): Section[] {
  const rank = new Map(order.map((sid, i) => [sid, i] as const));
  const big = order.length;
  return sections
    .map((sec, i) => ({ sec, i }))
    .sort((a, b) => {
      const ra = rank.get(a.sec.sectionId ?? '') ?? big;
      const rb = rank.get(b.sec.sectionId ?? '') ?? big;
      return ra - rb || a.i - b.i;
    })
    .map(({ sec }, i) => ({ ...sec, order: i + 1 }));
}

function applyPerQuestion(report: ReportAST, perQuestion: Record<string, PerQuestionSpec>): void {
  for (const [qid, spec] of Object.entries(perQuestion)) {
    if (!spec) continue;
    if (spec.chartType) {
      for (const c of report.chartAST?.charts ?? []) {
        if (chartQuestion(c) === qid) c.chartType = spec.chartType;
      }
    }
    if (spec.tableFormat) {
      for (const t of report.tableAST?.tables ?? []) {
        if (tableQuestion(t) !== qid) continue;
        for (const col of t.columns ?? []) {
          if (typeof spec.tableFormat === 'object') {
            if (col.columnId in spec.tableFormat) col.format = spec.tableFormat[col.columnId];
          } else if (col.role === 'measure') {
            col.format = spec.tableFormat;
          }
        }
      }
    }
  }
}

/** Return a new report reshaped by the sparse overrides (does not mutate input). */
export function applyProfile(report: ReportAST, ov: ReportOverrides): ReportAST {
  const out = clone(report);
  let sections = [...(out.semanticAST?.sections ?? [])];

  if (ov.includedQuestions && ov.includedQuestions.length) {
    sections = filterQuestions(out, sections, ov.includedQuestions);
  }
  if (ov.sectionOrder && ov.sectionOrder.length) {
    sections = reorderSections(sections, ov.sectionOrder);
  }
  out.semanticAST = { ...(out.semanticAST ?? {}), sections };

  if (ov.perQuestion) applyPerQuestion(out, ov.perQuestion);

  return out;
}
