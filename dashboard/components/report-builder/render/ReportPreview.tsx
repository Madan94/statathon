'use client';

/**
 * R3 — live preview composer. Walks `semanticAST.sections` in order and
 * dispatches each child to the paragraph / figure (ECharts) / table renderer,
 * mirroring the server `blocks.render_question_group`. A provenance drawer opens
 * when a measured table value is clicked.
 */
import { useMemo, useState } from 'react';

import type {
  Block,
  Chart,
  Figure,
  Locale,
  NumberSystem,
  ReportAST,
} from '@/lib/report/types';
import { loc } from '@/lib/report/format';
import { ReportChart } from './ReportChart';
import { ReportTable } from './ReportTable';
import { ProvenanceDrawer, type ProvenanceTarget } from './ProvenanceDrawer';

interface Props {
  report: ReportAST;
  locale?: Locale;
  numberSystem?: NumberSystem;
}

export function ReportPreview({ report, locale = 'en-IN', numberSystem = 'indian' }: Props) {
  const [target, setTarget] = useState<ProvenanceTarget | null>(null);

  const blocks = useMemo(
    () => indexBy(report.contentAST?.blocks ?? [], (b) => b.blockId),
    [report],
  );
  const figures = useMemo(
    () => indexBy(report.figureAST?.figures ?? [], (f) => f.figureId),
    [report],
  );
  const charts = useMemo(
    () => indexBy(report.chartAST?.charts ?? [], (c) => c.chartId),
    [report],
  );
  const tables = useMemo(
    () => indexBy(report.tableAST?.tables ?? [], (t) => t.tableId),
    [report],
  );

  const sections = useMemo(
    () => [...(report.semanticAST?.sections ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
    [report],
  );

  return (
    <div className="mx-auto max-w-3xl px-2 py-4">
      {sections.map((section, si) => (
        <section key={section.sectionId ?? si} id={section.sectionId} className="mb-8">
          {section.title && (
            <h2 className="mb-3 border-l-4 border-accent pl-2.5 text-lg font-semibold text-text">
              {loc(section.title, locale)}
            </h2>
          )}
          {(section.children ?? []).map((childId) => {
            const block = blocks.get(childId);
            if (block) return <Paragraph key={childId} block={block} locale={locale} />;

            const figure = figures.get(childId);
            if (figure) {
              const chart = figure.chartRef ? charts.get(figure.chartRef) : undefined;
              return (
                <FigureView key={childId} figure={figure} chart={chart} locale={locale} />
              );
            }

            const table = tables.get(childId);
            if (table) {
              return (
                <ReportTable
                  key={childId}
                  table={table}
                  locale={locale}
                  numberSystem={numberSystem}
                  onValueClick={setTarget}
                />
              );
            }

            return (
              <p key={childId} className="my-2 text-sm italic text-red-600">
                [unresolved: {childId}]
              </p>
            );
          })}
        </section>
      ))}

      <ProvenanceDrawer target={target} onClose={() => setTarget(null)} />
    </div>
  );
}

function Paragraph({ block, locale }: { block: Block; locale: Locale }) {
  const text = loc(block.content, locale);
  if (!text) return <p className="my-2 text-sm italic text-text-muted">[empty paragraph]</p>;
  return <p className="my-2 text-justify leading-relaxed text-text">{text}</p>;
}

function FigureView({
  figure,
  chart,
  locale,
}: {
  figure: Figure;
  chart: Chart | undefined;
  locale: Locale;
}) {
  const caption = loc(figure.caption, locale);
  return (
    <figure className="my-5">
      {chart ? (
        <ReportChart chart={chart} locale={locale} />
      ) : (
        <div className="text-sm italic text-red-600">[missing chart]</div>
      )}
      {caption && (
        <figcaption className="mt-1.5 text-center text-xs italic text-text-muted">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

function indexBy<T>(items: T[], key: (item: T) => string | undefined): Map<string, T> {
  const m = new Map<string, T>();
  for (const item of items) {
    const k = key(item);
    if (k) m.set(k, item);
  }
  return m;
}
