import { makeNum } from '../blockFormat';
import type { KindProps } from './types';

/* METRIC — a single big number + unit + optional label. */
export function MetricBlock({ block, numerals }: KindProps) {
  const num = makeNum(numerals);
  return (
    <div className="flex items-baseline gap-2 rounded border border-slate-200 bg-gradient-to-r from-white to-slate-50 px-4 py-3">
      <span className="text-[22px] font-bold tabular-nums text-slate-800">{num(block.metricValue)}</span>
      {block.metricUnit && <span className="text-[11px] text-slate-400">{block.metricUnit}</span>}
      {block.content && <span className="ml-2 text-[10px] text-slate-500">{block.content}</span>}
    </div>
  );
}
