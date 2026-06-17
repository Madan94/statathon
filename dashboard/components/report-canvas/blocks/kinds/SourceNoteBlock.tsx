import type { KindProps } from './types';

/* SOURCE NOTE — small grey provenance line. */
export function SourceNoteBlock({ block }: KindProps) {
  return <p className="py-0.5 text-[9px] text-slate-400">Source: {block.content}</p>;
}
