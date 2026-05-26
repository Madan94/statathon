'use client';

import { useState } from 'react';
import { AnalysisResult, ColumnProfile } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import { Pencil, Trash2, RotateCcw, CheckCircle2, ChevronLeft } from 'lucide-react';

export interface ColumnDecision {
  originalName: string;
  displayName: string;
  included: boolean;
  typeOverride?: string;
}

interface Props {
  results: AnalysisResult;
  decisions: Record<string, ColumnDecision>;
  onProceed: (decisions: Record<string, ColumnDecision>) => void;
  onBack: () => void;
}

export default function Step2Normalize({ results, decisions, onProceed, onBack }: Props) {
  const health = results.health as {
    rows?: number;
    missing_per_column?: Record<string, number>;
    dtypes?: Record<string, string>;
  } | undefined;
  const columnProfiles = results.column_profiles as Record<string, ColumnProfile> | undefined;
  const schema = results.schema ?? {};
  const allColumns = Object.keys(columnProfiles ?? schema);
  const totalRows = health?.rows ?? 0;

  const [cols, setCols] = useState<Record<string, ColumnDecision>>(() => {
    const init: Record<string, ColumnDecision> = {};
    allColumns.forEach((c) => {
      init[c] = decisions[c] ?? {
        originalName: c,
        displayName: c,
        included: true,
        typeOverride: undefined,
      };
    });
    return init;
  });

  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');

  const startEdit = (key: string) => {
    setEditingKey(key);
    setEditValue(cols[key].displayName);
  };
  const commitEdit = (key: string) => {
    const trimmed = editValue.trim();
    if (trimmed) {
      setCols((prev) => ({
        ...prev,
        [key]: { ...prev[key], displayName: trimmed },
      }));
    }
    setEditingKey(null);
  };
  const toggleInclude = (key: string) => {
    setCols((prev) => ({
      ...prev,
      [key]: { ...prev[key], included: !prev[key].included },
    }));
  };
  const resetAll = () => {
    setCols((prev) => {
      const next = { ...prev };
      allColumns.forEach((c) => {
        next[c] = { ...next[c], displayName: c, included: true };
      });
      return next;
    });
  };

  const includedCount = Object.values(cols).filter((c) => c.included).length;
  const renamedCount = Object.values(cols).filter(
    (c) => c.displayName !== c.originalName
  ).length;
  const excludedCount = allColumns.length - includedCount;

  return (
    <div className="space-y-6">
      {/* Summary bar */}
      <div className="flex flex-wrap gap-3">
        <Badge variant="success">{includedCount} included</Badge>
        {excludedCount > 0 && <Badge variant="danger">{excludedCount} excluded</Badge>}
        {renamedCount > 0 && <Badge variant="warning">{renamedCount} renamed</Badge>}
      </div>

      <Card
        title="Column normalisation"
        description="Rename columns, exclude irrelevant ones, or override type hints before semantic mapping begins."
      >
        <div className="overflow-x-auto -mx-6">
          <table className="w-full text-sm min-w-[660px]">
            <thead>
              <tr className="border-b border-border">
                {['Include', 'Original name', 'Display name', 'Type', 'Missing', ''].map((h) => (
                  <th
                    key={h}
                    className="px-4 pb-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allColumns.map((key) => {
                const col = cols[key];
                const profile = columnProfiles?.[key];
                const missing = health?.missing_per_column?.[key] ?? 0;
                const ratio = totalRows > 0 ? missing / totalRows : profile?.missing_ratio ?? 0;
                const colType = schema[key] ?? profile?.datatype ?? '—';
                const isEditing = editingKey === key;

                return (
                  <tr
                    key={key}
                    className={cn(
                      'border-b border-border/30 transition-colors',
                      col.included ? 'hover:bg-surface/60' : 'opacity-40 bg-border/10'
                    )}
                  >
                    {/* Include toggle */}
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={col.included}
                        onChange={() => toggleInclude(key)}
                        className="h-4 w-4 rounded border-border text-accent focus:ring-accent/40 cursor-pointer"
                        aria-label={`Include ${key}`}
                      />
                    </td>
                    {/* Original */}
                    <td className="px-4 py-3 font-mono text-xs text-text-muted">{key}</td>
                    {/* Display name — editable */}
                    <td className="px-4 py-3">
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onBlur={() => commitEdit(key)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commitEdit(key);
                            if (e.key === 'Escape') setEditingKey(null);
                          }}
                          className="rounded border border-accent px-2 py-1 text-sm font-mono bg-surface focus:outline-none focus:ring-2 focus:ring-accent/30 w-full"
                        />
                      ) : (
                        <span
                          className={cn(
                            'font-mono text-xs',
                            col.displayName !== col.originalName
                              ? 'text-primary font-semibold'
                              : 'text-text'
                          )}
                        >
                          {col.displayName}
                        </span>
                      )}
                    </td>
                    {/* Type */}
                    <td className="px-4 py-3">
                      <Badge variant={colType.includes('int') || colType.includes('float') || colType === 'numeric' ? 'default' : 'muted'}>
                        {colType}
                      </Badge>
                    </td>
                    {/* Missing */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <div className="w-12 h-1.5 rounded-full bg-border overflow-hidden">
                          <div
                            className={cn(
                              'h-full rounded-full',
                              ratio > 0.3 ? 'bg-danger' : ratio > 0.1 ? 'bg-warning' : 'bg-success/60'
                            )}
                            style={{ width: `${Math.min(ratio * 100, 100)}%` }}
                          />
                        </div>
                        <span className="text-xs text-text-muted">
                          {(ratio * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    {/* Actions */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => startEdit(key)}
                          disabled={!col.included}
                          className="p-1 rounded hover:bg-border/60 text-text-muted hover:text-text transition-colors disabled:opacity-30"
                          title="Rename"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => toggleInclude(key)}
                          className={cn(
                            'p-1 rounded transition-colors',
                            col.included
                              ? 'hover:bg-danger/10 text-text-muted hover:text-danger'
                              : 'hover:bg-success/10 text-text-muted hover:text-success'
                          )}
                          title={col.included ? 'Exclude column' : 'Re-include column'}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-border">
        <div className="flex items-center gap-3">
          <Button variant="ghost" onClick={onBack} className="flex items-center gap-1">
            <ChevronLeft className="h-4 w-4" /> Back
          </Button>
          <Button
            variant="outline"
            onClick={resetAll}
            className="flex items-center gap-1 text-text-muted"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </Button>
        </div>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
          <span className="text-sm text-text-muted">
            {includedCount} of {allColumns.length} columns included
          </span>
          <Button onClick={() => onProceed(cols)} size="lg">
            Apply & Proceed to Semantic Mapping →
          </Button>
        </div>
      </div>
    </div>
  );
}
