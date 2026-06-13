'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { reportBuilderApi, ReportTemplateWithAst } from '@/lib/api';
import { resolveTemplateBySlug } from '@/lib/templateRouteUtils';
import TemplateAstExplorer from './TemplateAstExplorer';

const AST_GENERATOR_BASE = '/report/report-ast-generator';

export default function TemplateDetailView({ templateSlug }: { templateSlug: string }) {
  const router = useRouter();
  const [template, setTemplate] = useState<ReportTemplateWithAst | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      setTemplate(null);
      try {
        const templates = await reportBuilderApi.listTemplates();
        const matched = resolveTemplateBySlug(templates, templateSlug);
        if (!matched) {
          if (!cancelled) {
            setError('Template not found.');
            setLoading(false);
          }
          return;
        }
        const full = await reportBuilderApi.getTemplate(matched.id);
        if (!cancelled) {
          setTemplate(full);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load template AST');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [templateSlug]);

  const ast =
    template?.ast && typeof template.ast === 'object' ? template.ast : null;

  return (
    <div className="mx-auto max-w-7xl">
      <header className="mb-6">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push(AST_GENERATOR_BASE)}
          className="mb-4 gap-1.5 -ml-2 text-text-muted hover:text-text"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to all templates
        </Button>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-primary">
              Template blueprint
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-text sm:text-3xl">
              {template?.name ?? 'Loading template…'}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-muted">
              This is the structured output reverse-engineered from your MoSPI PDF — layout,
              data fields, tables, charts, and the report blueprint your dataset will fill in.
            </p>
          </div>

          {template && (
            <div className="flex flex-wrap gap-2 sm:justify-end">
              <Badge variant="muted">Template #{template.id}</Badge>
              {template.page_count != null && (
                <Badge variant="muted">{template.page_count} pages</Badge>
              )}
              {template.block_count != null && (
                <Badge variant="muted">{template.block_count} layout pieces</Badge>
              )}
              {template.extraction_method && (
                <Badge variant="success">{template.extraction_method}</Badge>
              )}
            </div>
          )}
        </div>
      </header>

      {error && <Alert variant="error">{error}</Alert>}

      {error && !loading && (
        <div className="mt-4">
          <Link href={AST_GENERATOR_BASE}>
            <Button variant="outline" size="sm">
              Return to templates
            </Button>
          </Link>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 py-16 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading template blueprint…
        </div>
      )}

      {!loading && ast && <TemplateAstExplorer ast={ast} />}

      {!loading && template && !ast && !error && (
        <Alert variant="warning">
          No AST data is stored for this template. Upload the PDF again from the AST Generator
          page to run extraction.
        </Alert>
      )}
    </div>
  );
}
