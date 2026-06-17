import { FigureChart } from '../FigureChart';
import { figureDataOf } from '../../engine/figureModel';
import type { KindProps } from './types';

/* CHART — real ECharts from the block's data (T1); placeholder when empty. */
export function ChartBlock({ block, isSelected, tableCaption }: KindProps) {
  const figData = figureDataOf(block);
  if (!figData) {
    return (
      <div className="rounded border border-dashed border-slate-300 bg-slate-50/40 px-3 py-6 text-center">
        <p className="text-[10px] font-medium text-slate-500">{tableCaption ? `${tableCaption} — ${block.title}` : block.title || 'Chart'}</p>
        <p className="mt-0.5 text-[9px] text-slate-400">Ask the assistant to fill this chart, or generate it.</p>
      </div>
    );
  }
  return <FigureChart data={figData} title={block.title} caption={tableCaption} controls={isSelected} height={210} />;
}
