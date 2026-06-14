'use client';
import type { PageBlock } from '../engine/useCanvasState';
import { BlockRenderer } from '../blocks/BlockRenderer';

/* ═══════════════════════════════════════════════════════════════════
   A4Page — renders one fixed-size A4 page with its blocks.
   Exact 210×297mm proportions. Content cannot overflow.
   ═══════════════════════════════════════════════════════════════════ */

export type PageSize = 'a4' | 'a4-extended' | 'mospi' | 'letter';

const PAGE_DIMENSIONS: Record<PageSize, { w: number; h: number; label: string }> = {
  'a4':          { w: 210, h: 297, label: 'A4 (210×297mm)' },
  'a4-extended': { w: 210, h: 350, label: 'A4 Extended' },
  'mospi':       { w: 215, h: 305, label: 'MoSPI Standard' },
  'letter':      { w: 216, h: 279, label: 'US Letter' },
};

export { PAGE_DIMENSIONS };

interface A4PageProps {
  blocks: PageBlock[];
  pageNumber: number;
  totalPages: number;
  selectedBlockId: string | null;
  onSelectBlock: (id: string | null) => void;
  onGenerate?: (index: number) => void;
  pageSize?: PageSize;
  zoom?: number;
}

export function A4Page({ blocks, pageNumber, totalPages, selectedBlockId, onSelectBlock, onGenerate, pageSize = 'a4', zoom = 100 }: A4PageProps) {
  const dim = PAGE_DIMENSIONS[pageSize];
  const scale = zoom / 100;
  return (
    <div
      className="relative mx-auto bg-white overflow-hidden select-none origin-top transition-transform duration-200"
      style={{
        width: `${dim.w}mm`,
        height: `${dim.h}mm`,
        padding: '18mm 22mm 20mm 22mm',
        boxShadow: '0 1px 4px rgba(0,0,0,0.05), 0 4px 24px rgba(0,0,0,0.03)',
        transform: `scale(${scale})`,
      }}
      onClick={() => onSelectBlock(null)}
    >
      {/* Page content area */}
      <div className="h-full overflow-hidden">
        {blocks.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-slate-300">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-50">
              <svg className="h-8 w-8 text-slate-200" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4v16m8-8H4" /></svg>
            </div>
            <p className="text-[13px] font-medium">Empty page</p>
            <p className="mt-1 text-[11px]">Click Auto-Generate or drag elements here</p>
          </div>
        ) : (
          <div className="space-y-3">
            {blocks.map(block => (
              <BlockRenderer
                key={block.id}
                block={block}
                isSelected={selectedBlockId === block.id}
                onSelect={() => onSelectBlock(block.id)}
                onGenerate={onGenerate}
              />
            ))}
          </div>
        )}
      </div>

      {/* Page footer */}
      <div className="absolute bottom-[8mm] left-[22mm] right-[22mm] flex items-center justify-between text-[8px] text-slate-300">
        <span>MoSPI Statistical Report</span>
        <span className="tabular-nums">Page {pageNumber} of {totalPages}</span>
      </div>
    </div>
  );
}
