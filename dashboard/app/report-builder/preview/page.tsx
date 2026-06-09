'use client';

/**
 * R3 — live report preview route: `/report-builder/preview?tid=…&sig=…`.
 * Fetches the report AST and renders it with the interactive React preview
 * (ECharts + tables + provenance). A tab switches to the canonical server HTML,
 * and the PDF can be downloaded on demand.
 */
import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ArrowLeft, Download, Languages, Loader2, SlidersHorizontal } from 'lucide-react';
import Link from 'next/link';

import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { generatePhaseApi } from '@/lib/api';
import type { Locale, ReportAST } from '@/lib/report/types';
import { applyProfile, type ReportOverrides } from '@/lib/report/profile';
import { ReportPreview } from '@/components/report-builder/render/ReportPreview';
import { CustomizePanel } from '@/components/report-builder/render/CustomizePanel';

function PreviewInner() {
  const sp = useSearchParams();
  const tid = sp.get('tid') ?? '';
  const sig = sp.get('sig') ?? '';

  const [report, setReport] = useState<ReportAST | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [locale, setLocale] = useState<Locale>('en-IN');
  const [tab, setTab] = useState<'react' | 'html'>('react');
  const [overrides, setOverrides] = useState<ReportOverrides>({});
  const [customizing, setCustomizing] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!tid || !sig) {
      setError('Missing template id or signature in the URL.');
      return;
    }
    let cancelled = false;
    generatePhaseApi
      .getReport(tid, sig)
      .then((r) => {
        if (!cancelled) setReport(r as ReportAST);
      })
      .catch(() => {
        if (!cancelled) setError('No report found — generate it first.');
      });
    generatePhaseApi
      .getOverrides(tid, sig)
      .then((o) => {
        if (!cancelled) setOverrides(o as ReportOverrides);
      })
      .catch(() => {
        /* no overrides saved yet — fine */
      });
    return () => {
      cancelled = true;
    };
  }, [tid, sig]);

  const shaped = useMemo(
    () => (report ? applyProfile(report, overrides) : null),
    [report, overrides],
  );
  const previewLocale = (overrides.locale as Locale) ?? locale;
  const previewNumberSystem = overrides.numberSystem ?? 'indian';

  const saveOverrides = async () => {
    setSaving(true);
    try {
      await generatePhaseApi.patchOverrides(tid, sig, overrides as Record<string, unknown>);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Report preview"
        description="Interactive preview rendered from the report AST."
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-lg border border-border p-0.5">
          <TabButton active={tab === 'react'} onClick={() => setTab('react')}>
            Interactive
          </TabButton>
          <TabButton active={tab === 'html'} onClick={() => setTab('html')}>
            Server HTML
          </TabButton>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant={customizing ? 'secondary' : 'outline'}
            size="sm"
            onClick={() => setCustomizing((c) => !c)}
          >
            <SlidersHorizontal className="h-4 w-4" /> Customize
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setLocale((l) => (l === 'hi-IN' ? 'en-IN' : 'hi-IN'))}
          >
            <Languages className="h-4 w-4" />
            {locale === 'hi-IN' ? 'हिन्दी' : 'English'}
          </Button>
          <a
            href={generatePhaseApi.reportPdfUrl(tid, sig, { locale })}
            target="_blank"
            rel="noreferrer"
          >
            <Button variant="outline" size="sm">
              <Download className="h-4 w-4" /> PDF
            </Button>
          </a>
          <Link href="/report-builder/binding">
            <Button variant="ghost" size="sm" className="text-text-muted">
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
          </Link>
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      {!error && !report && (
        <div className="flex items-center gap-2 py-12 text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading report…
        </div>
      )}

      {report && tab === 'react' && (
        <div className="flex gap-4">
          <div className="min-w-0 flex-1 rounded-lg border border-border bg-surface">
            <ReportPreview
              report={shaped ?? report}
              locale={previewLocale}
              numberSystem={previewNumberSystem}
            />
          </div>
          {customizing && (
            <div className="hidden w-80 shrink-0 lg:block">
              <CustomizePanel
                report={report}
                value={overrides}
                onChange={setOverrides}
                onSave={saveOverrides}
                saving={saving}
              />
            </div>
          )}
        </div>
      )}

      {report && tab === 'html' && (
        <div className="overflow-hidden rounded-lg border border-border">
          <iframe
            title="Server-rendered report"
            src={generatePhaseApi.reportHtmlUrl(tid, sig)}
            className="h-[75vh] w-full bg-white"
          />
        </div>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
        active ? 'bg-accent text-white' : 'text-text-muted hover:text-text'
      }`}
    >
      {children}
    </button>
  );
}

export default function ReportPreviewPage() {
  return (
    <Suspense fallback={<div className="p-8 text-text-muted">Loading…</div>}>
      <PreviewInner />
    </Suspense>
  );
}
