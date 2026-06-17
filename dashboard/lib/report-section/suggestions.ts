import type { ComponentSuggestion, DescriptionSuggestion, ReportSectionRequest, SectionComponentConfig } from './types';

function measureLabel(request: ReportSectionRequest): string {
  const m = request.scope.columns.measures[0];
  return m?.label || m?.col || 'selected indicator';
}

function filterPhrase(request: ReportSectionRequest): string {
  const parts = request.scope.filters.map(f => `${f.col} ${Array.isArray(f.value) ? f.value.join(', ') : String(f.value ?? '')}`);
  return parts.length ? ` for ${parts.join('; ')}` : '';
}

function baseComponents(type: ReportSectionRequest['analysis']['type'], request: ReportSectionRequest): SectionComponentConfig[] {
  const measure = request.scope.columns.measures[0];
  const group = (request.analysis.groupBy || request.scope.columns.dimensions)[0];
  if (type === 'trend') return [
    { type: 'narrative', title: 'Trend Summary', maxWords: 140 },
    { type: 'chart', title: `${measureLabel(request)} Trend`, chartType: 'line', x: request.scope.columns.time || group, y: measure?.col },
    { type: 'table', title: `${measureLabel(request)} Trend Table` },
  ];
  if (type === 'ranking') return [
    { type: 'key_finding', title: 'Key Finding' },
    { type: 'table', title: `${measureLabel(request)} Ranking` },
    { type: 'chart', title: `${measureLabel(request)} Ranking`, chartType: 'bar', x: group, y: measure?.col },
  ];
  if (type === 'comparison') return [
    { type: 'narrative', title: 'Comparative Summary', maxWords: 120 },
    { type: 'table', title: `${measureLabel(request)} Comparison` },
    { type: 'chart', title: `${measureLabel(request)} Comparison`, chartType: 'bar', x: group, y: measure?.col },
  ];
  return [
    { type: 'narrative', title: 'Summary', maxWords: 150 },
    { type: 'table', title: `${measureLabel(request)} Table` },
    { type: 'source_note', title: 'Source Note' },
  ];
}

export function buildDescriptionSuggestions(request: ReportSectionRequest): DescriptionSuggestion[] {
  const m = measureLabel(request);
  const dims = request.scope.columns.dimensions;
  const time = request.scope.columns.time;
  const suffix = filterPhrase(request);
  const out: DescriptionSuggestion[] = [];

  out.push({
    suggestionId: 'summary',
    label: 'Generate summary',
    description: `Generate a concise MoSPI-style summary of ${m}${suffix}.`,
    analysisPatch: { type: 'summary', groupBy: dims.length ? dims : request.analysis.groupBy },
    recommendedComponents: baseComponents('summary', request),
    reason: 'A summary is suitable for any selected data slice.',
  });
  if (dims.length) {
    out.push({
      suggestionId: 'comparison',
      label: 'Compare selected groups',
      description: `Compare ${m} by ${dims[0]}${suffix}.`,
      analysisPatch: { type: 'comparison', groupBy: [dims[0]], sort: { by: request.scope.columns.measures[0]?.col || m, order: 'desc' } },
      recommendedComponents: baseComponents('comparison', request),
      reason: 'One selected dimension can be compared clearly in a table and bar chart.',
    });
    out.push({
      suggestionId: 'ranking',
      label: 'Rank selected values',
      description: `Rank ${dims[0]} categories by ${m}${suffix}.`,
      analysisPatch: { type: 'ranking', groupBy: [dims[0]], sort: { by: request.scope.columns.measures[0]?.col || m, order: 'desc' } },
      recommendedComponents: baseComponents('ranking', request),
      reason: 'Ranking is useful when the selected dimension has multiple categories.',
    });
  }
  if (time) {
    out.push({
      suggestionId: 'trend',
      label: 'Show trend',
      description: `Show the trend of ${m} over ${time}${suffix}.`,
      analysisPatch: { type: 'trend', groupBy: [time] },
      recommendedComponents: baseComponents('trend', request),
      reason: 'A time column is available, so a trend chart can be generated.',
    });
  }
  return out.slice(0, 4);
}

export function buildComponentSuggestions(request: ReportSectionRequest): ComponentSuggestion[] {
  const recommended = baseComponents(request.analysis.type, request);
  if (request.scope.columns.measures.some(m => m.moe?.enabled)) {
    recommended.push({ type: 'caveat', title: 'Margin of Error Note' });
  }
  const existing = new Set((request.components || []).map(c => c.type));
  return recommended.map(component => ({
    component,
    recommended: !existing.has(component.type),
    reason: `${component.type} is suitable for a ${request.analysis.type} analysis.`,
  }));
}
