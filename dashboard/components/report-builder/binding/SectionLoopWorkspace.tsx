'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  ArrowDown,
  ArrowUp,
  Download,
  FileText,
  Filter,
  LayoutPanelTop,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { QueryIndicatorFilters } from '@/components/report-builder/binding/QueryIndicatorFilters';
import { SectionBlockView } from '@/components/report-builder/binding/SectionBlockView';
import type { ReportSectionConfig } from '@/lib/reportSection';
import type { GeneratedSectionBlock, ReportSectionRequest, SectionExecutionResult } from '@/lib/report-section';
import type { DatasetColumnProfile } from '@/lib/api';

// ─────────────────────────────────────────────────────────────────────────────
// Section loop workspace
//   A two-tab loop between the Query interpreter and the Report canvas:
//
//     ┌──────────────┐  generate   ┌──────────────┐  add another  ┌──────────────┐
//     │  Interpreter │ ──────────▶ │    Canvas    │ ────────────▶ │  Interpreter │ …
//     └──────────────┘             └──────────────┘               └──────────────┘
//
//   Each generation appends one section (heading + generated blocks) onto the
//   accumulated canvas. The officer flips back to the interpreter to add the
//   next section — a loop, no backend call. Sections persist per dataset
//   signature so switching workbench tabs never loses the in-progress report.
// ─────────────────────────────────────────────────────────────────────────────

interface AccumulatedSection {
  id: string; // = request.requestId
  request: ReportSectionRequest;
  blocks: GeneratedSectionBlock[];
  meta: { rowsAfterFilter: number; rowsScanned: number; groups: number };
  addedAt: number;
}

interface SectionLoopWorkspaceProps {
  file: File | null;
  columns: DatasetColumnProfile[];
  config: ReportSectionConfig;
  onChange: (config: ReportSectionConfig) => void;
  templateId: string;
  signature: string;
  datasetId: string;
  className?: string;
}

const storageKey = (signature: string) => `section-loop:${signature}`;

export function SectionLoopWorkspace({
  file,
  columns,
  config,
  onChange,
  templateId,
  signature,
  datasetId,
  className,
}: SectionLoopWorkspaceProps) {
  const [tab, setTab] = useState<'interpreter' | 'canvas'>('interpreter');
  const [sections, setSections] = useState<AccumulatedSection[]>([]);
  const hydrated = useRef(false);

  // Hydrate accumulated sections for this dataset signature (deferred so the
  // setState never runs synchronously inside the effect body).
  useEffect(() => {
    hydrated.current = false;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      try {
        const raw = sessionStorage.getItem(storageKey(signature));
        const stored = raw ? (JSON.parse(raw) as AccumulatedSection[]) : [];
        setSections(Array.isArray(stored) ? stored : []);
      } catch {
        setSections([]);
      }
      hydrated.current = true;
    });
    return () => {
      cancelled = true;
    };
  }, [signature]);

  // Persist on change (only after the initial hydrate to avoid clobbering).
  useEffect(() => {
    if (!hydrated.current) return;
    try {
      sessionStorage.setItem(storageKey(signature), JSON.stringify(sections));
    } catch {
      /* storage full / unavailable — non-fatal */
    }
  }, [sections, signature]);

  const totalBlocks = useMemo(() => sections.reduce((n, s) => n + s.blocks.length, 0), [sections]);

  const handleGenerate = (blocks: GeneratedSectionBlock[], request: ReportSectionRequest, execution: SectionExecutionResult) => {
    const entry: AccumulatedSection = {
      id: request.requestId,
      request,
      blocks,
      meta: { rowsAfterFilter: execution.rowsAfterFilter, rowsScanned: execution.rowsScanned, groups: execution.rows.length },
      addedAt: Date.now(),
    };
    setSections((prev) => {
      const idx = prev.findIndex((s) => s.id === entry.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = entry;
        return next;
      }
      return [...prev, entry];
    });
    setTab('canvas');
  };

  const removeSection = (id: string) => setSections((prev) => prev.filter((s) => s.id !== id));
  const moveSection = (id: string, dir: -1 | 1) =>
    setSections((prev) => {
      const idx = prev.findIndex((s) => s.id === id);
      const target = idx + dir;
      if (idx < 0 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  const clearAll = () => setSections([]);

  // Add the next section: bump the section title so the next generation is a
  // distinct section (not an overwrite), then flip to the interpreter.
  const addAnother = () => {
    const base = config.sectionTitle.replace(/\s+\d+$/, '').trim() || 'New Section';
    onChange({ ...config, sectionTitle: `${base} ${sections.length + 1}` });
    setTab('interpreter');
  };

  const downloadBundle = () => {
    const bundle = {
      version: 'report.canvas.bundle.v1',
      templateId,
      signature,
      datasetId,
      generatedAt: new Date().toISOString(),
      sections: sections.map((s) => ({ request: s.request, blocks: s.blocks })),
    };
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report-canvas-${signature.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Downloaded ${sections.length} section(s)`);
  };

  const tabButton = (id: 'interpreter' | 'canvas', label: string, icon: React.ReactNode, count?: number) => (
    <button
      type="button"
      onClick={() => setTab(id)}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
        tab === id ? 'bg-primary text-white shadow-sm' : 'text-text-muted hover:text-text',
      )}
    >
      {icon}
      {label}
      {count !== undefined && count > 0 && (
        <span className={cn('rounded-full px-1.5 text-[10px]', tab === id ? 'bg-white/20' : 'bg-border text-text-muted')}>{count}</span>
      )}
    </button>
  );

  return (
    <div className={cn('space-y-4', className)}>
      {/* Loop tab bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-surface-card px-4 py-3 shadow-sm">
        <div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
          {tabButton('interpreter', 'Query interpreter', <Filter className="h-3.5 w-3.5" aria-hidden />)}
          {tabButton('canvas', 'Report canvas', <LayoutPanelTop className="h-3.5 w-3.5" aria-hidden />, sections.length)}
        </div>
        <div className="flex items-center gap-3 text-xs text-text-muted">
          <span className="hidden sm:inline">
            {sections.length} section{sections.length === 1 ? '' : 's'} · {totalBlocks} block{totalBlocks === 1 ? '' : 's'}
          </span>
          {sections.length > 0 && (
            <Button type="button" variant="outline" size="sm" onClick={downloadBundle}>
              <Download className="h-3.5 w-3.5" /> Bundle
            </Button>
          )}
        </div>
      </div>

      {/* Interpreter tab */}
      {tab === 'interpreter' && (
        <QueryIndicatorFilters
          file={file}
          columns={columns}
          config={config}
          onChange={onChange}
          templateId={templateId}
          signature={signature}
          datasetId={datasetId}
          onGenerate={handleGenerate}
          hidePreview
          generateLabel="Generate & add to canvas"
        />
      )}

      {/* Canvas tab */}
      {tab === 'canvas' && (
        <div className="space-y-4">
          {sections.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border bg-surface-card p-10 text-center">
              <LayoutPanelTop className="mx-auto h-7 w-7 text-text-muted" aria-hidden />
              <h3 className="mt-2 text-sm font-semibold text-text">No sections yet</h3>
              <p className="mt-1 text-xs text-text-muted">Build a section in the query interpreter and it will appear here.</p>
              <Button type="button" size="sm" className="mt-3" onClick={() => setTab('interpreter')}>
                <Filter className="h-4 w-4" /> Go to query interpreter
              </Button>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-border bg-surface-card px-5 py-3 shadow-sm">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-primary" aria-hidden />
                  <h3 className="text-sm font-semibold text-text">Report canvas</h3>
                  <Badge variant="muted" className="text-[9px]">{sections.length} section{sections.length === 1 ? '' : 's'}</Badge>
                </div>
                <div className="flex items-center gap-1.5">
                  <Button type="button" size="sm" onClick={addAnother}>
                    <Plus className="h-4 w-4" /> Add another section
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={clearAll} className="text-danger hover:bg-danger/10">
                    <RefreshCw className="h-3.5 w-3.5" /> Clear
                  </Button>
                </div>
              </div>

              {sections.map((section, idx) => {
                const chapter = section.request.target.chapter?.title;
                const sectionTitle = section.request.target.section?.title || section.request.description.text || 'Section';
                const filterText = section.request.scope.filters
                  .map((f) => `${f.col} ${f.op} ${Array.isArray(f.value) ? `[${f.value.join(', ')}]` : String(f.value ?? '')}`)
                  .join(` ${'AND'} `);
                return (
                  <div key={section.id} className="space-y-3 rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
                      <div className="min-w-0">
                        {chapter && <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">{chapter}</p>}
                        <h4 className="text-base font-semibold text-text">{sectionTitle}</h4>
                        <p className="mt-0.5 text-[11px] text-text-muted">
                          {section.meta.rowsAfterFilter.toLocaleString('en-IN')} of {section.meta.rowsScanned.toLocaleString('en-IN')} rows · {section.meta.groups} group(s)
                          {filterText ? <> · <span className="font-mono">WHERE {filterText}</span></> : null}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => moveSection(section.id, -1)}
                          disabled={idx === 0}
                          title="Move up"
                          className="rounded-md border border-border p-1.5 text-text-muted transition-colors hover:text-primary disabled:opacity-30"
                        >
                          <ArrowUp className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => moveSection(section.id, 1)}
                          disabled={idx === sections.length - 1}
                          title="Move down"
                          className="rounded-md border border-border p-1.5 text-text-muted transition-colors hover:text-primary disabled:opacity-30"
                        >
                          <ArrowDown className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => removeSection(section.id)}
                          title="Remove section"
                          className="rounded-md border border-border p-1.5 text-text-muted transition-colors hover:bg-danger/10 hover:text-danger"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    <div className="space-y-3">
                      {section.blocks.map((b) => <SectionBlockView key={b.id} block={b} />)}
                    </div>
                  </div>
                );
              })}

              <div className="flex justify-center">
                <Button type="button" variant="outline" onClick={addAnother}>
                  <Plus className="h-4 w-4" /> Add another section
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default SectionLoopWorkspace;
