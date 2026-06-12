'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Filter } from 'lucide-react';

export interface TypeFilterDropdownProps {
  label?: string;
  types: string[];
  selected: Set<string>;
  onChange: (selected: Set<string>) => void;
  counts?: Record<string, number>;
  typeColors?: Record<string, string>;
}

export function TypeFilterDropdown({
  label = 'Filter by type',
  types,
  selected,
  onChange,
  counts,
  typeColors,
}: TypeFilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  if (types.length === 0) return null;

  const allSelected = types.every((type) => selected.has(type));
  const noneSelected = types.every((type) => !selected.has(type));

  const toggleType = (type: string) => {
    const next = new Set(selected);
    if (next.has(type)) next.delete(type);
    else next.add(type);
    onChange(next);
  };

  const selectAll = () => onChange(new Set(types));
  const clearAll = () => onChange(new Set());

  return (
    <div ref={rootRef} className="relative mb-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs font-medium text-text shadow-sm hover:bg-surface/80 focus:outline-none focus:ring-2 focus:ring-accent/40"
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <Filter className="h-3.5 w-3.5 text-text-muted" aria-hidden />
        <span>{label}</span>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
          {selected.size}/{types.length}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-text-muted transition-transform ${open ? 'rotate-180' : ''}`}
          aria-hidden
        />
      </button>

      {open && (
        <div className="absolute left-0 z-20 mt-2 w-72 rounded-lg border border-border bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold text-text">Show types</span>
            <div className="flex items-center gap-2 text-[10px]">
              <button
                type="button"
                onClick={selectAll}
                disabled={allSelected}
                className="text-primary hover:underline disabled:cursor-not-allowed disabled:opacity-40"
              >
                Select all
              </button>
              <span className="text-text-muted">·</span>
              <button
                type="button"
                onClick={clearAll}
                disabled={noneSelected}
                className="text-text-muted hover:text-text hover:underline disabled:cursor-not-allowed disabled:opacity-40"
              >
                Clear all
              </button>
            </div>
          </div>
          <ul className="max-h-64 overflow-y-auto py-2" role="listbox" aria-label={label}>
            {types.map((type) => {
              const checked = selected.has(type);
              const count = counts?.[type];
              return (
                <li key={type}>
                  <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 hover:bg-surface/80">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleType(type)}
                      className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-accent/40"
                    />
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        typeColors?.[type] || 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {type}
                    </span>
                    {typeof count === 'number' && (
                      <span className="ml-auto text-[10px] text-text-muted">{count}</span>
                    )}
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Build sorted unique type keys and per-type counts from records. */
export function collectTypeOptions(
  items: Array<Record<string, unknown>>,
  getType: (item: Record<string, unknown>) => string
): { types: string[]; counts: Record<string, number> } {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const type = getType(item);
    counts[type] = (counts[type] || 0) + 1;
  }
  return { types: Object.keys(counts).sort(), counts };
}

/** Keep filter selection in sync when available types change (defaults to all selected). */
export function useTypeFilter(types: string[]): [Set<string>, (next: Set<string>) => void] {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(types));

  useEffect(() => {
    setSelected(new Set(types));
  }, [types.join('|')]);

  return [selected, setSelected];
}
