import type { KindProps } from './types';

/* NARRATIVE — a `section:` prefix becomes a numbered §-sub-heading; otherwise
   it's body prose (stored as lightweight HTML). */
export function NarrativeBlock({ block, numbering }: KindProps) {
  const isSection = /^section:/i.test(block.content.trim());
  if (isSection) {
    return (
      <h4 id={numbering?.anchor} className="doc-heading doc-h3 scroll-mt-4 flex items-baseline gap-2 pl-4 pt-1 pb-0.5 font-semibold text-slate-700">
        {numbering?.number && <span className="tabular-nums text-slate-400">{numbering.number}</span>}
        <span>{block.content.replace(/^section:\s*/i, '')}</span>
      </h4>
    );
  }
  return block.content
    ? <p className="doc-body py-1 text-slate-700" dangerouslySetInnerHTML={{ __html: block.content }} />
    : <p className="doc-body py-1 text-slate-700"><span className="text-slate-300 italic">Double-click to edit…</span></p>;
}
