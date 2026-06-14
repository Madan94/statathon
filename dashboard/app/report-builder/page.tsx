'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock,
  Database,
  FileText,
  FunctionSquare,
  Layers,
  Loader2,
  Plus,
  Sparkles,
  Table2,
  Zap,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { bindingPhaseApi, reportBuilderApi, type BindingTemplatePackage } from '@/lib/api';

interface RecentJob {
  id: number;
  analysis_id: number;
  status: string;
  created_at?: string | null;
  template_id?: number | null;
  total_blocks?: number;
}

function statusBadge(status: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (status === 'exported' || status === 'verified' || status === 'complete') return 'success';
  if (status === 'generating' || status === 'pending' || status === 'running') return 'warning';
  if (status === 'failed' || status === 'error') return 'danger';
  return 'muted';
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return 'unknown';
  const d = Date.parse(dateStr);
  if (!Number.isFinite(d)) return dateStr;
  const diff = Date.now() - d;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function ReportBuilderLandingPage() {
  const [templates, setTemplates] = useState<BindingTemplatePackage[]>([]);
  const [jobs, setJobs] = useState<RecentJob[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      bindingPhaseApi.listTemplatePackages(),
      reportBuilderApi.listJobs().catch(() => []),
    ]).then(([tplResult, jobResult]) => {
      if (cancelled) return;
      if (tplResult.status === 'fulfilled') setTemplates(tplResult.value);
      if (jobResult.status === 'fulfilled') setJobs(Array.isArray(jobResult.value) ? jobResult.value.slice(0, 5) : []);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  const validTemplates = templates.filter((t) => t.status === 'VALID');
  const richTemplates = templates.filter((t) =>
    t.questions_count >= 12 || t.topics_count >= 5 || t.chart_slots_count + t.table_slots_count >= 8
  );

  return (
    <div className="mx-auto max-w-6xl space-y-8 pb-12">
      <PageHeader
        title="Report Builder"
        description="Turn raw datasets into publication-grade intelligence reports with AI-assisted binding, officer review, and per-component generation."
        actions={
          <Link href="/report-builder/binding">
            <Button size="sm">
              <Plus className="h-4 w-4" /> New binding session
            </Button>
          </Link>
        }
      />

      {/* Hero cards row */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Link href="/report-builder/binding" className="group">
          <div className="rounded-2xl border border-border bg-gradient-to-br from-primary/5 via-surface-card to-surface p-6 shadow-sm transition-all hover:border-primary/40 hover:shadow-md">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Database className="h-6 w-6" />
            </div>
            <h3 className="mt-4 text-base font-bold text-text">Dataset Binder</h3>
            <p className="mt-1 text-sm text-text-muted">
              Upload a CSV, match columns to template entities, review the question plan, and prepare for generation.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-primary group-hover:underline">
              Start binding <ArrowRight className="h-3 w-3" />
            </span>
          </div>
        </Link>

        <Link href="/report-builder/canvas" className="group">
          <div className="rounded-2xl border border-border bg-gradient-to-br from-accent/5 via-surface-card to-surface p-6 shadow-sm transition-all hover:border-accent/40 hover:shadow-md">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent">
              <BookOpen className="h-6 w-6" />
            </div>
            <h3 className="mt-4 text-base font-bold text-text">Report Canvas</h3>
            <p className="mt-1 text-sm text-text-muted">
              Generate components, edit the document, chat with Deep BI Agent, and export publication-ready reports.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-accent group-hover:underline">
              Open canvas <ArrowRight className="h-3 w-3" />
            </span>
          </div>
        </Link>

        <Link href="/report/report-ast-generator" className="group">
          <div className="rounded-2xl border border-border bg-gradient-to-br from-success/5 via-surface-card to-surface p-6 shadow-sm transition-all hover:border-success/40 hover:shadow-md">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-success/10 text-success">
              <Sparkles className="h-6 w-6" />
            </div>
            <h3 className="mt-4 text-base font-bold text-text">Template Extraction</h3>
            <p className="mt-1 text-sm text-text-muted">
              {loading ? 'Loading...' : `${templates.length} templates available · ${validTemplates.length} valid · ${richTemplates.length} rich`}
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-success group-hover:underline">
              Manage templates <ArrowRight className="h-3 w-3" />
            </span>
          </div>
        </Link>
      </div>

      {/* Workflow steps */}
      <Card title="How it works" description="The binding-first pipeline in four phases.">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { step: 'S0–S1', title: 'Profile & Propose', desc: 'Upload CSV + pick template. The binder profiles columns, detects roles, and proposes entity matches.', icon: Database, color: 'text-primary bg-primary/10' },
            { step: 'S2–S3', title: 'Review & Finalize', desc: 'Confirm or override each entity match. Build the officer-reviewed question plan. Check coverage.', icon: CheckCircle2, color: 'text-success bg-success/10' },
            { step: 'S3.5', title: 'Execution Handoff', desc: 'Prepare the canonical ExecutionBundle. Blocked questions are flagged. Ready plans get S4 dispatch.', icon: Zap, color: 'text-warning bg-warning/10' },
            { step: 'S4–S6', title: 'Generate & Render', desc: 'Per-component generation with AI narration. Auto or step-by-step. A4 document canvas with inline editing.', icon: BookOpen, color: 'text-accent bg-accent/10' },
          ].map(({ step, title, desc, icon: Icon, color }) => (
            <div key={step} className="rounded-xl border border-border bg-surface p-4">
              <div className="flex items-center gap-2">
                <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${color}`}>
                  <Icon className="h-4 w-4" />
                </span>
                <Badge variant="muted" className="text-[9px]">{step}</Badge>
              </div>
              <h4 className="mt-3 text-sm font-bold text-text">{title}</h4>
              <p className="mt-1 text-xs leading-relaxed text-text-muted">{desc}</p>
            </div>
          ))}
        </div>
      </Card>

      {/* Template catalog + recent jobs side by side */}
      <div className="grid gap-5 xl:grid-cols-[1fr_20rem]">
        {/* Template catalog preview */}
        <Card title="Template catalog" description={`${templates.length} templates available for binding.`}>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-text-muted" />
            </div>
          ) : templates.length === 0 ? (
            <div className="py-6 text-center text-sm text-text-muted">
              No templates found. Create one from a MoSPI PDF or import a JSON AST.
            </div>
          ) : (
            <div className="space-y-2">
              {templates.slice(0, 6).map((pkg) => (
                <div
                  key={`${pkg.source}-${pkg.template_id}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-2.5 text-sm transition-colors hover:bg-surface-card"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${pkg.source === 'built_in' ? 'bg-primary/10 text-primary' : 'bg-border text-text-muted'}`}>
                      {pkg.source === 'built_in' ? <Sparkles className="h-4 w-4" /> : <Layers className="h-4 w-4" />}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate font-medium text-text">{pkg.name}</p>
                      <p className="text-xs text-text-muted">
                        {pkg.topics_count} topics · {pkg.questions_count} questions · {pkg.entities_count} entities
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {pkg.chart_slots_count > 0 && <span className="flex items-center gap-0.5 text-[10px] text-text-muted"><BarChart3 className="h-3 w-3" />{pkg.chart_slots_count}</span>}
                    {pkg.table_slots_count > 0 && <span className="flex items-center gap-0.5 text-[10px] text-text-muted"><Table2 className="h-3 w-3" />{pkg.table_slots_count}</span>}
                    <Badge variant={pkg.status === 'VALID' ? 'success' : 'warning'} className="text-[9px]">{pkg.status}</Badge>
                  </div>
                </div>
              ))}
              {templates.length > 6 && (
                <Link href="/report-builder/binding" className="flex items-center justify-center gap-1 rounded-lg py-2 text-xs font-medium text-primary hover:underline">
                  View all {templates.length} templates <ChevronRight className="h-3 w-3" />
                </Link>
              )}
            </div>
          )}
        </Card>

        {/* Recent jobs */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Recent jobs</h3>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-text-muted" />
            </div>
          ) : jobs.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface p-4 text-center text-xs text-text-muted">
              No report jobs yet. Start a binding session to generate your first report.
            </div>
          ) : (
            jobs.map((job) => (
              <Link key={job.id} href={`/report-builder/${job.id}`}>
                <div className="rounded-lg border border-border bg-surface-card px-3 py-2.5 text-xs transition-colors hover:border-primary/30">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-text">Job #{job.id}</span>
                    <Badge variant={statusBadge(job.status)} className="text-[9px]">{job.status}</Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-text-muted">
                    <Clock className="h-3 w-3" />
                    <span>{timeAgo(job.created_at)}</span>
                    {job.total_blocks != null && <span>· {job.total_blocks} blocks</span>}
                  </div>
                </div>
              </Link>
            ))
          )}
        </div>
      </div>

      {/* Quick links */}
      <div className="grid gap-3 rounded-xl border border-border bg-surface-card p-4 sm:grid-cols-4">
        <Link href="/report-builder/binding" className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-text transition-colors hover:bg-surface hover:text-primary">
          <Database className="h-4 w-4" /> Dataset Binder
        </Link>
        <Link href="/report-builder/canvas" className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-text transition-colors hover:bg-surface hover:text-primary">
          <BookOpen className="h-4 w-4" /> Report Canvas
        </Link>
        <Link href="/report/report-ast-generator" className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-text transition-colors hover:bg-surface hover:text-primary">
          <FunctionSquare className="h-4 w-4" /> Template Extraction
        </Link>
        <Link href="/upload" className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-text transition-colors hover:bg-surface hover:text-primary">
          <Plus className="h-4 w-4" /> Upload dataset
        </Link>
      </div>
    </div>
  );
}
