'use client';

/**
 * Canvas landing — select an existing binder to open in the Report Canvas.
 * If the user arrives from S3.5 handoff, they get redirected to /canvas/[tid]/[sig] directly.
 * This page is for standalone access when the officer wants to pick from saved binders.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowRight, BookOpen, Database, Loader2, Sparkles } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { bindingPhaseApi, type BindingTemplatePackage } from '@/lib/api';

export default function CanvasLandingPage() {
  const router = useRouter();
  const [templates, setTemplates] = useState<BindingTemplatePackage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    bindingPhaseApi.listTemplatePackages()
      .then(setTemplates)
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  const validTemplates = templates.filter(t => t.status === 'VALID');

  return (
    <div className="mx-auto max-w-4xl space-y-6 pb-12">
      <PageHeader
        title="Report Canvas"
        description="Select a finalized binder to open in the generation canvas with Deep BI Agent."
        actions={
          <Link href="/report-builder/binding">
            <Button variant="outline" size="sm"><Database className="h-4 w-4" /> Start new binding</Button>
          </Link>
        }
      />

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-slate-300" />
        </div>
      ) : validTemplates.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface-card p-8 text-center">
          <BookOpen className="mx-auto h-10 w-10 text-slate-200" />
          <h3 className="mt-4 text-base font-semibold text-text">No binders ready yet</h3>
          <p className="mt-2 text-sm text-text-muted">
            Complete the Dataset Binder workflow (S0→S3.5) to create a finalized binder, then return here to generate.
          </p>
          <Link href="/report-builder/binding" className="mt-4 inline-block">
            <Button><Sparkles className="h-4 w-4" /> Start Dataset Binding</Button>
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-text-muted">
            Select a template below. You need a finalized binding (completed S3.5 handoff) for that template to use the canvas.
          </p>
          {validTemplates.map((tpl) => (
            <button
              key={tpl.template_id}
              type="button"
              onClick={() => {
                // For valid templates, navigate to a placeholder sig that the canvas will handle
                // In production, this would show a list of saved binder signatures for this template
                router.push(`/report-builder/binding`);
              }}
              className="flex w-full items-center justify-between gap-4 rounded-xl border border-border bg-surface-card px-5 py-4 text-left transition-all hover:border-primary/40 hover:shadow-sm"
            >
              <div className="flex items-center gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  {tpl.source === 'built_in' ? <Sparkles className="h-5 w-5" /> : <Database className="h-5 w-5" />}
                </div>
                <div>
                  <p className="text-sm font-semibold text-text">{tpl.name}</p>
                  <p className="mt-0.5 text-xs text-text-muted">
                    {tpl.topics_count} topics · {tpl.questions_count} questions · {tpl.entities_count} entities
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={tpl.status === 'VALID' ? 'success' : 'warning'}>{tpl.status}</Badge>
                <ArrowRight className="h-4 w-4 text-slate-300" />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
