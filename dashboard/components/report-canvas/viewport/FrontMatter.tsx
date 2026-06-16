'use client';
import type { PageSize } from './A4Page';
import { PAGE_DIMENSIONS } from './A4Page';
import type { DocumentModel } from '../engine/useDocumentModel';

/* ═══════════════════════════════════════════════════════════════════
   Front matter (D-L4) — Cover page, Table of Contents, List of Tables,
   List of Figures. Rendered as fixed A4 sheets ahead of the content,
   matching printed MoSPI statistical volumes.

   Pure presentation: it reads the DocumentModel (numbers + page map) and
   paints. Page numbers reflow automatically because the model is derived
   from the live packer output.
   ═══════════════════════════════════════════════════════════════════ */

const MM_TO_PX = 3.7795;

interface SheetProps {
  pageSize: PageSize;
  zoom: number;
  children: React.ReactNode;
}

/** One scaled A4 sheet wrapper (mirrors A4Page's footprint + chrome). */
function Sheet({ pageSize, zoom, children }: SheetProps) {
  const dim = PAGE_DIMENSIONS[pageSize];
  const scale = zoom / 100;
  const pageW = dim.w * MM_TO_PX;
  const pageH = dim.h * MM_TO_PX;
  return (
    <div className="relative" style={{ width: pageW * scale, height: pageH * scale }}>
      <div
        className="absolute left-0 top-0 origin-top-left bg-white"
        style={{
          width: `${dim.w}mm`, height: `${dim.h}mm`,
          padding: '24mm 22mm', transform: `scale(${scale})`,
          boxShadow: '0 1px 4px rgba(0,0,0,0.05), 0 4px 24px rgba(0,0,0,0.03)',
        }}
      >
        {children}
      </div>
    </div>
  );
}

interface CoverProps {
  pageSize: PageSize;
  zoom: number;
  title: string;
  referencePeriod?: string;
  officer?: string;
  generatedOn?: string;
  /** 1-based sheet number printed in the footer. */
  pageNumber?: number;
  /** Issuing organisation — short crest text, full ministry name, parent body. */
  crest?: string;
  ministry?: string;
  parentBody?: string;
  /** Document classification line. */
  classification?: string;
}

/** Cover page — title block, crest area, period, generated date, officer. */
export function CoverPage({ pageSize, zoom, title, referencePeriod, officer, generatedOn, pageNumber = 1, crest = 'GoI', ministry = 'Ministry of Statistics & Programme Implementation', parentBody = 'Government of India', classification = 'Confidential — Official Statistics' }: CoverProps) {
  const date = generatedOn || new Date().toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' });
  return (
    <Sheet pageSize={pageSize} zoom={zoom}>
      <div className="flex h-full flex-col">
        {/* Crest / org band */}
        <div className="flex flex-col items-center pt-6">
          <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-slate-800 text-[10px] font-bold tracking-wide text-slate-800">
            {crest}
          </div>
          <p className="mt-3 text-[12px] font-semibold tracking-wide text-slate-700">{ministry}</p>
          <p className="text-[10px] text-slate-400">{parentBody}</p>
        </div>

        {/* Title block */}
        <div className="mt-auto mb-auto text-center">
          <div className="mx-auto mb-4 h-[3px] w-24 rounded bg-slate-800" />
          <h1 className="px-6 text-[28px] font-extrabold uppercase leading-tight tracking-wide text-slate-900">{title}</h1>
          {referencePeriod && <p className="mt-3 text-[14px] font-medium text-slate-500">Reference Period: {referencePeriod}</p>}
          <div className="mx-auto mt-4 h-[3px] w-24 rounded bg-slate-800" />
        </div>

        {/* Footer block */}
        <div className="mt-auto border-t border-slate-200 pt-3 text-center text-[10px] text-slate-400">
          {officer && <p>Prepared by: {officer}</p>}
          <p>Generated on {date}</p>
          {classification && <p className="mt-1 italic">{classification}</p>}
          <p className="mt-2 tabular-nums text-slate-300">Page {pageNumber}</p>
        </div>
      </div>
    </Sheet>
  );
}

interface TocProps {
  pageSize: PageSize;
  zoom: number;
  model: DocumentModel;
  /** Page offset added to every page number (front-matter pages precede content). */
  pageOffset: number;
  onJump?: (anchor: string) => void;
  /** 1-based sheet number printed in the footer. */
  pageNumber?: number;
}

/** Table of Contents + List of Tables + List of Figures sheet. */
export function ContentsPage({ pageSize, zoom, model, pageOffset, onJump, pageNumber = 2 }: TocProps) {
  const { toc, listOfTables, listOfFigures } = model;
  return (
    <Sheet pageSize={pageSize} zoom={zoom}>
      <div className="flex h-full flex-col">
        <h2 className="mb-3 text-[18px] font-extrabold uppercase tracking-wide text-slate-900">Contents</h2>
        <ul className="space-y-1">
          {toc.map((e) => (
            <li
              key={e.anchor}
              onClick={() => onJump?.(e.anchor)}
              className={`flex cursor-pointer items-baseline gap-2 ${e.depth === 1 ? 'font-bold text-slate-800' : e.depth === 2 ? 'pl-4 font-medium text-slate-700' : 'pl-8 text-slate-600'}`}
              style={{ fontSize: e.depth === 1 ? 12 : e.depth === 2 ? 11 : 10 }}
            >
              <span className="tabular-nums text-slate-400">{e.number}</span>
              <span className="truncate">{e.label}</span>
              <span className="mx-1 flex-1 border-b border-dotted border-slate-300" />
              <span className="tabular-nums text-slate-400">{e.page + pageOffset}</span>
            </li>
          ))}
          {toc.length === 0 && <li className="text-[10px] italic text-slate-300">Generating outline…</li>}
        </ul>

        {listOfTables.length > 0 && (
          <>
            <h3 className="mb-2 mt-5 text-[13px] font-bold text-slate-800">List of Tables</h3>
            <ul className="space-y-0.5">
              {listOfTables.map((t, i) => (
                <li key={i} className="flex items-baseline gap-2 text-[10px] text-slate-600">
                  <span className="tabular-nums font-medium text-slate-500">{t.caption}</span>
                  <span className="truncate">{t.title}</span>
                  <span className="mx-1 flex-1 border-b border-dotted border-slate-300" />
                  <span className="tabular-nums text-slate-400">{t.page + pageOffset}</span>
                </li>
              ))}
            </ul>
          </>
        )}

        {listOfFigures.length > 0 && (
          <>
            <h3 className="mb-2 mt-5 text-[13px] font-bold text-slate-800">List of Figures</h3>
            <ul className="space-y-0.5">
              {listOfFigures.map((f, i) => (
                <li key={i} className="flex items-baseline gap-2 text-[10px] text-slate-600">
                  <span className="tabular-nums font-medium text-slate-500">{f.caption}</span>
                  <span className="truncate">{f.title}</span>
                  <span className="mx-1 flex-1 border-b border-dotted border-slate-300" />
                  <span className="tabular-nums text-slate-400">{f.page + pageOffset}</span>
                </li>
              ))}
            </ul>
          </>
        )}

        <div className="mt-auto border-t border-slate-100 pt-2 text-right text-[8px] text-slate-300">
          <span className="tabular-nums">Page {pageNumber}</span>
        </div>
      </div>
    </Sheet>
  );
}
