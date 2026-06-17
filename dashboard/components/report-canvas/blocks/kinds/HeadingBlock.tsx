import type { KindProps } from './types';

/* HEADING — MoSPI decimal type-scale (Topic=1 / Chapter=1.1). */
export function HeadingBlock({ block, numbering }: KindProps) {
  const depth = numbering?.depth ?? Math.min(2, Math.max(1, block.sectionPath.length));
  const label = (block.content || block.title).replace(/^(topic|chapter):\s*/i, '');
  const num = numbering?.number;
  if (depth === 1) {
    return (
      <div id={numbering?.anchor} className="scroll-mt-4 pt-2 pb-1">
        <h2 className="doc-heading doc-h1 flex items-baseline gap-2 uppercase tracking-wide text-slate-900">
          {num && <span className="doc-num tabular-nums text-slate-400">{num}</span>}
          <span>{label}</span>
        </h2>
        <div className="mt-1 h-[2px] w-full rounded bg-slate-800/80" />
      </div>
    );
  }
  return (
    <h3 id={numbering?.anchor} className="doc-heading doc-h2 scroll-mt-4 flex items-baseline gap-2 pt-1.5 pb-0.5 text-slate-800">
      {num && <span className="doc-num tabular-nums text-slate-400">{num}</span>}
      <span>{label}</span>
    </h3>
  );
}
