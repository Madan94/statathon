import type { GeneratedSectionBlock, ReportSectionRequest, SectionComponentConfig, SectionExecutionResult, SectionResultRow } from './types';

function fmt(value: number | null, unit?: string): string {
  if (value == null || Number.isNaN(value)) return 'not available';
  const text = Math.abs(value) >= 1000 ? value.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : value.toFixed(Number.isInteger(value) ? 0 : 1);
  return unit ? `${text}${unit === '%' ? '%' : ` ${unit}`}` : text;
}

function labelOf(row: SectionResultRow): string {
  const values = Object.values(row.key).filter(v => v !== null && v !== undefined && v !== '');
  return values.length ? values.map(String).join(' / ') : 'All records';
}

function narrative(request: ReportSectionRequest, result: SectionExecutionResult, maxWords = 120): string {
  const measure = result.measure;
  const measureLabel = measure?.label || measure?.col || 'selected indicator';
  const unit = measure?.unit;
  const rows = result.rows.filter(r => r.value !== null);
  if (!rows.length) return `No computable ${measureLabel} value was found for the selected data slice.`;
  const top = rows[0];
  const tail = rows[rows.length - 1];
  const parts = [
    `The selected slice contains ${result.rowsAfterFilter.toLocaleString('en-IN')} records after applying ${result.filtersApplied.length} filter(s).`,
  ];
  if (request.analysis.type === 'comparison' && rows.length >= 2) {
    const diff = top.value != null && tail.value != null ? Math.abs(top.value - tail.value) : null;
    parts.push(`${labelOf(top)} records the highest ${measureLabel} at ${fmt(top.value, unit)}, compared with ${fmt(tail.value, unit)} for ${labelOf(tail)}${diff != null ? `, a difference of ${fmt(diff, unit)}` : ''}.`);
  } else if (request.analysis.type === 'ranking') {
    parts.push(`${labelOf(top)} ranks first for ${measureLabel} with ${fmt(top.value, unit)}.`);
  } else {
    parts.push(`${measureLabel} is reported at ${fmt(top.value, unit)} for ${labelOf(top)}.`);
  }
  return parts.join(' ').split(/\s+/).slice(0, maxWords).join(' ');
}

function tablePayload(request: ReportSectionRequest, result: SectionExecutionResult): Record<string, unknown> {
  return {
    type: request.analysis.type,
    questionId: request.requestId,
    items: result.rows,
    rows: result.rows,
    rankingData: result.rows,
    measure: result.measure?.label || result.measure?.col || 'Value',
    unit: result.measure?.unit,
    source: 'Frontend section workflow',
    provenance: provenancePayload(result),
  };
}

function provenancePayload(result: SectionExecutionResult): Record<string, unknown> {
  return {
    requestId: result.requestId,
    sliceSignature: result.sliceSignature,
    filtersApplied: result.filtersApplied,
    rowsScanned: result.rowsScanned,
    rowsAfterFilter: result.rowsAfterFilter,
    sourceColumns: [result.measure?.col, ...result.groupBy].filter(Boolean),
    warnings: result.warnings,
    marginOfError: result.marginOfError,
  };
}

function moeText(result: SectionExecutionResult): string {
  const moe = result.marginOfError;
  if (!moe) return '';
  if (!moe.valid) return moe.reason ? `Margin of error was not computed: ${moe.reason}.` : 'Margin of error was not computed.';
  return `Margin of error (${Math.round((moe.confidence || 0.95) * 100)}%): ±${fmt(moe.marginOfError ?? null, result.measure?.unit)}; interval ${fmt(moe.lower ?? null, result.measure?.unit)} to ${fmt(moe.upper ?? null, result.measure?.unit)}; quality ${moe.quality || 'not assessed'}.`;
}

function blockBase(request: ReportSectionRequest, component: SectionComponentConfig, sectionPath: string[], index: number): GeneratedSectionBlock {
  return {
    id: `sectiongen-${request.requestId}-${index}-${component.type}`.replace(/[^a-zA-Z0-9_-]+/g, '-'),
    index: -1,
    kind: component.type === 'chart' ? 'chart' : component.type === 'metric' ? 'metric' : component.type === 'key_finding' ? 'key_finding' : component.type === 'source_note' || component.type === 'caveat' ? 'source_note' : component.type === 'table' ? 'table' : 'narrative',
    title: component.title,
    content: '',
    sectionPath,
    status: 'done',
    pageIndex: 0,
  };
}

export function buildSectionBlocks(request: ReportSectionRequest, result: SectionExecutionResult): GeneratedSectionBlock[] {
  const chapter = request.target.chapter?.title || 'Generated Section';
  const section = request.target.section?.title || request.description.text || 'Generated Section';
  const sectionPath = [chapter, section];
  const enabled = (request.components || []).filter(c => c.enabled !== false);
  const blocks: GeneratedSectionBlock[] = [];
  enabled.forEach((component, idx) => {
    const block = blockBase(request, component, sectionPath, idx);
    if (component.type === 'narrative') {
      block.content = narrative(request, result, component.maxWords || 120);
    } else if (component.type === 'table') {
      block.tableData = tablePayload(request, result);
    } else if (component.type === 'chart') {
      block.tableData = { ...tablePayload(request, result), chartType: component.chartType || 'bar', x: component.x, y: component.y };
    } else if (component.type === 'metric') {
      const first = result.rows[0];
      block.metricValue = fmt(first?.value ?? null);
      block.metricUnit = result.measure?.unit || '';
      block.content = `${block.metricValue}${block.metricUnit ? ` ${block.metricUnit}` : ''}`;
    } else if (component.type === 'key_finding') {
      const first = result.rows[0];
      block.content = first ? `${labelOf(first)} records the leading ${result.measure?.label || result.measure?.col || 'value'} at ${fmt(first.value, result.measure?.unit)}.` : 'No key finding could be computed.';
    } else {
      const moe = moeText(result);
      const warnings = result.warnings.length ? result.warnings.map(w => w.message).join(' ') : '';
      block.content = [moe, warnings, `Filters applied: ${result.filtersApplied.join('; ')}`].filter(Boolean).join(' ');
    }
    blocks.push(block);
  });
  return blocks;
}
