'use client';

import { BookOpen, ChevronLeft, ChevronRight, Maximize2, Minus, Plus, ScrollText } from 'lucide-react';
import type { PageSize } from '../viewport/A4Page';

export type Density = 'compact' | 'comfortable';
export type ViewMode = 'paged' | 'scroll';

interface Props {
  pageSize: PageSize;
  onPageSizeChange: (s: PageSize) => void;
  density: Density;
  onDensityChange: (d: Density) => void;
  typographyPreset?: string;
  onTypographyPresetChange?: (id: string) => void;
  typographyPresets?: Array<{ id: string; label: string }>;
  onOpenTypography?: () => void;
  viewMode: ViewMode;
  onViewModeChange: (v: ViewMode) => void;
  showFrontMatter: boolean;
  onToggleFrontMatter: () => void;
  zoom: number;
  onZoomChange: (z: number) => void;
  currentPage: number;
  totalPages: number;
  onGoToPage: (i: number) => void;
  onAddPage: () => void;
}

export function CanvasViewBar({
  pageSize,
  onPageSizeChange,
  density,
  onDensityChange,
  typographyPreset,
  onTypographyPresetChange,
  typographyPresets,
  onOpenTypography,
  viewMode,
  onViewModeChange,
  showFrontMatter,
  onToggleFrontMatter,
  zoom,
  onZoomChange,
  currentPage,
  totalPages,
  onGoToPage,
  onAddPage,
}: Props) {
  const current = totalPages > 0 ? Math.min(currentPage + 1, totalPages) : 0;

  return (
    <div className="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-3">
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex shrink-0 items-center gap-0.5 rounded-md border border-slate-200 bg-white p-0.5 shadow-sm">
          <button
            type="button"
            onClick={() => onViewModeChange('paged')}
            title="Paged view"
            aria-label="Paged view"
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors ${viewMode === 'paged' ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
          >
            <BookOpen className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Paged</span>
          </button>
          <button
            type="button"
            onClick={() => onViewModeChange('scroll')}
            title="Scroll view"
            aria-label="Scroll view"
            className={`flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors ${viewMode === 'scroll' ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
          >
            <ScrollText className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Scroll</span>
          </button>
        </div>

        <button
          type="button"
          onClick={onToggleFrontMatter}
          title="Toggle cover and contents pages"
          className={`hidden rounded-md px-2 py-1 text-[11px] font-medium transition-colors sm:block ${showFrontMatter ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-white'}`}
        >
          Front matter
        </button>
      </div>

      <div className="flex shrink-0 items-center gap-2 rounded-md border border-slate-200 bg-white px-2 py-1 shadow-sm">
        <button
          type="button"
          onClick={() => onGoToPage(currentPage - 1)}
          disabled={currentPage <= 0}
          title="Previous page"
          aria-label="Previous page"
          className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-25"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="min-w-[84px] text-center text-[11px] font-medium tabular-nums text-slate-700">
          Page {current || 1} of {Math.max(totalPages, 1)}
        </span>
        <button
          type="button"
          onClick={() => onGoToPage(currentPage + 1)}
          disabled={currentPage >= totalPages - 1}
          title="Next page"
          aria-label="Next page"
          className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-25"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onAddPage}
          title="Add page"
          aria-label="Add page"
          className="hidden rounded border border-dashed border-slate-300 p-1 text-slate-400 hover:border-blue-400 hover:text-blue-600 md:block"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex min-w-0 items-center justify-end gap-2">
        <select
          value={pageSize}
          onChange={e => onPageSizeChange(e.target.value as PageSize)}
          title="Page size"
          className="hidden rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:border-blue-300 lg:block"
        >
          <option value="a4">A4</option>
          <option value="mospi">MoSPI</option>
          <option value="a4-extended">A4+</option>
          <option value="letter">Letter</option>
        </select>

        <select
          value={density}
          onChange={e => onDensityChange(e.target.value as Density)}
          title="Density"
          className="hidden rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:border-blue-300 xl:block"
        >
          <option value="comfortable">Comfortable</option>
          <option value="compact">Compact</option>
        </select>

        {onTypographyPresetChange && typographyPresets && (
          <select
            value={typographyPreset}
            onChange={e => onTypographyPresetChange(e.target.value)}
            title="Document font"
            className="hidden max-w-[130px] rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:border-blue-300 2xl:block"
          >
            {typographyPresets.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        )}

        <div className="flex items-center gap-0.5 rounded-md border border-slate-200 bg-white p-0.5 shadow-sm">
          <button
            type="button"
            onClick={() => onZoomChange(Math.max(25, zoom - 10))}
            title="Zoom out"
            aria-label="Zoom out"
            className="rounded p-1 text-slate-500 hover:bg-slate-100"
          >
            <Minus className="h-3.5 w-3.5" />
          </button>
          <select
            value={zoom}
            onChange={e => onZoomChange(Number(e.target.value))}
            title="Zoom"
            className="rounded bg-transparent px-1 py-0.5 text-[11px] text-slate-700 outline-none"
          >
            {[50, 75, 100, 125, 150].map(z => <option key={z} value={z}>{z}%</option>)}
          </select>
          <button
            type="button"
            onClick={() => onZoomChange(Math.min(150, zoom + 10))}
            title="Zoom in"
            aria-label="Zoom in"
            className="rounded p-1 text-slate-500 hover:bg-slate-100"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        {onOpenTypography && (
          <button
            type="button"
            onClick={onOpenTypography}
            title="Typography settings"
            aria-label="Typography settings"
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 shadow-sm hover:bg-slate-50"
          >
            Aa
          </button>
        )}

        <button
          type="button"
          onClick={() => onZoomChange(100)}
          title="Reset zoom"
          aria-label="Reset zoom"
          className="hidden rounded-md p-1.5 text-slate-500 hover:bg-white lg:block"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
