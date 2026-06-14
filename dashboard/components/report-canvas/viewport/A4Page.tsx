'use client';
import type { PageBlock } from '../engine/useCanvasState';
import { BlockRenderer } from '../blocks/BlockRenderer';

/* ═══════════════════════════════════════════════════════════════════
   A4Page — renders one fixed-size A4 page with its blocks.
   Exact 210×297mm proportions. Content cannot overflow.
   ═══════════════════════════════════════════════════════════════════ */

interface A4PageProps {
  blocks: PageBlock[];
  pageNumber: number;
  totalPages: number;
  selectedBlockId: string | null;
  onSelectBlock: (id: string | null) => void;
  onGenerate?: (index: number) => void;
}

export function A4Page({ blocks, pageNumber, totalPages, selectedBlockId, onSelectBlock, onGenerate }: A4PageProps) {
  return (
    <div
      className="relative mx-auto bg-white overflow-hidden select-none"
      style={{
        width: '210mm',
        height: '297mm',
        maxWidth: '100%',
        maxHeight: '100%',
        padding: '18mm 22mm 20mm 22mm',
        boxShadow: '0 2px 8px rgba(0,0,0,0.06), 0 8px 32px rgba(0,0,0,0.04)',
        aspectRatio: '210 / 297',
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
