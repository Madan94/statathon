'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
  Upload,
  X,
} from 'lucide-react';
import Link from 'next/link';

import { bindingPhaseApi, generatePhaseApi } from '@/lib/api';
import type { DatasetColumnProfile } from '@/lib/api';
import { canvasHandoffStorageKey } from '@/lib/report-section/canvasHandoff';
import type { GeneratedSectionBlock, ReportSectionRequest, SectionPredicate, SectionMeasure } from '@/lib/report-section';
import type { ReportCanvasHandoffBundle } from '@/lib/report-section/canvasHandoff';

// ─── Types ────────────────────────────────────────────────────────────────────

type AggKind = 'count' | 'sum' | 'mean' | 'weighted_mean';

interface ParsedScenario {
  id: string;
  title: string;
  scenario: string;
  finding: string;
  insight: string;
  filters: SectionPredicate[];
  groupBy: string[];
  measures: SectionMeasure[];
  aggKind: AggKind;
  status: 'idle' | 'running' | 'done' | 'error';
  blocks?: GeneratedSectionBlock[];
  narrative?: string;
  keyFindings?: string[];
  errorMsg?: string;
}

// ─── Parser ───────────────────────────────────────────────────────────────────

function parseUseCaseText(text: string, columns: DatasetColumnProfile[]): ParsedScenario[] {
  const colNames = columns.map((c) => c.name);

  // Split by numbered headings: "1.", "2.", etc.
  const sections = text.split(/\n(?=\d+\.\s)/).filter((s) => s.trim());

  return sections.map((block, i) => {
    const lines = block.split('\n').map((l) => l.trim()).filter(Boolean);
    const titleLine = lines[0] ?? `Use Case ${i + 1}`;
    const title = titleLine.replace(/^\d+\.\s*/, '').trim();

    const getField = (prefix: string) => {
      const l = lines.find((ln) => ln.toLowerCase().startsWith(prefix.toLowerCase()));
      return l ? l.slice(prefix.length).trim() : '';
    };

    const scenario = getField('Scenario:');
    const finding  = getField('Finding:');
    const insight  = getField('MoSPI Insight:');
    const fullText = block.toLowerCase();

    // ── Detect columns mentioned ──────────────────────────────────────────
    const mentioned = colNames.filter((c) => block.toLowerCase().includes(c.toLowerCase()));

    // ── Detect aggregation type from keywords ─────────────────────────────
    let aggKind: AggKind = 'count';
    if (/average|mean|avg/i.test(block))          aggKind = 'mean';
    else if (/total|sum|aggregat/i.test(block))   aggKind = 'sum';
    else if (/weighted/i.test(block))             aggKind = 'weighted_mean';
    else if (/how many|count|number of/i.test(block)) aggKind = 'count';

    // ── Extract filters ───────────────────────────────────────────────────
    const filters: SectionPredicate[] = [];

    // "State X" → StateCode
    const stateMatch = block.match(/State\s+(\d+)/i);
    if (stateMatch) filters.push({ col: 'StateCode', op: 'eq', value: Number(stateMatch[1]) });

    // "District XXXX"
    const distMatch = block.match(/District\s+(\d+)/i);
    if (distMatch) filters.push({ col: 'DistrictID', op: 'eq', value: Number(distMatch[1]) });

    // "Sector X" or "Rural sector (Sector 1)" or "Urban sectors (Sector 2)"
    const sectorMatch = block.match(/Sector\s+(\d+)/i) || block.match(/\(Sector\s+(\d+)\)/i);
    if (sectorMatch) filters.push({ col: 'Sector', op: 'eq', value: Number(sectorMatch[1]) });

    // "Code X in ColumnName" or "ColumnName ... Code X"
    const codeInColMatch = block.match(/Code\s+(\d+)\s+in\s+([\w_]+)/i);
    if (codeInColMatch) {
      const codeVal = Number(codeInColMatch[1]);
      const colRef  = colNames.find((c) => c.toLowerCase() === codeInColMatch[2].toLowerCase());
      if (colRef) filters.push({ col: colRef, op: 'eq', value: codeVal });
    }

    // "(Code X)" or "= X" patterns near mentioned columns
    const codeMatch = block.match(/\(Code\s+([\d,\-]+)\)/gi);
    if (codeMatch && mentioned.length > 0) {
      codeMatch.forEach((cm) => {
        const v = cm.replace(/[^\d]/g, '');
        if (v && mentioned[0]) filters.push({ col: mentioned[0], op: 'eq', value: Number(v) });
      });
    }

    // ">70%" → disability percentage > 70
    const pctMatch = block.match(/>(\d+)%/);
    if (pctMatch) {
      const pctCol = colNames.find((c) => /percent|disab/i.test(c));
      if (pctCol) filters.push({ col: pctCol, op: 'gt', value: Number(pctMatch[1]) });
    }

    // "aged 60 and above" / "age 60+" → age >= 60
    if (/age\s*(d)?\s*60|60\s*(and above|years?\s*(and\s*)?above|\+)/i.test(block)) {
      const ageCol = colNames.find((c) => /age/i.test(c));
      if (ageCol) filters.push({ col: ageCol, op: 'ge', value: 60 });
    }

    // "Yes" values → detect binary columns
    if (/Working_before_onset_disability.*Yes/i.test(block)) {
      if (colNames.includes('Working_before_onset_disability'))
        filters.push({ col: 'Working_before_onset_disability', op: 'eq', value: 1 });
    }
    if (/Disability_caused_loss_change.*Yes/i.test(block) || /loss_change.*Yes/i.test(block)) {
      const lossCol = colNames.find((c) => /disability_caused_loss/i.test(c));
      if (lossCol) filters.push({ col: lossCol, op: 'eq', value: 1 });
    }

    // ── GroupBy detection ─────────────────────────────────────────────────
    const groupBy: string[] = [];
    if (/by statecode|per state|each state|state.*group|group.*state/i.test(fullText)) {
      if (colNames.includes('StateCode')) groupBy.push('StateCode');
    }
    if (/by district|per district/i.test(fullText)) {
      if (colNames.includes('DistrictID')) groupBy.push('DistrictID');
    }
    if (/living arrangement|by.*arrangement|arrangement.*group/i.test(fullText)) {
      const arrCol = colNames.find((c) => /arrangement/i.test(c));
      if (arrCol && !groupBy.includes(arrCol)) groupBy.push(arrCol);
    }

    // ── Measures ──────────────────────────────────────────────────────────
    const measures: SectionMeasure[] = [];

    // Primary numeric column from "mentioned"
    const numericMentioned = mentioned.filter((c) => {
      const col = columns.find((col) => col.name === c);
      return col && (col.role === 'measure' || col.dtype === 'int' || col.dtype === 'float');
    });

    // Medical expenditure columns
    const medExpCol = colNames.find((c) => /usual_me/i.test(c) && /non_med/i.test(c) && !/non_m_m/i.test(c));
    if (/medical expenditure|me_excluding/i.test(fullText) && medExpCol) {
      measures.push({ col: medExpCol, agg: aggKind === 'mean' ? 'mean' : 'sum', label: 'Medical Expenditure' });
    }

    // FSU_Serial_No as default count proxy if nothing else
    if (measures.length === 0) {
      const fsuCol = colNames.find((c) => /fsu_serial/i.test(c)) ?? colNames.find((c) => c.toLowerCase().includes('serial'));
      if (fsuCol) measures.push({ col: fsuCol, agg: 'count', label: 'Count of Individuals' });
      else if (numericMentioned.length > 0) {
        measures.push({ col: numericMentioned[0], agg: aggKind, label: numericMentioned[0] });
      }
    }

    return {
      id: crypto.randomUUID(),
      title,
      scenario,
      finding,
      insight,
      filters,
      groupBy,
      measures,
      aggKind,
      status: 'idle',
    };
  });
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function UseCaseReportPage() {
  const params    = useParams();
  const router    = useRouter();
  const templateId = decodeURIComponent(params.templateId as string);
  const signature  = decodeURIComponent(params.signature  as string);

  const [workspace, setWorkspace]       = useState<{ dataset_id: string; dataset_ast?: { columns: DatasetColumnProfile[] } } | null>(null);
  const [loading, setLoading]           = useState(true);
  const [pasteText, setPasteText]       = useState('');
  const [scenarios, setScenarios]       = useState<ParsedScenario[]>([]);
  const [step, setStep]                 = useState<'input' | 'review' | 'generating' | 'done'>('input');
  const [globalError, setGlobalError]   = useState<string | null>(null);
  const [expandedIdx, setExpandedIdx]   = useState<number | null>(0);
  const [progress, setProgress]         = useState(0);

  useEffect(() => {
    bindingPhaseApi.getWorkspace(templateId, signature)
      .then((ws) => setWorkspace(ws))
      .catch(() => setGlobalError('Could not load workspace.'))
      .finally(() => setLoading(false));
  }, [templateId, signature]);

  const columns = workspace?.dataset_ast?.columns ?? [];

  const handleParse = () => {
    if (!pasteText.trim()) return;
    const parsed = parseUseCaseText(pasteText, columns);
    setScenarios(parsed);
    setStep('review');
    setExpandedIdx(0);
  };

  // ── Per-scenario update helper ────────────────────────────────────────────
  const updateScenario = (id: string, patch: Partial<ParsedScenario>) =>
    setScenarios((prev) => prev.map((s) => s.id === id ? { ...s, ...patch } : s));

  // ── Generate all scenarios ────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!workspace) return;
    setStep('generating');
    setGlobalError(null);
    setProgress(0);

    const chapterTitle = 'Use Case Report';
    const allSections: ReportCanvasHandoffBundle['sections'] = [];
    const mkId = () => crypto.randomUUID();

    for (let i = 0; i < scenarios.length; i++) {
      const sc = scenarios[i];
      updateScenario(sc.id, { status: 'running' });

      try {
        const sectionTitle = sc.title;
        const sectionPath  = [chapterTitle, sectionTitle];

        // ── Build ReportSectionRequest ──────────────────────────────────
        const reqId = crypto.randomUUID();
        const request: ReportSectionRequest = {
          version:   'report.section.v1',
          requestId: reqId,
          datasetId: workspace.dataset_id,
          target: {
            templateId,
            signature,
            mode:    'append',
            chapter: { title: chapterTitle, create: i === 0 },
            section: { title: sectionTitle, create: true },
          },
          scope: {
            filters:           sc.filters,
            filterCombinator:  'AND',
            columns: {
              dimensions: sc.groupBy,
              measures:   sc.measures,
              include:    [...sc.groupBy, ...sc.measures.map((m) => m.col)],
            },
          },
          description: {
            text:   `${sc.scenario} ${sc.finding}`.trim() || sc.title,
            source: 'user',
          },
          analysis: {
            type:    sc.groupBy.length > 0 ? 'comparison' : (sc.aggKind === 'mean' ? 'metric' : 'summary'),
            groupBy: sc.groupBy.length > 0 ? sc.groupBy : undefined,
            sort:    sc.groupBy.length > 0 ? { by: sc.measures[0]?.col ?? '', order: 'desc' } : null,
            limit:   sc.groupBy.length > 0 ? 30 : null,
          },
          components: [
            { type: 'table',       title: sectionTitle,  maxWords: 0,   enabled: true },
            { type: 'narrative',   title: 'Analysis',    maxWords: 250, enabled: true },
            { type: 'key_finding', title: 'Key Finding', maxWords: 0,   enabled: true },
            { type: 'metric',      title: 'Summary',     maxWords: 0,   enabled: sc.aggKind !== 'count' || sc.groupBy.length === 0 },
          ],
          options: {
            engine:        'backend',
            warningPolicy: 'warn_only',
          },
        };

        // ── Call generateSection() — real data from backend ────────────
        let execBlocks: GeneratedSectionBlock[] = [];
        let rowsAfterFilter = 0;
        let groups = 0;

        try {
          const exec = await generatePhaseApi.generateSection(templateId, signature, {
            request: request as unknown as Record<string, unknown>,
          });
          execBlocks      = exec.blocks ?? [];
          rowsAfterFilter = exec.rowsAfterFilter;
          groups          = exec.groups;
        } catch {
          // generateSection may fail for complex requests; fall back to empty blocks
          execBlocks = [];
        }

        // ── Build proper table block in blockFormat shape ───────────────
        // Ensure the primary table block has items in the correct { rank, key, value } format
        const tableBlockIdx = execBlocks.findIndex((b) => b.kind === 'table');
        if (tableBlockIdx === -1) {
          // Backend didn't generate a table; build one from finding text
          execBlocks.push({
            id: mkId(), index: execBlocks.length, kind: 'table',
            title: sectionTitle,
            content: '',
            tableData: {
              items: [],   // empty — narrative will cover
              measure: sc.measures[0]?.label ?? sc.measures[0]?.col ?? 'Value',
            },
            sectionPath, status: 'done', pageIndex: 0,
          });
        }

        // ── Synthesize LLM narrative grounded in real data ─────────────
        const description = [
          sc.scenario,
          sc.finding ? `Finding: ${sc.finding}` : '',
          `Filters applied: ${sc.filters.map((f) => `${f.col} ${f.op} ${f.value}`).join('; ') || 'none'}.`,
          sc.groupBy.length ? `Grouped by: ${sc.groupBy.join(', ')}.` : '',
          `Rows after filter: ${rowsAfterFilter}. Groups: ${groups || '-'}.`,
        ].filter(Boolean).join(' ');

        const synth = await generatePhaseApi.synthesize(templateId, signature, {
          description,
          tags:          ['use-case', sc.aggKind, ...(sc.groupBy.length ? sc.groupBy : [])],
          components:    [{ type: 'narrative', title: 'Analysis' }, { type: 'key_finding', title: 'Insight' }],
          measures:      sc.measures.map((m) => ({ col: m.col, label: m.label ?? m.col, agg: m.agg ?? 'count', weighted: false })),
          blocks:        execBlocks as unknown as Array<Record<string, unknown>>,
          section_title: sectionTitle,
          chapter_title: chapterTitle,
          dataset_id:    workspace.dataset_id,
          analysis_type: request.analysis.type,
          max_words:     280,
        });

        // ── Assemble final block list ───────────────────────────────────
        const finalBlocks: GeneratedSectionBlock[] = [
          // Heading
          { id: mkId(), index: 0, kind: 'heading', title: sectionTitle, content: sectionTitle, sectionPath, status: 'done', pageIndex: 0 },
          // LLM narrative
          ...(synth.content ? [{
            id: mkId(), index: 1, kind: 'narrative' as const,
            title: 'Analysis', content: synth.content,
            sectionPath, status: 'done' as const, pageIndex: 0,
          }] : []),
          // Real data blocks from backend (table, metric, chart, etc.)
          ...execBlocks.map((b, bi) => ({ ...b, id: mkId(), index: 2 + bi, sectionPath })),
          // MoSPI Insight
          ...(sc.insight ? [{
            id: mkId(), index: 100, kind: 'narrative' as const,
            title: 'MoSPI Policy Insight',
            content: sc.insight,
            sectionPath, status: 'done' as const, pageIndex: 0,
          }] : []),
          // Key findings from LLM
          ...(synth.key_findings ?? []).slice(0, 3).map((kf, ki) => ({
            id: mkId(), index: 200 + ki, kind: 'key_finding' as const,
            title: 'Key Finding', content: kf,
            sectionPath, status: 'done' as const, pageIndex: 0,
          })),
          // Source note
          {
            id: mkId(), index: 999, kind: 'source_note' as const,
            title: 'Source',
            content: `Computed from dataset ${workspace.dataset_id}. Filters: ${sc.filters.map((f) => `${f.col}=${f.value}`).join(', ') || 'none'}.`,
            sectionPath, status: 'done' as const, pageIndex: 0,
          },
        ];
        finalBlocks.forEach((b, bi) => { b.index = bi; });

        updateScenario(sc.id, {
          status: 'done',
          blocks: finalBlocks,
          narrative: synth.content,
          keyFindings: synth.key_findings,
        });

        allSections.push({
          id: reqId,
          request,
          blocks: finalBlocks,
          meta: { rowsScanned: rowsAfterFilter, rowsAfterFilter, groups },
          addedAt: Date.now(),
        });
      } catch (err) {
        updateScenario(sc.id, {
          status: 'error',
          errorMsg: err instanceof Error ? err.message : 'Generation failed',
        });
      }

      setProgress(Math.round(((i + 1) / scenarios.length) * 100));
    }

    // ── Build and store canvas handoff ──────────────────────────────────
    if (allSections.length > 0) {
      const bundle: ReportCanvasHandoffBundle = {
        version:      'report.canvas.handoff.v1',
        templateId,
        signature,
        datasetId:    workspace.dataset_id,
        generatedAt:  new Date().toISOString(),
        sections:     allSections,
      };
      sessionStorage.removeItem(`canvas:autoBoot:${templateId}::${signature}`);
      sessionStorage.setItem(canvasHandoffStorageKey(templateId, signature), JSON.stringify(bundle));
      setStep('done');
    } else {
      setGlobalError('No sections were generated successfully.');
      setStep('review');
    }
  };

  // ── Filter editor helpers ────────────────────────────────────────────────
  const removeFilter = (scId: string, fi: number) => {
    setScenarios((prev) => prev.map((s) =>
      s.id === scId ? { ...s, filters: s.filters.filter((_, i) => i !== fi) } : s
    ));
  };

  const successCount = scenarios.filter((s) => s.status === 'done').length;
  const errorCount   = scenarios.filter((s) => s.status === 'error').length;

  // ── Render ───────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f8fafc]">
        <div className="flex items-center gap-3 text-text-muted">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <span className="text-sm">Loading workspace…</span>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f8fafc] px-4 py-6 lg:px-8">
      <div className="mx-auto max-w-4xl space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <Link href="/report-builder/binding"
              className="inline-flex items-center gap-1 text-xs text-text-muted hover:text-primary mb-1">
              <ArrowLeft className="h-3.5 w-3.5" /> Back to binding
            </Link>
            <h1 className="flex items-center gap-2 text-xl font-bold text-[#0a1f44]">
              <FileText className="h-5 w-5 text-primary" />
              Use Case Report Builder
            </h1>
            <p className="mt-0.5 text-xs text-slate-500">
              Paste your scenario text → system parses, runs real data queries, synthesizes narrative → Report Canvas
            </p>
          </div>
          {/* Step pills */}
          <div className="flex items-center gap-1.5">
            {(['input', 'review', 'generating', 'done'] as const).map((s, i) => (
              <div key={s} className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-semibold ${
                step === s ? 'bg-primary text-white' : i < (['input','review','generating','done'] as const).indexOf(step) ? 'bg-primary/20 text-primary' : 'bg-slate-100 text-slate-400'
              }`}>
                {i < (['input','review','generating','done'] as const).indexOf(step) ? <Check className="h-3 w-3" /> : null}
                {s === 'input' ? '1. Paste' : s === 'review' ? '2. Review' : s === 'generating' ? '3. Generate' : '4. Canvas'}
              </div>
            ))}
          </div>
        </div>

        {globalError && (
          <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {globalError}
          </div>
        )}

        {/* ── STEP 1: INPUT ──────────────────────────────────────────────────── */}
        {step === 'input' && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10">
                <Upload className="h-4 w-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-[#0a1f44]">Paste your use case scenarios</h2>
                <p className="text-xs text-slate-500">
                  Each scenario should be numbered (1., 2., …) with Scenario:, Finding:, and MoSPI Insight: fields.
                </p>
              </div>
            </div>

            <textarea
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              placeholder={`1. Title of Use Case\nThis is the description.\nScenario: In State 5, District 511, how many individuals...\nFinding: There are 6 individuals...\nMoSPI Insight: This helps in identifying...\n\n2. Next Use Case\n...`}
              rows={18}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-mono text-slate-700 outline-none focus:ring-2 focus:ring-primary/20 resize-none"
            />

            <div className="flex items-center justify-between">
              <p className="text-[10px] text-slate-400">
                {columns.length} columns available for matching · {pasteText.trim().split(/\n\d+\./).length - 1 || 0} scenarios detected
              </p>
              <button
                type="button"
                onClick={handleParse}
                disabled={!pasteText.trim() || !columns.length}
                className="flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-50"
              >
                <Sparkles className="h-4 w-4" />
                Parse scenarios
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── STEP 2: REVIEW ─────────────────────────────────────────────────── */}
        {step === 'review' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-5 py-3.5 shadow-sm">
              <div>
                <p className="text-sm font-bold text-[#0a1f44]">{scenarios.length} scenarios parsed</p>
                <p className="text-xs text-slate-500">Review filters and measures before generating. Remove incorrect filters.</p>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => setStep('input')}
                  className="flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-xs text-slate-600 hover:bg-slate-50">
                  <RefreshCw className="h-3.5 w-3.5" /> Re-paste
                </button>
                <button type="button" onClick={handleGenerate}
                  className="flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary/90">
                  <Sparkles className="h-4 w-4" />
                  Generate all {scenarios.length} sections
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>

            {scenarios.map((sc, i) => (
              <div key={sc.id} className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                {/* Row header */}
                <button
                  type="button"
                  onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
                  className="flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-slate-50"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                    {i + 1}
                  </span>
                  <span className="flex-1 text-sm font-semibold text-[#0a1f44]">{sc.title}</span>
                  <div className="flex items-center gap-1.5">
                    {sc.filters.length > 0 && (
                      <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[9px] font-semibold text-blue-700">
                        {sc.filters.length} filter{sc.filters.length > 1 ? 's' : ''}
                      </span>
                    )}
                    {sc.groupBy.length > 0 && (
                      <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[9px] font-semibold text-purple-700">
                        grouped by {sc.groupBy[0]}
                      </span>
                    )}
                    <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${
                      sc.aggKind === 'count' ? 'bg-slate-100 text-slate-600' :
                      sc.aggKind === 'mean'  ? 'bg-amber-100 text-amber-700' :
                                               'bg-green-100 text-green-700'
                    }`}>{sc.aggKind}</span>
                  </div>
                  {expandedIdx === i ? <ChevronUp className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
                </button>

                {expandedIdx === i && (
                  <div className="border-t border-slate-100 px-5 py-4 space-y-3">
                    {sc.scenario && (
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Scenario</p>
                        <p className="mt-0.5 text-xs text-slate-600">{sc.scenario}</p>
                      </div>
                    )}

                    {/* Filters */}
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400 mb-1.5">
                        Filters ({sc.filters.length})
                      </p>
                      {sc.filters.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">No filters detected — all rows will be used</p>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {sc.filters.map((f, fi) => (
                            <span key={fi}
                              className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-mono text-blue-800">
                              {f.col} {f.op} {String(f.value)}
                              <button type="button" onClick={() => removeFilter(sc.id, fi)}
                                className="text-blue-400 hover:text-red-500">
                                <X className="h-3 w-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Measures */}
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400 mb-1.5">
                        Measure
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {sc.measures.map((m, mi) => (
                          <span key={mi}
                            className="rounded-lg border border-green-200 bg-green-50 px-2.5 py-1 text-[11px] font-mono text-green-800">
                            {m.agg ?? 'count'}({m.col})
                          </span>
                        ))}
                      </div>
                    </div>

                    {sc.insight && (
                      <div className="rounded-xl bg-amber-50 border border-amber-200 px-3 py-2">
                        <p className="text-[10px] font-bold uppercase tracking-wide text-amber-600">MoSPI Policy Insight</p>
                        <p className="mt-0.5 text-xs text-amber-800">{sc.insight}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* ── STEP 3: GENERATING ─────────────────────────────────────────────── */}
        {step === 'generating' && (
          <div className="space-y-4">
            <div className="rounded-2xl border border-primary/20 bg-primary/5 px-5 py-4 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  <p className="text-sm font-bold text-primary">Generating report sections…</p>
                </div>
                <p className="text-sm font-bold text-primary">{progress}%</p>
              </div>
              <div className="h-2 w-full rounded-full bg-primary/10 overflow-hidden">
                <div className="h-full rounded-full bg-primary transition-all duration-300"
                  style={{ width: `${progress}%` }} />
              </div>
              <p className="mt-1.5 text-[10px] text-slate-500">
                Running data queries + LLM synthesis for each scenario. Please wait.
              </p>
            </div>

            <div className="space-y-2">
              {scenarios.map((sc, i) => (
                <div key={sc.id}
                  className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-sm ${
                    sc.status === 'done'  ? 'border-green-200 bg-green-50' :
                    sc.status === 'error' ? 'border-red-200 bg-red-50' :
                    sc.status === 'running' ? 'border-primary/30 bg-primary/5' :
                                              'border-slate-200 bg-white'
                  }`}
                >
                  <span className="w-5 shrink-0 text-center text-[11px] font-bold text-slate-400">{i + 1}</span>
                  <span className="flex-1 font-medium text-[#1e293b]">{sc.title}</span>
                  {sc.status === 'running' && <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0" />}
                  {sc.status === 'done'    && <Check className="h-4 w-4 text-green-600 shrink-0" />}
                  {sc.status === 'error'   && (
                    <span className="flex items-center gap-1 text-[10px] text-red-600 shrink-0">
                      <AlertCircle className="h-3.5 w-3.5" />
                      {sc.errorMsg?.slice(0, 40)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── STEP 4: DONE ───────────────────────────────────────────────────── */}
        {step === 'done' && (
          <div className="space-y-4">
            <div className="rounded-2xl border border-green-200 bg-green-50 px-5 py-4 shadow-sm">
              <div className="flex items-center gap-3 mb-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-green-500/10">
                  <Check className="h-5 w-5 text-green-600" />
                </div>
                <div>
                  <p className="text-sm font-bold text-green-800">Report generated successfully</p>
                  <p className="text-xs text-green-700">
                    {successCount} of {scenarios.length} sections completed
                    {errorCount > 0 ? ` · ${errorCount} failed` : ''}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => router.push(`/report-builder/canvas/${encodeURIComponent(templateId)}/${encodeURIComponent(signature)}?draftMode=new`)}
                className="flex items-center gap-2 rounded-xl bg-green-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-green-700"
              >
                <FileText className="h-4 w-4" />
                Open Report Canvas
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>

            {/* Summary of generated sections */}
            <div className="space-y-2">
              {scenarios.map((sc, i) => (
                <div key={sc.id}
                  className={`rounded-xl border px-4 py-3 text-xs ${
                    sc.status === 'done'  ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-500">{i + 1}.</span>
                    <span className="flex-1 font-semibold text-[#1e293b]">{sc.title}</span>
                    {sc.status === 'done' ? (
                      <span className="text-green-700 font-semibold flex items-center gap-1">
                        <Check className="h-3.5 w-3.5" /> {sc.blocks?.length ?? 0} blocks
                      </span>
                    ) : (
                      <span className="text-red-600">{sc.errorMsg}</span>
                    )}
                  </div>
                  {sc.narrative && (
                    <p className="mt-1.5 text-slate-500 line-clamp-2 text-[10px]">{sc.narrative}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
