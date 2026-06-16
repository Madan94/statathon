'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, CornerDownLeft } from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════
   Command Palette (S4) — global ⌘K / Ctrl-K launcher.
   Searches actions, sections (jump), and components (generate/inspect).
   A flat, fuzzy-filtered list; Enter runs the highlighted command.
   ═══════════════════════════════════════════════════════════════════ */

export interface PaletteCommand {
  id: string;
  label: string;
  hint?: string;
  group: 'Actions' | 'Sections' | 'Components';
  run: () => void;
}

interface Props {
  open: boolean;
  onClose: () => void;
  commands: PaletteCommand[];
}

export function CommandPalette({ open, onClose, commands }: Props) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setActive(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands.slice(0, 40);
    return commands
      .filter(c => `${c.label} ${c.hint ?? ''} ${c.group}`.toLowerCase().includes(q))
      .slice(0, 40);
  }, [commands, query]);

  useEffect(() => { setActive(0); }, [query]);

  if (!open) return null;

  const run = (c?: PaletteCommand) => {
    if (!c) return;
    c.run();
    onClose();
  };

  // Group while preserving filtered order.
  const groups: Record<string, PaletteCommand[]> = {};
  filtered.forEach(c => { (groups[c.group] ||= []).push(c); });
  let flatIndex = -1;

  return (
    <div className="fixed inset-0 z-[120] flex items-start justify-center bg-slate-900/30 pt-[12vh] backdrop-blur-sm" onClick={onClose}>
      <div className="w-[560px] overflow-hidden rounded-xl bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* Search */}
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, filtered.length - 1)); }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
              else if (e.key === 'Enter') { e.preventDefault(); run(filtered[active]); }
              else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
            }}
            placeholder="Search actions, sections, components…"
            className="flex-1 text-[13px] text-slate-700 placeholder:text-slate-400 outline-none"
          />
          <kbd className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] text-slate-400">Esc</kbd>
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-auto py-1">
          {Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <p className="px-4 pt-2 pb-1 text-[9px] font-bold uppercase tracking-wide text-slate-300">{group}</p>
              {items.map(c => {
                flatIndex += 1;
                const idx = flatIndex;
                return (
                  <button
                    key={c.id}
                    onMouseEnter={() => setActive(idx)}
                    onClick={() => run(c)}
                    className={`flex w-full items-center justify-between px-4 py-1.5 text-left text-[12px] ${
                      active === idx ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span className="truncate">{c.label}</span>
                    <span className="flex items-center gap-2">
                      {c.hint && <span className="text-[9px] text-slate-400">{c.hint}</span>}
                      {active === idx && <CornerDownLeft className="h-3 w-3 text-blue-400" />}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="px-4 py-8 text-center text-[12px] text-slate-300">No matches.</p>
          )}
        </div>
      </div>
    </div>
  );
}
