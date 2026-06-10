'use client';

/**
 * R4 — customization panel. Edits a sparse `ReportOverrides` (theme, number
 * system, locale, front/back matter, section order, included questions and
 * per-question chart type) and reports changes up so the live preview re-shapes
 * instantly via `applyProfile`; "Save" persists the overrides server-side.
 */
import { useMemo } from 'react';
import { Loader2, Save } from 'lucide-react';

import type { ReportAST } from '@/lib/report/types';
import {
  elementQuestionMap,
  type ReportOverrides,
} from '@/lib/report/profile';
import { loc } from '@/lib/report/format';
import { Button } from '@/components/ui/Button';
import { SectionReorder, type ReorderItem } from './SectionReorder';

const THEMES: Array<[string, string]> = [
  ['mospi_navy', 'MoSPI Navy'],
  ['mospi_saffron', 'MoSPI Saffron'],
  ['neutral_grey', 'Neutral Grey'],
];

const CHART_TYPES = ['simple_bar', 'grouped_bar', 'stacked_bar', 'line', 'pie', 'donut'];

interface Props {
  report: ReportAST;
  value: ReportOverrides;
  onChange: (next: ReportOverrides) => void;
  onSave: () => void;
  saving?: boolean;
}

export function CustomizePanel({ report, value, onChange, onSave, saving }: Props) {
  const sections = report.semanticAST?.sections ?? [];

  const sectionItems = useMemo<ReorderItem[]>(() => {
    const byId = new Map(sections.map((s) => [s.sectionId ?? '', s]));
    const ordered = value.sectionOrder?.length
      ? [
          ...value.sectionOrder.filter((id) => byId.has(id)),
          ...sections.map((s) => s.sectionId ?? '').filter((id) => !value.sectionOrder!.includes(id)),
        ]
      : sections.map((s) => s.sectionId ?? '');
    return ordered
      .filter(Boolean)
      .map((id) => ({ id, label: loc(byId.get(id)?.title) || id }));
  }, [sections, value.sectionOrder]);

  const { questions, qLabel } = useMemo(() => {
    const label = new Map<string, string>();
    for (const c of report.chartAST?.charts ?? []) {
      const q = c.provenance?.questionId ?? c.biQuery;
      if (q && !label.has(q)) label.set(q, loc(c.title) || q);
    }
    for (const t of report.tableAST?.tables ?? []) {
      const q = t.provenance?.questionId ?? t.biQuery;
      if (q && !label.has(q)) label.set(q, loc(t.title) || q);
    }
    const all = Array.from(new Set(Object.values(elementQuestionMap(report))));
    for (const q of all) if (!label.has(q)) label.set(q, q);
    return { questions: all, qLabel: label };
  }, [report]);

  const chartableQuestions = useMemo(() => {
    const out = new Map<string, string>(); // qid → current chartType
    for (const c of report.chartAST?.charts ?? []) {
      const q = c.provenance?.questionId ?? c.biQuery;
      if (q) out.set(q, value.perQuestion?.[q]?.chartType ?? c.chartType);
    }
    return out;
  }, [report, value.perQuestion]);

  const front = value.frontMatter ?? {};
  const back = value.backMatter ?? {};

  const set = (patch: Partial<ReportOverrides>) => onChange({ ...value, ...patch });

  const isIncluded = (q: string) =>
    !value.includedQuestions || value.includedQuestions.includes(q);

  const toggleQuestion = (q: string) => {
    const base = value.includedQuestions ?? questions;
    const next = base.includes(q) ? base.filter((x) => x !== q) : [...base, q];
    set({ includedQuestions: next.length === questions.length ? undefined : next });
  };

  const setChartType = (q: string, chartType: string) =>
    set({ perQuestion: { ...value.perQuestion, [q]: { ...value.perQuestion?.[q], chartType } } });

  return (
    <aside className="flex h-full w-full max-w-xs flex-col gap-5 overflow-y-auto border-l border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text">Customize</h3>
        <Button size="sm" variant="primary" onClick={onSave} disabled={saving}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save
        </Button>
      </div>

      <Group label="Theme">
        <select
          value={value.theme ?? ''}
          onChange={(e) => set({ theme: e.target.value || undefined })}
          className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text"
        >
          <option value="">Default</option>
          {THEMES.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </Group>

      <Group label="Numbers & language">
        <div className="flex flex-wrap gap-2">
          <Toggle
            on={(value.numberSystem ?? 'indian') === 'indian'}
            onClick={() =>
              set({
                numberSystem:
                  (value.numberSystem ?? 'indian') === 'indian' ? 'international' : 'indian',
              })
            }
          >
            {(value.numberSystem ?? 'indian') === 'indian' ? 'Indian (12,34,567)' : 'International'}
          </Toggle>
          <Toggle
            on={(value.locale ?? 'en-IN') === 'hi-IN'}
            onClick={() => set({ locale: (value.locale ?? 'en-IN') === 'hi-IN' ? 'en-IN' : 'hi-IN' })}
          >
            {(value.locale ?? 'en-IN') === 'hi-IN' ? 'हिन्दी' : 'English'}
          </Toggle>
        </div>
      </Group>

      <Group label="Document">
        <div className="grid grid-cols-2 gap-1.5">
          <Check label="Cover" checked={front.cover ?? true} onChange={(v) => set({ frontMatter: { ...front, cover: v } })} />
          <Check label="Contents" checked={front.toc ?? true} onChange={(v) => set({ frontMatter: { ...front, toc: v } })} />
          <Check label="Notes" checked={back.notes ?? true} onChange={(v) => set({ backMatter: { ...back, notes: v } })} />
          <Check label="Glossary" checked={back.glossary ?? false} onChange={(v) => set({ backMatter: { ...back, glossary: v } })} />
        </div>
      </Group>

      <Group label="Section order">
        <SectionReorder items={sectionItems} onReorder={(ids) => set({ sectionOrder: ids })} />
      </Group>

      <Group label="Include questions">
        <ul className="space-y-1">
          {questions.map((q) => (
            <li key={q} className="flex items-center gap-2">
              <Check label={qLabel.get(q) ?? q} checked={isIncluded(q)} onChange={() => toggleQuestion(q)} />
            </li>
          ))}
        </ul>
      </Group>

      {chartableQuestions.size > 0 && (
        <Group label="Chart type">
          <ul className="space-y-2">
            {Array.from(chartableQuestions.entries()).map(([q, ct]) => (
              <li key={q} className="space-y-1">
                <span className="block truncate text-xs text-text-muted" title={qLabel.get(q)}>
                  {qLabel.get(q) ?? q}
                </span>
                <select
                  value={ct}
                  onChange={(e) => setChartType(q, e.target.value)}
                  className="w-full rounded-md border border-border bg-surface px-2 py-1 text-sm text-text"
                >
                  {CHART_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
        </Group>
      )}
    </aside>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">{label}</h4>
      {children}
    </section>
  );
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-2.5 py-1 text-xs font-medium transition ${
        on ? 'border-accent bg-accent/10 text-text' : 'border-border text-text-muted hover:text-text'
      }`}
    >
      {children}
    </button>
  );
}

function Check({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-sm text-text">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-border accent-accent"
      />
      <span className="truncate" title={label}>
        {label}
      </span>
    </label>
  );
}
