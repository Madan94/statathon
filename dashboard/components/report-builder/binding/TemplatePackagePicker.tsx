'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Database, Loader2, Search, SlidersHorizontal, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';
import type { BindingTemplatePackage } from '@/lib/api';

type SourceFilter = 'all' | 'built_in' | 'db';
type StatusFilter = 'all' | 'valid' | 'needs_review' | 'rich';
type SortMode = 'recommended' | 'newest' | 'richness' | 'questions' | 'name';

interface TemplatePackagePickerProps {
  packages: BindingTemplatePackage[];
  selectedTemplateId: string;
  loading?: boolean;
  onSelect: (templateId: string) => void;
}

const SOURCE_OPTIONS: Array<{ value: SourceFilter; label: string }> = [
  { value: 'all', label: 'All sources' },
  { value: 'built_in', label: 'Built-in' },
  { value: 'db', label: 'Extracted' },
];

const STATUS_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: 'All templates' },
  { value: 'valid', label: 'Valid only' },
  { value: 'rich', label: 'Rich templates' },
  { value: 'needs_review', label: 'Needs review' },
];

const SORT_OPTIONS: Array<{ value: SortMode; label: string }> = [
  { value: 'recommended', label: 'Recommended' },
  { value: 'newest', label: 'Newest' },
  { value: 'richness', label: 'Richest' },
  { value: 'questions', label: 'Most questions' },
  { value: 'name', label: 'Name A-Z' },
];

function statusVariant(status: string, source: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (status === 'VALID') return 'success';
  if (status === 'INVALID') return 'danger';
  if (source === 'built_in') return 'muted';
  return 'warning';
}

function sourceLabel(pkg: BindingTemplatePackage): string {
  return pkg.source === 'built_in' ? 'Built-in' : `Template ${pkg.template_id}`;
}

function packageSearchText(pkg: BindingTemplatePackage): string {
  return [
    pkg.template_id,
    pkg.name,
    pkg.source,
    pkg.status,
    pkg.version,
    pkg.domain,
    pkg.report_type,
    pkg.description,
  ].filter(Boolean).join(' ').toLowerCase();
}

function updatedTime(pkg: BindingTemplatePackage): number {
  if (!pkg.updated_at) return 0;
  const parsed = Date.parse(pkg.updated_at);
  return Number.isFinite(parsed) ? parsed : 0;
}

function richness(pkg: BindingTemplatePackage): number {
  return pkg.richness_score
    ?? (
      pkg.topics_count * 6
      + (pkg.chapters_count ?? 0) * 3
      + (pkg.sections_count ?? 0) * 2
      + pkg.questions_count * 1.5
      + pkg.entities_count
      + pkg.chart_slots_count * 1.2
      + pkg.table_slots_count * 1.2
    );
}

function isRich(pkg: BindingTemplatePackage): boolean {
  return pkg.questions_count >= 12
    || pkg.topics_count >= 5
    || pkg.chart_slots_count + pkg.table_slots_count >= 8
    || richness(pkg) >= 80;
}

function compareRecommended(a: BindingTemplatePackage, b: BindingTemplatePackage): number {
  const aBuiltIn = a.source === 'built_in' ? 1 : 0;
  const bBuiltIn = b.source === 'built_in' ? 1 : 0;
  if (aBuiltIn !== bBuiltIn) return bBuiltIn - aBuiltIn;
  const aValid = a.status === 'VALID' ? 1 : 0;
  const bValid = b.status === 'VALID' ? 1 : 0;
  if (aValid !== bValid) return bValid - aValid;
  const richDiff = richness(b) - richness(a);
  if (richDiff !== 0) return richDiff;
  return updatedTime(b) - updatedTime(a);
}

function dateLabel(pkg: BindingTemplatePackage): string | null {
  if (!pkg.updated_at) return null;
  const parsed = Date.parse(pkg.updated_at);
  if (!Number.isFinite(parsed)) return null;
  return new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(parsed);
}

function stat(label: string, value: number | undefined) {
  return (
    <span className="whitespace-nowrap rounded-lg bg-surface px-2 py-1">
      <strong className="text-text">{value ?? 0}</strong> {label}
    </span>
  );
}

export function TemplatePackagePicker({
  packages,
  selectedTemplateId,
  loading = false,
  onSelect,
}: TemplatePackagePickerProps) {
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>('recommended');
  const [previewTemplateId, setPreviewTemplateId] = useState(selectedTemplateId);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const selectedPackage = useMemo(
    () => packages.find((pkg) => pkg.template_id === selectedTemplateId) ?? null,
    [packages, selectedTemplateId]
  );

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const items = packages.filter((pkg) => {
      if (sourceFilter !== 'all' && pkg.source !== sourceFilter) return false;
      if (statusFilter === 'valid' && pkg.status !== 'VALID') return false;
      if (statusFilter === 'needs_review' && pkg.status === 'VALID') return false;
      if (statusFilter === 'rich' && !isRich(pkg)) return false;
      if (normalized && !packageSearchText(pkg).includes(normalized)) return false;
      return true;
    });
    return [...items].sort((a, b) => {
      if (sortMode === 'newest') return updatedTime(b) - updatedTime(a);
      if (sortMode === 'richness') return richness(b) - richness(a);
      if (sortMode === 'questions') return b.questions_count - a.questions_count;
      if (sortMode === 'name') return a.name.localeCompare(b.name);
      return compareRecommended(a, b);
    });
  }, [packages, query, sortMode, sourceFilter, statusFilter]);

  const previewPackage = useMemo(
    () => packages.find((pkg) => pkg.template_id === previewTemplateId)
      ?? selectedPackage
      ?? filtered[0]
      ?? null,
    [filtered, packages, previewTemplateId, selectedPackage]
  );

  useEffect(() => {
    setPreviewTemplateId(selectedTemplateId);
  }, [selectedTemplateId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.isContentEditable) return;
      event.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-success/20 bg-success/5 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-success">Selected template</p>
            <p className="mt-1 break-words text-base font-semibold leading-snug text-text">
              {selectedPackage?.name ?? selectedTemplateId}
            </p>
            <p className="mt-1 break-words text-xs text-text-muted">
              {selectedPackage
                ? `${sourceLabel(selectedPackage)} - v${selectedPackage.version}`
                : 'Manual template id. Use the advanced field to change it directly.'}
            </p>
          </div>
          {selectedPackage && (
            <Badge variant={statusVariant(selectedPackage.status, selectedPackage.source)} className="shrink-0">
              {selectedPackage.status}
            </Badge>
          )}
        </div>
        {selectedPackage && (
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
            {stat('topics', selectedPackage.topics_count)}
            {stat('chapters', selectedPackage.chapters_count)}
            {stat('sections', selectedPackage.sections_count)}
            {stat('questions', selectedPackage.questions_count)}
            {stat('entities', selectedPackage.entities_count)}
          </div>
        )}
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-text">Template catalog</p>
            <p className="text-xs text-text-muted">
              {filtered.length} of {packages.length} templates shown. Press / to search.
            </p>
          </div>
          {loading && <Loader2 className="h-4 w-4 animate-spin text-text-muted" />}
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_240px]">
          <div className="min-w-0 space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-text-muted" />
              <input
                ref={searchRef}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by name, id, domain, source, or description"
                className="w-full rounded-lg border border-border bg-surface-card py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
              />
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              <label className="text-xs font-medium text-text-muted">
                Source
                <select
                  value={sourceFilter}
                  onChange={(event) => setSourceFilter(event.target.value as SourceFilter)}
                  className="mt-1 w-full rounded-lg border border-border bg-surface-card px-2 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent/40"
                >
                  {SOURCE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-medium text-text-muted">
                Filter
                <select
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
                  className="mt-1 w-full rounded-lg border border-border bg-surface-card px-2 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent/40"
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-medium text-text-muted">
                Sort
                <select
                  value={sortMode}
                  onChange={(event) => setSortMode(event.target.value as SortMode)}
                  className="mt-1 w-full rounded-lg border border-border bg-surface-card px-2 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent/40"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="max-h-[420px] overflow-y-auto rounded-xl border border-border bg-surface-card">
              {filtered.map((pkg) => {
                const selected = pkg.template_id === selectedTemplateId;
                const rich = isRich(pkg);
                return (
                  <button
                    key={`${pkg.source}-${pkg.template_id}`}
                    type="button"
                    onClick={() => {
                      onSelect(pkg.template_id);
                      setPreviewTemplateId(pkg.template_id);
                    }}
                    onFocus={() => setPreviewTemplateId(pkg.template_id)}
                    onMouseEnter={() => setPreviewTemplateId(pkg.template_id)}
                    className={cn(
                      'flex w-full min-w-0 items-start gap-3 border-b border-border px-3 py-3 text-left transition-colors last:border-b-0',
                      selected ? 'bg-primary/5 ring-1 ring-inset ring-primary/25' : 'hover:bg-accent-muted/40'
                    )}
                  >
                    <span className={cn(
                      'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                      pkg.source === 'built_in' ? 'bg-primary/10 text-primary' : 'bg-border text-text-muted'
                    )}>
                      {pkg.source === 'built_in' ? <Sparkles className="h-4 w-4" /> : <Database className="h-4 w-4" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="min-w-0 break-words text-sm font-semibold leading-snug text-text">{pkg.name}</span>
                        {selected && <CheckCircle2 className="h-4 w-4 text-success" />}
                        {rich && <span className="shrink-0 rounded-full bg-accent-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">Rich</span>}
                      </span>
                      <span className="mt-1 block break-words text-xs text-text-muted">
                        {sourceLabel(pkg)} - {pkg.topics_count} topics - {pkg.questions_count} questions - {pkg.entities_count} entities
                      </span>
                    </span>
                    <Badge variant={statusVariant(pkg.status, pkg.source)} className="shrink-0">{pkg.status}</Badge>
                  </button>
                );
              })}
              {!loading && filtered.length === 0 && (
                <div className="p-5 text-sm text-text-muted">
                  No templates match this search. Clear filters or use the manual template id in advanced controls.
                </div>
              )}
            </div>
          </div>

          <aside className="min-w-0 rounded-xl border border-border bg-surface-card p-3">
            <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
              <SlidersHorizontal className="h-4 w-4" /> Preview
            </div>
            {previewPackage ? (
              <div className="space-y-3">
                <div>
                  <p className="break-words text-sm font-semibold leading-snug text-text">{previewPackage.name}</p>
                  <p className="mt-1 break-words text-xs text-text-muted">{previewPackage.description || 'No description provided.'}</p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-text-muted">
                  {stat('topics', previewPackage.topics_count)}
                  {stat('chapters', previewPackage.chapters_count)}
                  {stat('sections', previewPackage.sections_count)}
                  {stat('questions', previewPackage.questions_count)}
                  {stat('charts', previewPackage.chart_slots_count)}
                  {stat('tables', previewPackage.table_slots_count)}
                </div>
                <div className="space-y-1 text-xs text-text-muted">
                  <p className="break-words"><span className="font-medium text-text">ID:</span> {previewPackage.template_id}</p>
                  <p className="break-words"><span className="font-medium text-text">Domain:</span> {previewPackage.domain || 'unspecified'}</p>
                  <p><span className="font-medium text-text">Updated:</span> {dateLabel(previewPackage) || 'bundled'}</p>
                  <p><span className="font-medium text-text">Readiness:</span> {previewPackage.diagnostics_score ?? 'not scored'}</p>
                </div>
                {previewPackage.template_id !== selectedTemplateId && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={() => onSelect(previewPackage.template_id)}
                  >
                    Select this template
                  </Button>
                )}
              </div>
            ) : (
              <p className="text-sm text-text-muted">Load templates to preview their binder coverage.</p>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}

export default TemplatePackagePicker;
