'use client';

import Card from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import { CheckCircle2, ShieldAlert, Info } from 'lucide-react';

export interface RulesInventoryRow {
  column?: string;
  original_name?: string;
  rule_id?: string;
  rule_type?: string;
  source?: string;
  kind?: string;
  status?: string;
  violation_count?: number;
  matched_via?: string;
  explanation?: string;
  columns?: string[];
}

interface Props {
  inventory: RulesInventoryRow[];
  rulesDiscovered?: number;
  className?: string;
}

function statusVariant(status?: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (status === 'violation') return 'danger';
  if (status === 'passed') return 'success';
  return 'muted';
}

export default function ValidationRulesInventory({
  inventory,
  rulesDiscovered = 0,
  className,
}: Props) {
  const matched = inventory.length;
  const violations = inventory.filter((r) => r.status === 'violation').length;
  const passed = inventory.filter((r) => r.status === 'passed').length;

  if (!inventory.length) {
    return (
      <Card className={cn('border-warning/30 bg-warning/5', className)}>
        <div className="flex gap-3">
          <Info className="h-5 w-5 text-warning shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-text">No rules matched your columns</p>
            <p className="text-text-muted mt-1">
              {rulesDiscovered > 0
                ? `${rulesDiscovered} rules were discovered in the library, but none matched these column names (even after checking raw headers). Statistical rules may still apply on re-analysis.`
                : 'Rule discovery returned no applicable rules for this dataset profile.'}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card
      title={`Rules inventory (${matched} column–rule pairs)`}
      description="Every rule evaluated against your columns — including checks that passed cleanly."
      className={className}
    >
      <div className="flex flex-wrap gap-2 mb-4">
        <Badge variant="success" className="gap-1">
          <CheckCircle2 className="h-3 w-3" /> {passed} passed
        </Badge>
        {violations > 0 && (
          <Badge variant="danger" className="gap-1">
            <ShieldAlert className="h-3 w-3" /> {violations} with violations
          </Badge>
        )}
      </div>
      <div className="overflow-x-auto -mx-6 max-h-[360px] overflow-y-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead className="sticky top-0 bg-surface-card">
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-muted">
              {['Column', 'Raw header', 'Rule', 'Source', 'Match', 'Status', 'Issues'].map((h) => (
                <th key={h} className="px-4 pb-2 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {inventory.map((row, i) => (
              <tr key={`${row.rule_id}-${row.column}-${i}`} className="border-b border-border/30 hover:bg-surface/60">
                <td className="px-4 py-2 font-mono text-xs">{row.column ?? '—'}</td>
                <td className="px-4 py-2 font-mono text-xs text-text-muted">
                  {row.original_name && row.original_name !== row.column ? row.original_name : '—'}
                </td>
                <td className="px-4 py-2 text-xs">
                  <span className="font-mono">{row.rule_id ?? '—'}</span>
                  {row.rule_type && (
                    <span className="block text-[10px] text-text-muted">{row.rule_type}</span>
                  )}
                </td>
                <td className="px-4 py-2 text-xs capitalize">{row.source ?? '—'}</td>
                <td className="px-4 py-2 text-xs capitalize">{row.matched_via ?? '—'}</td>
                <td className="px-4 py-2">
                  <Badge variant={statusVariant(row.status)}>{row.status ?? '—'}</Badge>
                </td>
                <td className="px-4 py-2 text-xs font-mono">{row.violation_count ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
