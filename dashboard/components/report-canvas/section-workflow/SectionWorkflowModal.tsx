'use client';

import { useMemo, useState } from 'react';
import {
  buildComponentSuggestions,
  buildDescriptionSuggestions,
  buildSectionBlocks,
  executeWithSliceCache,
  parseRowsInput,
  reportSectionDatasetStore,
  validateSectionRequest,
  type GeneratedSectionBlock,
  type ReportSectionRequest,
  type SectionComponentConfig,
  type SectionIssue,
} from '@/lib/report-section';

interface Props {
  templateId: string;
  signature: string;
  onClose: () => void;
  onAppendBlocks: (blocks: GeneratedSectionBlock[], request: ReportSectionRequest) => void;
}

function defaultRequest(templateId: string, signature: string): ReportSectionRequest {
  return {
    version: 'report.section.v1',
    requestId: `req_${Date.now()}`,
    datasetId: 'employment_2023',
    target: {
      templateId,
      signature,
      mode: 'append',
      chapter: { id: 'ch_state_comparison', title: 'State Comparison', create: true },
      section: { id: 'sec_generated_section', title: 'Generated Section', create: true },
      insertAfterBlockId: null,
    },
    scope: {
      filters: [
        { col: 'Gender', op: 'eq', value: 'Male', required: true },
        { col: 'State', op: 'in', value: ['Tamil Nadu', 'Karnataka'], required: true },
        { col: 'Year', op: 'eq', value: 2023, required: true },
      ],
      columns: {
        dimensions: ['State'],
        measures: [{ col: 'EmploymentRate', label: 'Employment Rate', agg: 'reported_value', unit: '%' }],
        time: 'Year',
        include: ['Gender', 'State', 'Year', 'EmploymentRate'],
      },
    },
    description: { text: 'Compare male employment rate for Tamil Nadu and Karnataka in 2023.', source: 'user' },
    analysis: { type: 'comparison', groupBy: ['State'], sort: { by: 'EmploymentRate', order: 'desc' } },
    components: [
      { type: 'narrative', title: 'Comparative Summary', maxWords: 120 },
      { type: 'table', title: 'Male Employment Rate by State, 2023' },
      { type: 'chart', title: 'Male Employment Rate, 2023', chartType: 'bar', x: 'State', y: 'EmploymentRate' },
    ],
    options: { engine: 'local', cache: true, verify: true, requireEvidence: true, warningPolicy: 'acknowledge_before_append' },
  };
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function parseRequest(text: string): ReportSectionRequest | null {
  try {
    const parsed = JSON.parse(text) as ReportSectionRequest;
    if (parsed?.version !== 'report.section.v1') return null;
    return parsed;
  } catch {
    return null;
  }
}

function issueBadge(issue: SectionIssue) {
  const color = issue.severity === 'error' ? 'bg-red-50 text-red-700 border-red-200' : issue.severity === 'warn' ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-slate-50 text-slate-600 border-slate-200';
  return <span key={`${issue.code}-${issue.column || ''}-${issue.message}`} className={`rounded border px-2 py-1 text-[11px] ${color}`}>{issue.code}: {issue.message}</span>;
}

export function SectionWorkflowModal({ templateId, signature, onClose, onAppendBlocks }: Props) {
  const [requestText, setRequestText] = useState(() => prettyJson(defaultRequest(templateId, signature)));
  const [datasetText, setDatasetText] = useState('');
  const [previewBlocks, setPreviewBlocks] = useState<GeneratedSectionBlock[]>([]);
  const [previewIssues, setPreviewIssues] = useState<SectionIssue[]>([]);
  const [ackWarnings, setAckWarnings] = useState(false);
  const [message, setMessage] = useState('');

  const request = useMemo(() => parseRequest(requestText), [requestText]);
  const snapshot = request ? reportSectionDatasetStore.getSnapshot(request.datasetId) : null;
  const validation = useMemo(() => request ? validateSectionRequest(request, snapshot) : null, [request, snapshot]);
  const descriptionSuggestions = useMemo(() => request ? buildDescriptionSuggestions(request) : [], [request]);
  const componentSuggestions = useMemo(() => request ? buildComponentSuggestions(request) : [], [request]);
  const allIssues = [...(validation?.issues || []), ...previewIssues];
  const hasWarnings = allIssues.some(i => i.severity !== 'info');
  const hasErrors = allIssues.some(i => i.severity === 'error') || validation?.status === 'cannot_compute';

  const updateRequest = (patch: (req: ReportSectionRequest) => ReportSectionRequest) => {
    if (!request) return;
    setRequestText(prettyJson(patch(request)));
    setPreviewBlocks([]);
    setPreviewIssues([]);
    setAckWarnings(false);
  };

  const loadDataset = () => {
    if (!request) { setMessage('Fix request JSON before loading data.'); return; }
    try {
      const rows = parseRowsInput(datasetText);
      if (!rows.length) { setMessage('Dataset input did not contain rows. Paste JSON array or CSV.'); return; }
      const snap = reportSectionDatasetStore.registerRows(request.datasetId, rows);
      setMessage(`Loaded ${snap.rowCount.toLocaleString('en-IN')} rows for ${snap.datasetId}.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to parse dataset rows.');
    }
  };

  const applySuggestion = (index: number) => {
    const suggestion = descriptionSuggestions[index];
    if (!suggestion) return;
    updateRequest(req => ({
      ...req,
      description: { text: suggestion.description, source: 'suggested' },
      analysis: { ...req.analysis, ...suggestion.analysisPatch },
      components: suggestion.recommendedComponents,
    }));
  };

  const addComponent = (component: SectionComponentConfig) => {
    updateRequest(req => ({ ...req, components: [...req.components, component] }));
  };

  const removeComponent = (idx: number) => {
    updateRequest(req => ({ ...req, components: req.components.filter((_, i) => i !== idx) }));
  };

  const generatePreview = () => {
    if (!request) { setMessage('Request JSON is invalid.'); return; }
    const snap = reportSectionDatasetStore.getSnapshot(request.datasetId);
    const result = validateSectionRequest(request, snap);
    if (result.status === 'cannot_compute') {
      setPreviewIssues(result.issues);
      setMessage('Request cannot compute yet. Fix errors first.');
      return;
    }
    const rows = reportSectionDatasetStore.getRows(request.datasetId);
    const execution = executeWithSliceCache(request, rows);
    const blocks = buildSectionBlocks(request, execution);
    setPreviewBlocks(blocks);
    setPreviewIssues([...result.issues, ...execution.warnings]);
    setAckWarnings(false);
    setMessage(`Preview built: ${blocks.length} block(s), ${execution.rowsAfterFilter.toLocaleString('en-IN')} rows after filtering.`);
  };

  const append = () => {
    if (!request || !previewBlocks.length) return;
    if (hasWarnings && !ackWarnings) {
      setMessage('Acknowledge warnings before appending.');
      return;
    }
    onAppendBlocks(previewBlocks, request);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4">
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Generate report section</h2>
            <p className="text-xs text-slate-500">Local MVP: JSON scope + frontend-cached dataset + draft append.</p>
          </div>
          <button onClick={onClose} className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100">Close</button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-hidden lg:grid-cols-[1.1fr_0.9fr]">
          <div className="min-h-0 overflow-auto border-r border-slate-200 p-4">
            <label className="mb-1 block text-xs font-semibold text-slate-700">Section request JSON</label>
            <textarea value={requestText} onChange={e => setRequestText(e.target.value)} className="h-64 w-full rounded border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] text-slate-800 outline-none focus:border-blue-400" />

            <div className="mt-4">
              <label className="mb-1 block text-xs font-semibold text-slate-700">Preprocessed dataset rows for this datasetId</label>
              <textarea value={datasetText} onChange={e => setDatasetText(e.target.value)} placeholder="Paste JSON array of rows or simple CSV for demo." className="h-32 w-full rounded border border-slate-200 p-3 font-mono text-[11px] outline-none focus:border-blue-400" />
              <div className="mt-2 flex items-center gap-2">
                <button onClick={loadDataset} className="rounded bg-slate-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-900">Load dataset cache</button>
                <span className="text-xs text-slate-500">{snapshot ? `${snapshot.rowCount.toLocaleString('en-IN')} rows cached for ${snapshot.datasetId}` : 'No cached rows yet'}</span>
              </div>
            </div>

            {message && <p className="mt-3 rounded bg-blue-50 px-3 py-2 text-xs text-blue-700">{message}</p>}
          </div>

          <div className="min-h-0 overflow-auto p-4">
            <div className="space-y-4">
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Validation</h3>
                <div className="mt-2 flex flex-wrap gap-2">
                  {!request && <span className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700">Invalid request JSON</span>}
                  {request && validation?.issues.length === 0 && <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700">Ready</span>}
                  {allIssues.map(issueBadge)}
                </div>
              </section>

              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Description suggestions</h3>
                <div className="mt-2 space-y-2">
                  {descriptionSuggestions.map((s, i) => (
                    <button key={s.suggestionId} onClick={() => applySuggestion(i)} className="block w-full rounded border border-slate-200 p-2 text-left hover:border-blue-300 hover:bg-blue-50">
                      <p className="text-xs font-semibold text-slate-800">{s.label}</p>
                      <p className="text-xs text-slate-600">{s.description}</p>
                      <p className="mt-1 text-[10px] text-slate-400">{s.reason}</p>
                    </button>
                  ))}
                </div>
              </section>

              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected components</h3>
                <div className="mt-2 space-y-2">
                  {request?.components.map((c, i) => (
                    <div key={`${c.type}-${i}`} className="flex items-center justify-between rounded border border-slate-200 px-2 py-1.5">
                      <span className="text-xs text-slate-700">{c.type}: {c.title}</span>
                      <button onClick={() => removeComponent(i)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {componentSuggestions.map((s, i) => (
                    <button key={`${s.component.type}-${i}`} onClick={() => addComponent(s.component)} className="rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50">Add {s.component.type}</button>
                  ))}
                </div>
              </section>

              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Preview</h3>
                <div className="mt-2 flex items-center gap-2">
                  <button onClick={generatePreview} disabled={!request || hasErrors} className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300">Build preview</button>
                  {hasWarnings && (
                    <label className="flex items-center gap-1 text-xs text-amber-700">
                      <input type="checkbox" checked={ackWarnings} onChange={e => setAckWarnings(e.target.checked)} /> Acknowledge warnings
                    </label>
                  )}
                </div>
                <div className="mt-2 space-y-1">
                  {previewBlocks.map(b => <div key={b.id} className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-700">{b.kind}: {b.title}</div>)}
                </div>
              </section>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
          <p className="text-xs text-slate-500">Preview is read-only. Edit content after appending to the canvas.</p>
          <button onClick={append} disabled={!previewBlocks.length || (hasWarnings && !ackWarnings)} className="rounded bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300">Append to draft canvas</button>
        </div>
      </div>
    </div>
  );
}
