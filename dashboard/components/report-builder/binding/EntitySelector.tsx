'use client';

import { useMemo, useState } from 'react';
import { Check, Search } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';

export interface EntityOption {
  entityId: string;
  entityName: string;
  role: 'dimension' | 'measure' | 'time' | 'filter' | 'metadata' | string;
  columnName?: string;
  source: string; // "section", "chapter", "topic", "all"
  sourceLabel: string; // e.g. "Coal reserves by State/UT"
}

interface EntitySelectorProps {
  /** All available entities grouped by hierarchy level */
  entities: EntityOption[];
  /** Currently selected entity IDs */
  selected: string[];
  /** Called when selection changes */
  onChange: (selected: string[]) => void;
  /** Optional role filter */
  roleFilter?: string;
}

function roleBadgeVariant(role: string): 'success' | 'warning' | 'muted' | 'default' {
  if (role === 'measure') return 'success';
  if (role === 'dimension') return 'warning';
  if (role === 'time') return 'default';
  return 'muted';
}

export function EntitySelector({ entities, selected, onChange }: EntitySelectorProps) {
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('all');

  const grouped = useMemo(() => {
    const groups = new Map<string, EntityOption[]>();
    for (const e of entities) {
      const key = e.sourceLabel || e.source;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(e);
    }
    return groups;
  }, [entities]);

  const filtered = useMemo(() => {
    let list = entities;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((e) => e.entityName.toLowerCase().includes(q) || e.entityId.toLowerCase().includes(q) || (e.columnName || '').toLowerCase().includes(q));
    }
    if (roleFilter !== 'all') {
      list = list.filter((e) => e.role === roleFilter);
    }
    return list;
  }, [entities, search, roleFilter]);

  const filteredGrouped = useMemo(() => {
    const groups = new Map<string, EntityOption[]>();
    for (const e of filtered) {
      const key = e.sourceLabel || e.source;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(e);
    }
    return groups;
  }, [filtered]);

  const toggle = (entityId: string) => {
    if (selected.includes(entityId)) {
      onChange(selected.filter((id) => id !== entityId));
    } else {
      onChange([...selected, entityId]);
    }
  };

  const selectAll = () => {
    const allIds = filtered.map((e) => e.entityId);
    const merged = Array.from(new Set([...selected, ...allIds]));
    onChange(merged);
  };

  const roles = useMemo(() => Array.from(new Set(entities.map((e) => e.role))), [entities]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Required entities</p>
        <button type="button" onClick={selectAll} className="text-[10px] font-semibold text-primary hover:underline">
          Select all
        </button>
      </div>

      {/* Search + role filter */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search entities..."
            className="w-full rounded-md border border-border bg-surface py-1.5 pl-7 pr-2 text-xs text-text outline-none focus:ring-1 focus:ring-primary/30"
          />
        </div>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none"
        >
          <option value="all">All roles</option>
          {roles.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>

      {/* Grouped entity list */}
      <div className="max-h-[16rem] space-y-3 overflow-auto rounded-lg border border-border bg-surface p-2">
        {filteredGrouped.size > 0 ? (
          Array.from(filteredGrouped.entries()).map(([group, items]) => (
            <div key={group}>
              <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-text-muted">{group}</p>
              <div className="space-y-0.5">
                {items.map((entity) => {
                  const isSelected = selected.includes(entity.entityId);
                  return (
                    <button
                      key={entity.entityId}
                      type="button"
                      onClick={() => toggle(entity.entityId)}
                      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors ${isSelected ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface-card hover:text-text'}`}
                    >
                      <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${isSelected ? 'border-primary bg-primary text-white' : 'border-border'}`}>
                        {isSelected && <Check className="h-3 w-3" />}
                      </span>
                      <span className="min-w-0 flex-1 truncate font-medium">{entity.entityName}</span>
                      <Badge variant={roleBadgeVariant(entity.role)} className="px-1 py-0 text-[8px]">{entity.role}</Badge>
                      {entity.columnName && <span className="truncate text-[9px] text-text-muted">({entity.columnName})</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          ))
        ) : (
          <p className="py-3 text-center text-xs text-text-muted">No entities match your search.</p>
        )}
      </div>

      {/* Selection summary */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selected.map((id) => {
            const e = entities.find((x) => x.entityId === id);
            return (
              <span key={id} className="inline-flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-medium text-primary">
                {e?.entityName || id}
                <button type="button" onClick={() => toggle(id)} className="ml-0.5 hover:text-danger">×</button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
