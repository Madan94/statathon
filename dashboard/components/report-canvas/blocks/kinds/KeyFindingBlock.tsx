import type { KindProps } from './types';

/* KEY FINDING — emphasised callout. */
export function KeyFindingBlock({ block }: KindProps) {
  return (
    <div className="rounded-md bg-blue-50/70 px-4 py-2.5">
      <p className="doc-body font-medium text-slate-700" dangerouslySetInnerHTML={{ __html: block.content }} />
    </div>
  );
}
