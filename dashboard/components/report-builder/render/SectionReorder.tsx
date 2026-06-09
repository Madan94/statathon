'use client';

/**
 * R4 — dependency-free section reorder (move up / down). Emits the new order of
 * section ids; the parent maps that to the `sectionOrder` override.
 */
import { ChevronDown, ChevronUp, GripVertical } from 'lucide-react';

export interface ReorderItem {
  id: string;
  label: string;
}

interface Props {
  items: ReorderItem[];
  onReorder: (orderedIds: string[]) => void;
}

export function SectionReorder({ items, onReorder }: Props) {
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    const ids = items.map((it) => it.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    onReorder(ids);
  };

  if (!items.length) {
    return <p className="text-xs text-text-muted">No sections.</p>;
  }

  return (
    <ul className="space-y-1">
      {items.map((it, i) => (
        <li
          key={it.id}
          className="flex items-center gap-2 rounded-md border border-border bg-surface px-2 py-1.5"
        >
          <GripVertical className="h-3.5 w-3.5 shrink-0 text-text-muted" />
          <span className="flex-1 truncate text-sm text-text" title={it.label}>
            {it.label || it.id}
          </span>
          <button
            type="button"
            onClick={() => move(i, -1)}
            disabled={i === 0}
            className="rounded p-1 text-text-muted hover:bg-border/40 disabled:opacity-30"
            aria-label={`Move ${it.label} up`}
          >
            <ChevronUp className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => move(i, 1)}
            disabled={i === items.length - 1}
            className="rounded p-1 text-text-muted hover:bg-border/40 disabled:opacity-30"
            aria-label={`Move ${it.label} down`}
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </li>
      ))}
    </ul>
  );
}
