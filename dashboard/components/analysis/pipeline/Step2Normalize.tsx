'use client';

import { useMemo, useState } from 'react';
import { AnalysisResult } from '@/lib/api';
import { buildNormalizationPlan } from '@/lib/columnNormalization';
import { Button } from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import { Pencil, Trash2, RotateCcw, CheckCircle2, ChevronLeft, Info } from 'lucide-react';

export interface ColumnDecision {
  originalName: string;
  displayName: string;
  suggestedName: string;
  normalizedName: string;
  domain?: string;
  matchMethod?: string;
  matchConfidence?: number;
  included: boolean;
  isDeleted: boolean;
  typeOverride?: string;
}

interface Props {
  results: AnalysisResult;
  decisions: Record<string, ColumnDecision>;
  onProceed: (decisions: Record<string, ColumnDecision>) => void;
  onBack: () => void;
  saving?: boolean;
}

function methodVariant(method: string): 'success' | 'warning' | 'default' | 'muted' {
  const m = method.toLowerCase();
  if (m.includes('rapidfuzz') || m.includes('ontology') || m.includes('suffix') || m.includes('lock')) return 'success';
  if (m.includes('dynamic') || m.includes('cluster')) return 'warning';
  if (m.includes('embedding')) return 'default';
  if (m.includes('legacy')) return 'muted';
  return 'muted';
}

export default function Step2Normalize({ results, decisions, onProceed, onBack, saving }: Props) {
  const plan = useMemo(() => buildNormalizationPlan(results), [results]);

  const health = results.health as {
    rows?: number;
    missing_per_column?: Record<string, number>;
    dtypes?: Record<string, string>;
  } | undefined;
  const columnProfiles = results.column_profiles;
  const schema = results.schema ?? {};
  const totalRows = health?.rows ?? 0;

  const [cols, setCols] = useState<Record<string, ColumnDecision>>(() => {
    const init: Record<string, ColumnDecision> = {};
    plan.forEach((p) => {
      init[p.originalName] = decisions[p.originalName] ?? {
        originalName: p.originalName,
        displayName: p.displayName,
        suggestedName: p.displayName,
        normalizedName: p.normalizedName,
        domain: p.domain,
        matchMethod: p.matchMethod,
        matchConfidence: p.matchConfidence,
        included: true,
        isDeleted: false,
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
      [key]: { ...prev[key], included: !prev[key].included, isDeleted: false },
    }));
  };
  const markDeleted = (key: string) => {
    setCols((prev) => ({
      ...prev,
      [key]: { ...prev[key], isDeleted: true, included: false },
    }));
  };
  const restoreColumn = (key: string) => {
    setCols((prev) => ({
      ...prev,
      [key]: { ...prev[key], isDeleted: false, included: true },
    }));
  };
  const resetAll = () => {
    setCols(() => {
      const next: Record<string, ColumnDecision> = {};
      plan.forEach((p) => {
        next[p.originalName] = {
          originalName: p.originalName,
          displayName: p.displayName,
          suggestedName: p.displayName,
          normalizedName: p.normalizedName,
          domain: p.domain,
          matchMethod: p.matchMethod,
          matchConfidence: p.matchConfidence,
          included: true,
          isDeleted: false,
        };
      });
      return next;
    });
  };

  const includedCount = Object.values(cols).filter((c) => c.included && !c.isDeleted).length;
  const excludedCount = Object.values(cols).filter((c) => !c.included && !c.isDeleted).length;
  const deletedCount = Object.values(cols).filter((c) => c.isDeleted).length;
  const renamedCount = Object.values(cols).filter(
    (c) => c.displayName !== c.suggestedName
  ).length;

  return (
    <div className="space-y-6">
      <Card className="border-primary/20 bg-primary/5">
        <div className="flex gap-3">
          <Info className="h-5 w-5 text-primary shrink-0 mt-0.5" />
          <div className="text-sm text-text-muted">
            <p className="font-semibold text-text mb-1">Normalisation layer (audit checkpoint)</p>
            <p>
              Column names are expanded and normalised here: abbreviation resolution, camelCase
              splitting, and token title-casing. Domain prefixes such as{' '}
              <strong>Geography · Sector</strong> are assigned in the{' '}
              <strong>Semantic Mapping</strong> step (Step 3) — not here. The match method badge
              shows which normalisation path resolved each token (RapidFuzz ontology lookup,
              schema suffix detection, or embedding fallback).
            </p>
          </div>
        </div>
      </Card>

      <div className="flex flex-wrap gap-3">
        <Badge variant="success">{includedCount} included</Badge>
        {excludedCount > 0 && <Badge variant="warning">{excludedCount} excluded</Badge>}
        {deletedCount > 0 && <Badge variant="danger">{deletedCount} deleted</Badge>}
        {renamedCount > 0 && <Badge variant="default">{renamedCount} renamed</Badge>}
      </div>

      <Card
        title="Column normalisation"
        description="Review pipeline-generated full names. Edit, exclude columns, or confirm before semantic mapping."
      >
        <div className="overflow-x-auto -mx-6">
          <table className="w-full text-sm min-w-[900px]">
            <thead>
              <tr className="border-b border-border">
                {[
                  'Include',
                  'Original column',
                  'Expanded name',
                  'Normalised display name',
                  'Expansion method',
                  'Type',
                  'Missing',
                  '',
                ].map((h) => (
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
              {plan.map((p) => {
                const col = cols[p.originalName];
                if (!col) return null;
                const profile = columnProfiles?.[p.originalName] as
                  | { missing_ratio?: number; datatype?: string }
                  | undefined;
                const missing = health?.missing_per_column?.[p.originalName] ?? 0;
                const ratio =
                  totalRows > 0 ? missing / totalRows : profile?.missing_ratio ?? 0;
                const colType = schema[p.originalName] ?? profile?.datatype ?? '—';
                const isEditing = editingKey === p.originalName;
                const edited = col.displayName !== col.suggestedName;

                return (
                  <tr
                    key={p.originalName}
                    className={cn(
                      'border-b border-border/30 transition-colors',
                      col.isDeleted
                        ? 'opacity-30 line-through bg-danger/5'
                        : col.included
                        ? 'hover:bg-surface/60'
                        : 'opacity-50 bg-border/10'
                    )}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={col.included && !col.isDeleted}
                        onChange={() => toggleInclude(p.originalName)}
                        disabled={col.isDeleted}
                        className="h-4 w-4 rounded border-border text-accent focus:ring-accent/40 cursor-pointer"
                        aria-label={`Include ${p.originalName}`}
                      />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-text-muted">
                      {p.originalName}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted capitalize">
                      {p.normalizedName}
                    </td>
                    <td className="px-4 py-3 min-w-[200px]">
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onBlur={() => commitEdit(p.originalName)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commitEdit(p.originalName);
                            if (e.key === 'Escape') setEditingKey(null);
                          }}
                          className="rounded border border-accent px-2 py-1 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent/30 w-full"
                        />
                      ) : (
                        <span
                          className={cn(
                            'text-sm font-medium',
                            edited ? 'text-warning' : 'text-primary'
                          )}
                        >
                          {col.displayName}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={methodVariant(p.matchMethod)} className="text-[10px]">
                        {p.matchMethod}
                      </Badge>
                      {p.matchConfidence != null && (
                        <span className="block text-[10px] text-text-muted mt-1">
                          {(p.matchConfidence * 100).toFixed(0)}% conf.
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant={
                          colType.includes('int') ||
                          colType.includes('float') ||
                          colType === 'numeric'
                            ? 'default'
                            : 'muted'
                        }
                      >
                        {colType}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <div className="w-12 h-1.5 rounded-full bg-border overflow-hidden">
                          <div
                            className={cn(
                              'h-full rounded-full',
                              ratio > 0.3
                                ? 'bg-danger'
                                : ratio > 0.1
                                ? 'bg-warning'
                                : 'bg-success/60'
                            )}
                            style={{ width: `${Math.min(ratio * 100, 100)}%` }}
                          />
                        </div>
                        <span className="text-xs text-text-muted">
                          {(ratio * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => startEdit(p.originalName)}
                          disabled={!col.included}
                          className="p-1 rounded hover:bg-border/60 text-text-muted hover:text-text transition-colors disabled:opacity-30"
                          title="Edit display name"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            col.isDeleted
                              ? restoreColumn(p.originalName)
                              : markDeleted(p.originalName)
                          }
                          className={cn(
                            'p-1 rounded transition-colors',
                            col.isDeleted
                              ? 'hover:bg-success/10 text-success'
                              : 'hover:bg-danger/10 text-text-muted hover:text-danger'
                          )}
                          title={col.isDeleted ? 'Restore column' : 'Delete column'}
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
            <RotateCcw className="h-3.5 w-3.5" /> Reset to pipeline names
          </Button>
        </div>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
          <span className="text-sm text-text-muted">
            {includedCount} of {plan.length} columns confirmed for semantic mapping
          </span>
          <Button onClick={() => onProceed(cols)} size="lg" disabled={saving}>
            {saving ? 'Saving…' : 'Confirm normalisation & Proceed →'}
          </Button>
        </div>
      </div>
    </div>
  );
}
