'use client';

/**
 * R5 — version history. Lists saved report versions (v1 = the preserved
 * original) and lets the reviewer view any earlier snapshot in the preview.
 */
import { History } from 'lucide-react';

interface Props {
  versions: number[];
  current: number | null;
  selected: number | null; // null ⇒ viewing the latest/current
  onSelect: (version: number | null) => void;
}

export function VersionHistory({ versions, current, selected, onSelect }: Props) {
  if (!versions.length) {
    return (
      <p className="text-xs text-text-muted">
        No edits yet — the first edit preserves the original as v1.
      </p>
    );
  }
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
        <History className="h-3.5 w-3.5" /> Versions
      </div>
      <ul className="space-y-1">
        {versions.map((v) => {
          const isCurrent = v === current;
          const isSelected = selected === v || (selected === null && isCurrent);
          return (
            <li key={v}>
              <button
                type="button"
                onClick={() => onSelect(isCurrent ? null : v)}
                className={`flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-sm transition ${
                  isSelected
                    ? 'border-accent bg-accent/10 text-text'
                    : 'border-border text-text-muted hover:text-text'
                }`}
              >
                <span>
                  v{v}
                  {v === 1 && <span className="ml-1 text-xs text-text-muted">(original)</span>}
                </span>
                {isCurrent && (
                  <span className="rounded bg-accent/15 px-1.5 text-[10px] font-medium text-accent">
                    current
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
